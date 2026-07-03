"""
serve_dashboard.py — Local network dashboard server.

Serves jira_report.html on port 8080 bound to all interfaces.
Proxies Jira comment read/write through two API routes so the browser
never holds credentials and CORS is not an issue.

Routes:
    GET  /                         → dashboard HTML
    GET  /api/comments/{issueKey}  → fetch comments from Jira
    POST /api/comments/{issueKey}  → post a new comment to Jira

Intended to run continuously as a Windows Scheduled Task (At Startup).

Usage:
    python serve_dashboard.py
"""

import base64
import html as _html
import json
import logging
import os
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT      = 8080
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD = os.path.join(SCRIPT_DIR, "jira_report.html")
LOG_DIR   = os.path.join(SCRIPT_DIR, "logs")

os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "dashboard_server.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


def _load_env():
    path = os.path.join(SCRIPT_DIR, ".env")
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r'^\s*([^#][^=]*?)\s*=\s*(.+?)\s*$', line)
                if m:
                    env[m.group(1).strip()] = m.group(2).strip()
    except FileNotFoundError:
        log.warning(".env not found — comment proxy will not work.")
    return env


_ENV      = _load_env()
_BASE_URL = _ENV.get("JIRA_BASE_URL", "https://yourcompany.atlassian.net/rest/api/3")  # placeholder default — set JIRA_BASE_URL in .env
_EMAIL    = _ENV.get("JIRA_EMAIL", "")
_TOKEN    = _ENV.get("JIRA_API_TOKEN", "")
_PROJECT  = _ENV.get("JIRA_PROJECT_KEY", "IT")
_KEY_RE   = re.compile(rf'^{re.escape(_PROJECT)}-\d+$', re.IGNORECASE)


def _auth_headers():
    creds = base64.b64encode(f"{_EMAIL}:{_TOKEN}".encode()).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


def _adf_to_text(node):
    """Recursively extract plain text from an Atlassian Document Format node."""
    if not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return node.get("text", "")
    parts = [_adf_to_text(c) for c in node.get("content", [])]
    sep = "\n" if node.get("type") in ("paragraph", "listItem", "heading", "bulletList", "orderedList") else " "
    return sep.join(p for p in parts if p)


def _sanitize(text):
    """Strip HTML tags, unescape entities, and cap at 2000 characters."""
    text = _html.unescape(str(text))
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()[:2000]


def _jira_get_comments(issue_key):
    url = f"{_BASE_URL}/issue/{issue_key}/comment?maxResults=50&orderBy=created"
    req = urllib.request.Request(url, headers=_auth_headers())
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)
    return [
        {
            "id":      c["id"],
            "author":  c["author"].get("displayName", "Unknown"),
            "text":    _adf_to_text(c.get("body", {})),
            "created": c["created"][:10],
        }
        for c in data.get("comments", [])
    ]


def _jira_post_comment(issue_key, text):
    url  = f"{_BASE_URL}/issue/{issue_key}/comment"
    body = json.dumps({
        "body": {
            "version": 1, "type": "doc",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }
    }).encode()
    req = urllib.request.Request(url, data=body, headers=_auth_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


class DashboardHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path in ("/", "/index.html", "/jira_report.html"):
            self._serve_dashboard()
        elif self.path.startswith("/api/comments/"):
            self._handle_get_comments()
        else:
            self.send_error(404, "Not found")

    def do_POST(self):
        if self.path.startswith("/api/comments/"):
            self._handle_post_comment()
        else:
            self.send_error(404, "Not found")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── Dashboard HTML ──────────────────────────────────────────────────────

    def _serve_dashboard(self):
        if not os.path.exists(DASHBOARD):
            self.send_error(503, "Dashboard not yet generated — run jira_fetcher.ps1 first")
            return
        with open(DASHBOARD, "rb") as f:
            content = f.read()
        modified = datetime.fromtimestamp(os.path.getmtime(DASHBOARD)).strftime("%Y-%m-%d %H:%M")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Dashboard-Generated", modified)
        self.end_headers()
        self.wfile.write(content)

    # ── Comment proxy routes ────────────────────────────────────────────────

    def _issue_key(self):
        """Extract and validate issue key from /api/comments/{key}."""
        parts = self.path.split("/")
        raw   = parts[3].split("?")[0] if len(parts) >= 4 else ""
        key   = raw.upper()
        return key if _KEY_RE.match(key) else None

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type",  "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _handle_get_comments(self):
        key = self._issue_key()
        if not key:
            self._json({"error": "Invalid issue key"}, 400)
            return
        try:
            comments = _jira_get_comments(key)
            self._json({"comments": comments})
        except urllib.error.HTTPError as e:
            self._json({"error": f"Jira returned {e.code}"}, 502)
        except Exception as e:
            log.error(f"GET comments {key}: {e}")
            self._json({"error": "Server error"}, 500)

    def _handle_post_comment(self):
        key = self._issue_key()
        if not key:
            self._json({"error": "Invalid issue key"}, 400)
            return
        try:
            length  = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length))
            text    = _sanitize(payload.get("text", ""))
            if not text:
                self._json({"error": "Comment text is empty"}, 400)
                return
            result = _jira_post_comment(key, text)
            log.info(f"Comment posted to {key}: id={result.get('id')}")
            self._json({"id": result.get("id"), "created": (result.get("created") or "")[:10]})
        except urllib.error.HTTPError as e:
            self._json({"error": f"Jira returned {e.code}"}, 502)
        except Exception as e:
            log.error(f"POST comment {key}: {e}")
            self._json({"error": "Server error"}, 500)

    def log_message(self, fmt, *args):
        log.info(f"{self.address_string()} - {fmt % args}")


def get_local_ips():
    ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ":" not in ip and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return list(dict.fromkeys(ips))


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), DashboardHandler)
    log.info(f"Dashboard server started on port {PORT}")
    log.info(f"Dashboard file: {DASHBOARD}")
    for ip in get_local_ips():
        log.info(f"  -> http://{ip}:{PORT}")
    log.info("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Server stopped.")
        server.server_close()
