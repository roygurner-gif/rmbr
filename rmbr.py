#!/usr/bin/env python3
"""
RMBR — Remember Everything You Forget
QOS Service — Life Dashboard

Pulls email from Dovecot on VPS, monitors systems, shows you
everything you need to know on one screen.

Roy W. Gurner | Occam Engineering | 2026
"""
import os
import sys
import json
import time
import imaplib
import email
import subprocess
import urllib.request
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from email.header import decode_header

PORT = 8889
VPS_HOST = "148.230.94.100"
REFRESH_INTERVAL = 300  # 5 minutes
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LLM_BACKEND = "anthropic" if ANTHROPIC_API_KEY else "local"

# Email accounts to check
MAIL_ACCOUNTS = [
    {"user": "roy@anticloud.pro", "server": VPS_HOST, "port": 993},
    {"user": "contact@pepperpllc.com", "server": VPS_HOST, "port": 993},
    {"user": "contact@simpl.studio", "server": VPS_HOST, "port": 993},
]

# State
STATE = {
    "emails": [],
    "email_count": 0,
    "last_check": None,
    "bank_balance": None,
    "next_bill": None,
    "calendar": [],
    "status": "ok",
}

def check_calendar():
    """Pull upcoming events from macOS Calendar via icalBuddy."""
    try:
        result = subprocess.run(
            ["icalBuddy", "-n", "eventsToday+7"],
            capture_output=True, text=True, timeout=10
        )
        events = []
        current_title = None
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            if line.startswith('•') or line.startswith('* '):
                current_title = line.lstrip('•* ').strip()
            elif line.startswith('    ') and current_title:
                when = line.strip()
                events.append({"title": current_title, "when": when})
                current_title = None
            elif current_title and not line.startswith(' '):
                events.append({"title": current_title, "when": ""})
                current_title = line.lstrip('•* ').strip()
        if current_title:
            events.append({"title": current_title, "when": ""})
        STATE["calendar"] = events
    except Exception as e:
        STATE["calendar"] = [{"title": f"Calendar error: {e}", "when": ""}]

# Bot filter for spam detection
SPAM_KEYWORDS = [
    "cloud storage", "urology", "wellness insider", "weight loss",
    "gelatin", "prostate", "storage renewal", "account locked",
    "payment failed", "seo expert", "web presence", "build your app",
    "data entry", "virtual assistant"
]

def decode_mime_header(header):
    """Decode MIME encoded email headers."""
    if not header:
        return ""
    parts = decode_header(header)
    result = []
    for part, encoding in parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(encoding or 'utf-8', errors='replace'))
            except:
                result.append(part.decode('utf-8', errors='replace'))
        else:
            result.append(part)
    return ' '.join(result)

def is_spam(from_addr, subject):
    """Check if email is likely spam."""
    combined = (from_addr + " " + subject).lower()
    return any(kw in combined for kw in SPAM_KEYWORDS)

def check_emails():
    """Pull emails from all Dovecot accounts on VPS."""
    all_emails = []

    for account in MAIL_ACCOUNTS:
        try:
            # Connect via IMAP over SSH tunnel or direct SSL
            mail = imaplib.IMAP4_SSL(account["server"], account["port"])
            mail.login(account["user"], get_password(account["user"]))
            mail.select("INBOX")

            # Get unread emails
            status, messages = mail.search(None, "UNSEEN")
            if status == "OK" and messages[0]:
                msg_ids = messages[0].split()
                for msg_id in msg_ids[-20:]:  # Last 20 unread
                    status, data = mail.fetch(msg_id, "(RFC822)")
                    if status == "OK":
                        msg = email.message_from_bytes(data[0][1])
                        from_addr = decode_mime_header(msg["From"])
                        subject = decode_mime_header(msg["Subject"])
                        date = msg["Date"]

                        spam = is_spam(from_addr, subject)

                        all_emails.append({
                            "account": account["user"],
                            "from": from_addr[:60],
                            "subject": subject[:80],
                            "date": date,
                            "spam": spam,
                            "msg_id": msg_id.decode(),
                        })

            mail.logout()
        except Exception as e:
            all_emails.append({
                "account": account["user"],
                "from": "ERROR",
                "subject": str(e)[:80],
                "date": datetime.now().isoformat(),
                "spam": False,
                "msg_id": "",
            })

    # Sort: real emails first, then spam
    all_emails.sort(key=lambda x: (x["spam"], x["date"]), reverse=False)

    STATE["emails"] = all_emails
    STATE["email_count"] = len([e for e in all_emails if not e["spam"]])
    STATE["last_check"] = datetime.now().isoformat()

