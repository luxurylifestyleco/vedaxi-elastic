"""Synthetic company directory page with one declarative WebMCP form.

The form uses the WebMCP declarative attributes (toolname, tooldescription,
toolparamdescription). There is no document.modelContext registration.
The server does not contact anyone.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

_PROFILES = {
    "northwind labs": {"industry": "logistics software", "public": True},
    "brightparcel": {"industry": "regional shipping", "public": True},
    "closed books llc": {"industry": None, "public": False},
}

_PAGE = """<!DOCTYPE html>
<html>
<body>
<form
  toolname="lookup_company"
  tooldescription="Look up a public synthetic company profile to prepare outreach sales research. Does not contact the company."
  method="post"
  action="/lookup"
  data-intent-goals="prepare_outreach"
  data-stage="3"
  data-binds="companies=1"
  data-domain="sales"
  data-permissions="web:access">
  <input name="companies" toolparamdescription="Prospect payload or company list" required>
  <button type="submit">Look up</button>
</form>
</body>
</html>
"""


def _lookup(raw: str) -> dict:
    text = raw or ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = text
    names: list = []
    if isinstance(parsed, dict) and isinstance(parsed.get("prospects"), list):
        names = [item.get("company") for item in parsed["prospects"] if isinstance(item, dict)]
    elif isinstance(parsed, list):
        names = parsed
    elif isinstance(parsed, str) and parsed:
        names = [part.strip() for part in parsed.split(",")]
    profiles = []
    for name in names:
        profile = _PROFILES.get(str(name).strip().lower())
        profiles.append({
            "company": name,
            "industry": None if profile is None else profile["industry"],
            "public": False if profile is None else profile["public"],
            "source": "company-directory",
        })
    return {"profiles": profiles}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] not in ("/", "/index.html"):
            self.send_response(404)
            self.end_headers()
            return
        body = _PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/lookup":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        raw = (form.get("companies") or [""])[0]
        body = json.dumps(_lookup(raw)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    print(f"DIRECTORY_PORT={server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
