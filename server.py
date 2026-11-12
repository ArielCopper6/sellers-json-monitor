#!/usr/bin/env python3
"""Local dashboard for the sellers.json monitor.

    python3 server.py        # then open http://localhost:8765

Serves the dashboard and lets it add/remove partners and run a check now.
Only reachable from this Mac (binds to 127.0.0.1).
"""
import datetime as dt
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sellers_monitor as m  # noqa: E402

PORT = 8765
ALLOWED_ORIGINS = {f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}"}
lock = threading.Lock()  # one check at a time


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _same_origin(self):
        # block other websites in your browser from changing anything here
        origin = self.headers.get("Origin")
        return origin is None or origin in ALLOWED_ORIGINS

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/dashboard.html"):
            # live page: no data baked in, it loads /api/data instead
            page = m.DASHBOARD_TEMPLATE.read_text().replace("/*__DATA__*/null", "null")
            self._send(200, page.encode(), "text/html")
        elif path == "/api/data":
            self._send(200, m.dashboard_data())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._same_origin():
            return self._send(403, {"error": "forbidden"})
        path = urlparse(self.path).path
        today = dt.date.today().isoformat()
        if path == "/api/partners":
            domain = m.normalize_domain(str(self._json_body().get("domain", "")))
            if not domain:
                return self._send(400, {"error": "That doesn't look like a website name. Try something like openx.com"})
            if domain in m.load_domains():
                return self._send(400, {"error": f"{domain} is already on the list."})
            try:
                m.fetch_sellers(domain)
            except Exception as e:
                reason = "the file doesn't exist there" if "404" in str(e) else f"{type(e).__name__}: {e}"
                return self._send(400, {"error": f"Couldn't read https://{domain}/sellers.json ({reason}). Check the spelling."})
            with lock:
                m.add_domain(domain)
                res = m.check_domains([domain], today)[0]
            return self._send(200, {"ok": True, "domain": domain, "sellers": res.get("count")})
        if path == "/api/check":
            if not lock.acquire(blocking=False):
                return self._send(409, {"error": "A check is already running."})
            try:
                results = m.check_domains(m.load_domains(), today)
            finally:
                lock.release()
            return self._send(200, {"ok": True, "errors": [r["domain"] for r in results if r.get("error")]})
        self._send(404, {"error": "not found"})

    def do_DELETE(self):
        if not self._same_origin():
            return self._send(403, {"error": "forbidden"})
        u = urlparse(self.path)
        if u.path == "/api/partners":
            domain = m.normalize_domain(parse_qs(u.query).get("domain", [""])[0])
            with lock:
                m.remove_domain(domain)
                m.build_dashboard()
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))


if __name__ == "__main__":
    print(f"Dashboard running at http://localhost:{PORT}", file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
