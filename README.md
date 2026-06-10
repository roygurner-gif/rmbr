# RMBR — Life Board

**One screen. All signals.**
A self-hosted life dashboard: kanban + email + calendar + finances + ask-an-LLM, in one tab.

Built for operators who don't want Trello + Notion + Todoist + Gmail + Calendar + their bank app open at the same time. RMBR pulls it all to one URL.

```
┌─────────────────────────────────────────────────────────────┐
│  RMBR   Life Board                            14:32  ◉ OK   │
├─────────────────────────────────────────────────────────────┤
│  TODO (3)        │  DOING (1)       │  DONE (12)            │
│  ─────────────   │  ─────────────   │  ─────────────        │
│  • Renew passport│  • Refactor auth │  ✓ Pay rent           │
│  • Call dentist  │                  │  ✓ Submit timesheet   │
│  • Book flight   │                  │  ✓ Inbox zero         │
├─────────────────────────────────────────────────────────────┤
│  Ask RMBR ▸ "what bills are coming up this week?"           │
├─────────────────────────────────────────────────────────────┤
│  $4,217  ◉ ok   │  📧 3 real / 28 spam  │  🐙 2 commits     │
└─────────────────────────────────────────────────────────────┘
```

## Who it's for

- Technical founders running multiple projects
- Operators who want **one terminal-aesthetic screen**, not a cloud SaaS dashboard
- People who run their own VPS, their own mail, their own everything
- Anyone who's tired of context-switching between five apps to know what's going on

## What it does

| Pane | Source |
|---|---|
| **Kanban board** (TODO / DOING / DONE) | Local JSON, persists in browser |
| **Email** (real vs spam, multi-account) | IMAP, or SSH to your VPS Dovecot maildirs |
| **Calendar** (next 7 days) | macOS Calendar via `icalBuddy` |
| **Bank balance + next bill** | Manual (POST `/api/balance`) — no scraping |
| **Ask RMBR** (chat with your dashboard state) | Local OpenAI-compatible LLM endpoint (MLX / Ollama / vLLM / llama.cpp) |

## Install

```bash
git clone <this-repo>
cd rmbr
mkdir -p ~/.rmbr && cp config.example.json ~/.rmbr/config.json   # then edit
python3 rmbr.py
```

Open <http://localhost:8889>.

### Requirements
- Python 3.9+ (stdlib only — no pip install)
- macOS for calendar pane (uses `icalBuddy`); optional otherwise
- A VPS running Dovecot with vhosts at `/var/mail/vhosts/<domain>/<user>/Maildir/` (optional)
- A local OpenAI-compatible LLM endpoint for "Ask RMBR" (optional — works without it, just disables that pane)

### Config

`~/.rmbr/config.json` — see `config.example.json` for the full schema.

```json
{
  "vps_host": "your.vps.example.com",
  "vps_ssh_user": "root",
  "mail_accounts": [
    {"user": "you@yourdomain.com", "server": "your.vps.example.com", "port": 993}
  ],
  "local_llm_url": "http://localhost:8003/v1/chat/completions",
  "local_llm_model": "mlx-community/Qwen2.5-14B-Instruct-4bit"
}
```

Env overrides: `RMBR_PORT`, `RMBR_CONFIG`, `RMBR_VPS_HOST`.

## API

| Endpoint | Method | What |
|---|---|---|
| `/` | GET | Kanban UI |
| `/old` | GET | Legacy dashboard UI |
| `/health` | GET | `{"status": "OK"}` |
| `/api/status` | GET | Full state JSON |
| `/api/emails` | GET | Email list |
| `/api/calendar` | GET | Re-pull calendar |
| `/api/refresh` | GET | Re-pull email + calendar |
| `/api/balance` | POST | `{"balance": 4217, "next_bill": "AT&T $89 Jun 15"}` |
| `/api/ask` | POST | `{"question": "what bills this week?"}` → LLM answer with full RMBR state as context |
| `/api/nuke` | POST | ⚠️ Delete all unread mail in configured mailboxes via SSH |

## Why not Trello / Notion / Todoist?

- **Self-hosted.** Your life data on your hardware. No cloud, no subscription, no exfil.
- **One screen.** Not a kanban app you also have to keep open alongside email + calendar.
- **Ask anything.** "What's on the board, what bills are due, what emails matter — pick one." That query works because the LLM has the full state as context.
- **Terminal aesthetic.** If `htop` is more comforting than Notion, this is for you.
- **Hackable.** ~600 lines of Python, no framework, no ORM, no build step.

## License

MIT — see [LICENSE](LICENSE).
