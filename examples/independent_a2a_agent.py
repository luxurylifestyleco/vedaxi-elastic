"""Independent A2A v1 agent. Does not import Elastic Web.

Speaks:
- GET /.well-known/agent-card.json
- POST JSON-RPC SendMessage and GetTask on the card's JSONRPC URL

SendStreamingMessage is rejected. No live contact, no real accounts.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_PROFILES = {
    "northwind labs": {
        "industry": "logistics software",
        "public": True,
        "note": "Publishes an operations blog",
    },
    "brightparcel": {
        "industry": "regional shipping",
        "public": True,
        "note": "Existing-customer overlap on public site",
    },
    "closed books llc": {
        "industry": None,
        "public": False,
        "note": "No public profile",
    },
}

_TASKS: dict = {}
_LOCK = threading.Lock()


def _companies(data: object) -> list:
    if not isinstance(data, dict):
        return []
    payload = data
    prospects = data.get("prospects")
    if isinstance(prospects, dict):
        payload = prospects
    if isinstance(payload.get("prospects"), list):
        return [item.get("company") for item in payload["prospects"] if isinstance(item, dict)]
    if isinstance(data.get("companies"), list):
        return list(data["companies"])
    return []


def _research(data: dict) -> dict:
    rows = []
    for company in _companies(data):
        profile = _PROFILES.get(str(company).strip().lower())
        if profile is None:
            rows.append({
                "company": company,
                "industry": None,
                "public": False,
                "note": "not in the synthetic directory",
            })
        else:
            rows.append({"company": company, **profile})
    return {"research": rows}


def _task_shell(state: str, text: str | None = None, data: dict | None = None) -> dict:
    task_id = f"task-{uuid.uuid4().hex}"
    message = None
    if text:
        message = {
            "messageId": f"msg-{uuid.uuid4().hex}",
            "role": "ROLE_AGENT",
            "parts": [{"text": text}],
        }
    task = {
        "id": task_id,
        "contextId": f"ctx-{uuid.uuid4().hex}",
        "status": {"state": state, "message": message},
        "artifacts": [],
    }
    if data is not None:
        task["artifacts"] = [{
            "artifactId": f"art-{uuid.uuid4().hex}",
            "name": "Company research",
            "parts": [{"data": data, "mediaType": "application/json"}],
        }]
    return task


def _finish(task_id: str, data: dict, skill: str) -> None:
    with _LOCK:
        task = _TASKS.get(task_id)
        if task is None:
            return
        if skill != "research_company":
            task["status"] = {
                "state": "TASK_STATE_FAILED",
                "message": {
                    "messageId": f"msg-{uuid.uuid4().hex}",
                    "role": "ROLE_AGENT",
                    "parts": [{"text": f"Unknown skill: {skill}"}],
                },
            }
            return
        if not _companies(data):
            task["status"] = {
                "state": "TASK_STATE_FAILED",
                "message": {
                    "messageId": f"msg-{uuid.uuid4().hex}",
                    "role": "ROLE_AGENT",
                    "parts": [{"text": "no companies to research"}],
                },
            }
            return
        task["status"] = {"state": "TASK_STATE_COMPLETED"}
        task["artifacts"] = [{
            "artifactId": f"art-{uuid.uuid4().hex}",
            "name": "Company research",
            "parts": [{"data": _research(data), "mediaType": "application/json"}],
        }]


def _progress(task_id: str, data: dict, skill: str, delay: float) -> None:
    time.sleep(delay)
    with _LOCK:
        task = _TASKS.get(task_id)
        if task is None or task["status"]["state"] != "TASK_STATE_SUBMITTED":
            return
        task["status"] = {"state": "TASK_STATE_WORKING"}
    time.sleep(delay)
    _finish(task_id, data, skill)


class _Handler(BaseHTTPRequestHandler):
    server_version = "IndependentA2A/1.0"

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] != "/.well-known/agent-card.json":
            self._send(404, {"error": "not found"})
            return
        host = self.headers.get("Host") or f"127.0.0.1:{self.server.server_address[1]}"
        card = {
            "name": "Synthetic Company Research",
            "description": "Researches synthetic companies for a sales outreach plan. Does not contact them.",
            "supportedInterfaces": [{
                "url": f"http://{host}/rpc",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }],
            "version": "1.0.0",
            "capabilities": {"streaming": False, "pushNotifications": False},
            "defaultInputModes": ["application/json", "text/plain"],
            "defaultOutputModes": ["application/json"],
            "skills": [{
                "id": "research_company",
                "name": "Research Company",
                "description": "Prepare outreach research for synthetic sales companies. Does not contact the company.",
                "tags": [
                    "sales",
                    "domain:sales",
                    "intent:prepare_outreach",
                    "stage:2",
                    "produces:research",
                    "binds:prospects=1",
                    "perm:a2a:delegate",
                ],
            }],
        }
        self._send(200, card)

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/rpc":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            return
        method = req.get("method")
        req_id = req.get("id")
        params = req.get("params") or {}
        if method == "SendStreamingMessage":
            self._send(200, {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "streaming is not implemented"}})
            return
        if method == "SendMessage":
            self._send(200, {"jsonrpc": "2.0", "id": req_id, "result": {"task": self._send_message(params)}})
            return
        if method == "GetTask":
            with _LOCK:
                task = _TASKS.get(params.get("id"))
            if task is None:
                self._send(200, {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32001, "message": "task not found"}})
                return
            self._send(200, {"jsonrpc": "2.0", "id": req_id, "result": task})
            return
        self._send(200, {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"method not found: {method}"}})

    def _send_message(self, params: dict) -> dict:
        message = params.get("message") or {}
        skill = (message.get("metadata") or {}).get("skillId") or ""
        data = {}
        for part in message.get("parts") or []:
            if isinstance(part, dict) and isinstance(part.get("data"), dict):
                data = part["data"]
                break
        delay_ms = data.pop("delay_ms", None) if isinstance(data, dict) else None
        delay = (float(delay_ms) / 1000.0) if delay_ms is not None else 0.05
        immediate = bool((params.get("configuration") or {}).get("returnImmediately"))
        task = _task_shell("TASK_STATE_SUBMITTED")
        with _LOCK:
            _TASKS[task["id"]] = task
        if immediate:
            threading.Thread(
                target=_progress, args=(task["id"], data, skill, delay), daemon=True
            ).start()
            return task
        _finish(task["id"], data, skill)
        with _LOCK:
            return _TASKS[task["id"]]

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def main() -> None:
    port = 0
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    print(f"A2A_PORT={server.server_address[1]}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