def check_emails_ssh():
    """Fallback: check emails via SSH to VPS (no IMAP password needed)."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=10", f"root@{VPS_HOST}",
             """
             for box in /var/mail/vhosts/*/; do
                 domain=$(basename "$box")
                 for user in "$box"*/; do
                     uname=$(basename "$user")
                     for f in "${user}Maildir/new/"*; do
                         [ -f "$f" ] || continue
                         from=$(grep -m1 "^From:" "$f" 2>/dev/null | head -c 80)
                         subj=$(grep -m1 "^Subject:" "$f" 2>/dev/null | head -c 80)
                         echo "${uname}@${domain}|${from}|${subj}"
                     done
                 done
             done
             """],
            capture_output=True, text=True, timeout=30
        )

        all_emails = []
        for line in result.stdout.strip().split('\n'):
            if '|' not in line:
                continue
            parts = line.split('|', 2)
            if len(parts) < 3:
                continue
            account = parts[0]
            from_addr = parts[1].replace("From: ", "")[:60]
            subject = parts[2].replace("Subject: ", "")[:80]
            spam = is_spam(from_addr, subject)

            all_emails.append({
                "account": account,
                "from": from_addr,
                "subject": subject,
                "date": "",
                "spam": spam,
                "msg_id": "",
            })

        all_emails.sort(key=lambda x: x["spam"])
        STATE["emails"] = all_emails
        STATE["email_count"] = len([e for e in all_emails if not e["spam"]])
        STATE["last_check"] = datetime.now().isoformat()

    except Exception as e:
        STATE["emails"] = [{"account": "error", "from": "SSH Error", "subject": str(e), "date": "", "spam": False, "msg_id": ""}]

def get_password(user):
    """Get email password from config."""
    config_file = Path("/opt/qos/config/mail_passwords.json")
    if not config_file.exists():
        config_file = Path.home() / ".qos" / "mail_passwords.json"
    if config_file.exists():
        with open(config_file) as f:
            passwords = json.load(f)
        return passwords.get(user, "")
    return ""

def set_balance(balance, next_bill=None):
    """Manually set bank balance."""
    STATE["bank_balance"] = balance
    if next_bill:
        STATE["next_bill"] = next_bill

class RmbrHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/api/emails":
            self._json({"emails": STATE["emails"], "count": STATE["email_count"], "last_check": STATE["last_check"]})
        elif self.path == "/api/calendar":
            check_calendar()
            self._json({"events": STATE["calendar"]})
        elif self.path == "/api/status":
            self._json(STATE)
        elif self.path == "/api/refresh":
            check_emails_ssh()
            check_calendar()
            self._json({"refreshed": True, "count": STATE["email_count"]})
        elif self.path == "/health":
            self._json({"status": "OK", "service": "rmbr"})
        elif self.path == "/old":
            self._html(DASHBOARD)
        elif self.path == "/":
            kanban_path = Path(__file__).parent.parent / "web" / "kanban.html"
            if kanban_path.exists():
                self._html(kanban_path.read_text())
            else:
                self._html(DASHBOARD)
        else:
            self.send_error(404)

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)

        if self.path == "/api/balance":
            data = json.loads(body)
            set_balance(data.get("balance"), data.get("next_bill"))
            self._json({"updated": True})
        elif self.path == "/api/ask":
            data = json.loads(body)
            question = data.get("question", "")

            # Build context from RMBR state
            context_parts = []
            if STATE["bank_balance"] is not None:
                context_parts.append(f"Bank balance: ${STATE['bank_balance']:,}")
            if STATE["next_bill"]:
                context_parts.append(f"Next bill: {STATE['next_bill']}")
            if STATE["calendar"]:
                cal_lines = [f"- {e['title']}: {e['when']}" for e in STATE["calendar"]]
                context_parts.append("Upcoming calendar:\n" + "\n".join(cal_lines))
            if STATE["emails"]:
                real = [e for e in STATE["emails"] if not e["spam"]]
                spam_count = len(STATE["emails"]) - len(real)
                context_parts.append(f"Emails: {len(real)} real, {spam_count} spam")
                if real:
                    email_lines = [f"- From: {e['from']} | Subject: {e['subject']}" for e in real[:5]]
                    context_parts.append("Real emails:\n" + "\n".join(email_lines))
            else:
                context_parts.append("Emails: Inbox zero")

            context = "\n".join(context_parts)
            today = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")

            system_prompt = f"You are RMBR, a personal AI assistant running on QOS (Quantum Operating System). You have access to the user's real data. Today is {today}. Be concise and direct. Answer from the data below.\n\nCURRENT STATE:\n{context}"

            try:
                if LLM_BACKEND == "anthropic":
                    llm_body = json.dumps({
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 200,
                        "system": system_prompt,
                        "messages": [
                            {"role": "user", "content": question}
                        ]
                    }).encode()
                    req = urllib.request.Request(
                        "https://api.anthropic.com/v1/messages",
                        data=llm_body,
                        headers={
                            "Content-Type": "application/json",
                            "x-api-key": ANTHROPIC_API_KEY,
                            "anthropic-version": "2023-06-01"
                        }
                    )
                    resp = urllib.request.urlopen(req, timeout=30)
                    result = json.loads(resp.read())
                    answer = result["content"][0]["text"]
                else:
                    llm_body = json.dumps({
                        "model": "mlx-community/Qwen2.5-14B-Instruct-4bit",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": question}
                        ],
                        "max_tokens": 200
                    }).encode()
                    req = urllib.request.Request(
                        "http://localhost:8003/v1/chat/completions",
                        data=llm_body,
                        headers={"Content-Type": "application/json"}
                    )
                    resp = urllib.request.urlopen(req, timeout=30)
                    result = json.loads(resp.read())
                    answer = result["choices"][0]["message"]["content"]

                self._json({"answer": answer})
            except Exception as e:
                self._json({"answer": f"LLM offline ({LLM_BACKEND}): {e}"})
        elif self.path == "/api/nuke":
            # Delete all spam emails via SSH
            try:
                subprocess.run(
                    ["ssh", "-o", "ConnectTimeout=10", f"root@{VPS_HOST}",
                     "rm -f /var/mail/vhosts/anticloud.pro/roy/Maildir/new/* /var/mail/vhosts/pepperpllc.com/contact/Maildir/new/* /var/mail/vhosts/simpl.studio/contact/Maildir/new/*"],
                    capture_output=True, timeout=15
                )
                check_emails_ssh()
                self._json({"nuked": True, "remaining": STATE["email_count"]})
            except Exception as e:
                self._json({"error": str(e)})
        else:
            self.send_error(404)

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

DASHBOARD = r"""<!DOCTYPE html>
<html>
<head>
<title>RMBR — Remember Everything</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0a0a0f; color:#e0e0e0; font-family:'SF Mono',Menlo,monospace; }

