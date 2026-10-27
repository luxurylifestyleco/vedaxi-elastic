"""Local WebMCP document for the browser CDP client.

Serves one imperative registerTool and one declarative form. No external network.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

_NOTE = {"ok": True, "note": "synthetic", "company_id": "NTE-001", "listed": False}

_PAGE = """<!DOCTYPE html>
<html>
<body>
<form
  toolname="lookup_company"
  tooldescription="Look up a synthetic company record. Does not contact anyone."
  method="post"
  action="/lookup"
  toolautosubmit>
  <input name="company" toolparamdescription="Company name" required>
  <button type="submit">Look up</button>
</form>
<script>
const NOTE = """ + json.dumps(_NOTE) + r""";
document.querySelector("form").addEventListener("submit", (e) => {
  e.preventDefault();
  const company = new FormData(e.target).get("company") || "";
  const done = fetch("/lookup", {
    method: "POST",
    headers: {"Content-Type": "application/x-www-form-urlencoded"},
    body: new URLSearchParams({company}),
  }).then((r) => r.json());
  if (e.agentInvoked) e.respondWith(done);
});
(async () => {
  if (!document.modelContext) {
    console.error("document.modelContext missing");
    return;
  }
  await document.modelContext.registerTool({
    name: "note_company",
    description: "Record a synthetic company note. Does not contact anyone.",
    inputSchema: {
      type: "object",
      properties: { company: { type: "string", description: "Company name" } },
      required: ["company"],
    },
    execute: async () => NOTE,
  });
})();
</script>
</body>
</html>
"""


def _lookup(company: str) -> dict:
    return {
        "handled_by": "webmcp_browser_page_lookup",
        "token": "ew-webmcp-lookup-ok",
        "company": company,
    }


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
        company = (form.get("company") or [""])[0]
        body = json.dumps(_lookup(company)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    print(f"WEBMCP_PAGE_PORT={server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
