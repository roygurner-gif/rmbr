"""Security guards: Host check, CSRF header, token, nuke scope, bind refusal."""
import http.client
import importlib.util
import json
import subprocess
import sys
import threading
from http.server import HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load(monkeypatch, **env):
    for k in ("RMBR_HOST", "RMBR_TOKEN", "RMBR_ALLOWED_HOSTS", "RMBR_CONFIG"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("RMBR_CONFIG", "/nonexistent/rmbr.json")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    spec = importlib.util.spec_from_file_location("rmbr_under_test", ROOT / "rmbr.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def server(monkeypatch):
    started = []

    def start(**env):
        mod = load(monkeypatch, **env)
        srv = HTTPServer(("127.0.0.1", 0), mod.RmbrHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        started.append(srv)
        return mod, srv.server_address[1]
    yield start
    for s in started:
        s.shutdown()


def req(port, method, path, headers=None, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    return r.status, dict(r.getheaders()), data


OK = {"X-RMBR": "1"}


def test_api_requires_custom_header_and_sends_no_cors(server):
    _, port = server()
    assert req(port, "GET", "/api/status")[0] == 403                 # cross-site fetch can't add it
    st, hdrs, body = req(port, "GET", "/api/status", OK)
    assert st == 200 and "Access-Control-Allow-Origin" not in hdrs
    assert req(port, "POST", "/api/nuke", {"Content-Type": "text/plain"}, b"x")[0] == 403
    assert req(port, "GET", "/health")[0] == 200                    # non-API stays open
    assert req(port, "GET", "/")[0] == 200


def test_dns_rebinding_host_rejected(server):
    _, port = server()
    assert req(port, "GET", "/api/status", {**OK, "Host": "evil.example:8889"})[0] == 403
    assert req(port, "GET", "/", {"Host": "evil.example"})[0] == 403
    assert req(port, "GET", "/api/status", {**OK, "Host": "localhost:8889"})[0] == 200
    assert req(port, "GET", "/api/status", {**OK, "Host": "[::1]:8889"})[0] == 200


def test_allowed_hosts_and_token(server):
    _, port = server(RMBR_TOKEN="s3cret", RMBR_ALLOWED_HOSTS="rmbr.lan")
    h = {**OK, "Host": "rmbr.lan"}
    assert req(port, "GET", "/api/status", h)[0] == 401
    assert req(port, "GET", "/api/status", {**h, "X-RMBR-Token": "nope"})[0] == 401
    assert req(port, "GET", "/api/status", {**h, "X-RMBR-Token": "s3cret"})[0] == 200


def test_bad_bodies(server):
    _, port = server()
    assert req(port, "POST", "/api/balance", {**OK, "Content-Length": "999999999"})[0] == 413
    assert req(port, "POST", "/api/balance", OK, b"{not json")[0] == 400
    assert req(port, "POST", "/api/balance", OK, b"[1,2]")[0] == 400
    assert req(port, "POST", "/api/balance", OK, json.dumps({"balance": 5}).encode())[0] == 200


def test_nuke_deletes_only_spam_files(monkeypatch):
    mod = load(monkeypatch)
    emails = [
        {"spam": True, "_path": "/var/mail/vhosts/ex.com/roy/Maildir/new/1700.M1.host"},
        {"spam": False, "_path": "/var/mail/vhosts/ex.com/roy/Maildir/new/1700.M2.host"},
        {"spam": True, "_path": "/var/mail/vhosts/ex.com/roy/Maildir/new/*"},          # glob
        {"spam": True, "_path": "/var/mail/vhosts/ex.com/roy/Maildir/new/a;rm -rf ~"},  # injection
        {"spam": True, "_path": "/etc/passwd"},
        {"spam": True},
    ]
    assert mod.spam_paths(emails) == ["/var/mail/vhosts/ex.com/roy/Maildir/new/1700.M1.host"]
    assert all("_path" not in e for e in mod.public_emails(emails))


def test_refuses_network_bind_without_token():
    env = {"RMBR_HOST": "0.0.0.0", "RMBR_CONFIG": "/nonexistent", "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, str(ROOT / "rmbr.py")], env=env,
                       capture_output=True, text=True, timeout=20)
    assert r.returncode != 0 and "refusing to bind" in r.stderr