.header { background:#0d0d14; border-bottom:1px solid #1a1a2e; padding:16px 24px; display:flex; justify-content:space-between; align-items:center; }
.logo { font-size:20px; font-weight:700; color:#f59e0b; letter-spacing:3px; }
.logo span { color:#666; font-size:12px; font-weight:300; }
.tagline { color:#555; font-size:11px; }

.container { max-width:900px; margin:0 auto; padding:20px; }

.balance-card { background:linear-gradient(135deg, #111118, #1a1a2e); border:1px solid #f59e0b; border-radius:16px; padding:40px; text-align:center; margin-bottom:20px; }
.balance-amount { font-size:48px; font-weight:700; color:#0f6; }
.balance-label { font-size:12px; color:#666; text-transform:uppercase; letter-spacing:2px; margin-top:8px; }
.balance-ok { font-size:14px; color:#0f6; margin-top:12px; }
.next-bill { color:#888; font-size:13px; margin-top:8px; }

.section { background:#111118; border:1px solid #1a1a2e; border-radius:12px; margin-bottom:16px; overflow:hidden; }
.section-header { padding:14px 20px; border-bottom:1px solid #1a1a2e; display:flex; justify-content:space-between; align-items:center; }
.section-title { font-size:13px; font-weight:600; color:#fff; text-transform:uppercase; letter-spacing:1px; }
.badge { background:rgba(245,158,11,0.2); color:#f59e0b; padding:3px 10px; border-radius:10px; font-size:11px; font-weight:600; }
.badge.spam { background:rgba(255,68,68,0.2); color:#f44; }

.email-row { display:grid; grid-template-columns:1fr 2fr 60px; padding:12px 20px; border-bottom:1px solid #0d0d14; align-items:center; }
.email-row.spam { opacity:0.4; }
.email-from { color:#ccc; font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.email-subject { color:#888; font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.email-tag { font-size:10px; text-align:right; }
.email-tag.real { color:#0f6; }
.email-tag.junk { color:#f44; }

.btn { background:none; border:1px solid #333; color:#666; padding:6px 14px; border-radius:6px; font-size:11px; cursor:pointer; font-family:inherit; }
.btn:hover { border-color:#f59e0b; color:#f59e0b; }
.btn.danger { border-color:#f44; color:#f44; }
.btn.danger:hover { background:rgba(255,68,68,0.1); }

.footer { text-align:center; padding:20px; color:#333; font-size:10px; }
</style>
</head>
<body>

<div class="header">
    <div><div class="logo">RMBR <span>Quantum Operating System</span></div></div>
    <div class="tagline">remembers everything you forget</div>
</div>

<div class="container">
    <div class="balance-card">
        <div class="balance-label">Checking</div>
        <div class="balance-amount" id="balance">—</div>
        <div class="balance-ok" id="balanceOk"></div>
        <div class="next-bill" id="nextBill"></div>
    </div>

    <div class="section">
        <div class="section-header">
            <span class="section-title">Emails</span>
            <div style="display:flex;gap:8px">
                <span class="badge" id="emailCount">0</span>
                <button class="btn" onclick="refreshEmails()">Refresh</button>
                <button class="btn danger" onclick="nukeSpam()">Nuke Spam</button>
            </div>
        </div>
        <div id="emails"></div>
    </div>
</div>

    <div class="section">
        <div class="section-header">
            <span class="section-title">Calendar</span>
            <span class="badge" id="calCount">0</span>
        </div>
        <div id="calendar"></div>
    </div>

    <div class="section">
        <div class="section-header">
            <span class="section-title">Ask RMBR</span>
            <span class="badge" id="llmStatus">14B</span>
        </div>
        <div style="padding:16px 20px">
            <div style="display:flex;gap:8px">
                <input type="text" id="askInput" placeholder="RMBR, what's my..." style="flex:1;padding:10px;background:#0a0a0f;border:1px solid #333;color:#e0e0e0;font-family:inherit;font-size:13px;border-radius:6px" onkeypress="if(event.key==='Enter')askRmbr()">
                <button class="btn" onclick="askRmbr()" style="background:#f59e0b;color:#0a0a0f;border:none;font-weight:600">Ask</button>
            </div>
            <div id="answer" style="margin-top:12px;color:#ccc;font-size:13px;line-height:1.6;min-height:20px"></div>
        </div>
    </div>

<div class="footer">RMBR — because you forgot again</div>

<script>
async function loadStatus() {
    try {
        const r = await fetch('/api/status');
        const d = await r.json();

        if (d.bank_balance !== null) {
            document.getElementById('balance').textContent = '$' + d.bank_balance.toLocaleString();
            document.getElementById('balanceOk').textContent = '✓ you\\'re fine';
        } else {
            document.getElementById('balance').textContent = '—';
            document.getElementById('balanceOk').textContent = 'POST /api/balance to set';
        }

        if (d.next_bill) {
            document.getElementById('nextBill').textContent = 'Next bill: ' + d.next_bill;
        }

        // Calendar
        const cal = d.calendar || [];
        document.getElementById('calCount').textContent = cal.length + ' upcoming';
        let chtml = '';
        for (const ev of cal) {
            chtml += '<div style="display:flex;justify-content:space-between;padding:10px 20px;border-bottom:1px solid #0d0d14">' +
                '<span style="color:#ccc;font-size:13px">' + ev.title + '</span>' +
                '<span style="color:#f59e0b;font-size:12px">' + ev.when + '</span>' +
                '</div>';
        }
        document.getElementById('calendar').innerHTML = chtml || '<div style="padding:20px;color:#555;text-align:center">No upcoming events.</div>';

        const real = d.emails.filter(e => !e.spam);
        const spam = d.emails.filter(e => e.spam);
        document.getElementById('emailCount').textContent = real.length + ' real / ' + spam.length + ' spam';

        let html = '';
        for (const e of d.emails) {
            html += '<div class="email-row' + (e.spam ? ' spam' : '') + '">' +
                '<div class="email-from">' + e.from + '</div>' +
                '<div class="email-subject">' + e.subject + '</div>' +
                '<div class="email-tag ' + (e.spam ? 'junk' : 'real') + '">' + (e.spam ? 'SPAM' : 'REAL') + '</div>' +
                '</div>';
        }
        document.getElementById('emails').innerHTML = html || '<div style="padding:20px;color:#555;text-align:center">No emails. Inbox zero.</div>';

    } catch(e) {
        document.getElementById('balance').textContent = 'OFFLINE';
    }
}

async function refreshEmails() {
    document.getElementById('emailCount').textContent = 'checking...';
    await fetch('/api/refresh');
    loadStatus();
}

async function nukeSpam() {
    if (confirm('Nuke all emails?')) {
        await fetch('/api/nuke', {method: 'POST'});
        loadStatus();
    }
}

async function askRmbr() {
    const input = document.getElementById('askInput');
    const answer = document.getElementById('answer');
    const q = input.value.trim();
    if (!q) return;
    answer.textContent = 'thinking...';
    answer.style.color = '#f59e0b';
    try {
        const r = await fetch('/api/ask', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({question: q})
        });
        const d = await r.json();
        answer.textContent = d.answer;
        answer.style.color = '#ccc';
    } catch(e) {
        answer.textContent = 'LLM offline';
        answer.style.color = '#f44';
    }
    input.value = '';
}

loadStatus();
setInterval(loadStatus, 60000);
</script>
</body>
</html>"""

if __name__ == "__main__":
    print(f"  [RMBR] Dashboard on :{PORT}")
    print(f"  [RMBR] LLM backend: {LLM_BACKEND}" + (" (Haiku 4.5)" if LLM_BACKEND == "anthropic" else " (local MLX)"))
    print(f"  [RMBR] Checking emails via SSH to {VPS_HOST}")

    # Initial checks
    check_emails_ssh()
    check_calendar()
    print(f"  [RMBR] Found {STATE['email_count']} real emails, {len(STATE['emails']) - STATE['email_count']} spam")
    print(f"  [RMBR] Found {len(STATE['calendar'])} calendar events")

    server = HTTPServer(("0.0.0.0", PORT), RmbrHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
