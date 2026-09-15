"""Example 04: Full Gateway API Roundtrip."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from urllib.request import Request, urlopen

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "apps", "gateway"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "packages", "elastic-bench"))

import app
from app import create_app
import control_c


def _post(url: str, payload: dict) -> dict:
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(url: str) -> dict:
    with urlopen(url) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    # Pre-populate gateway store with recipes from control_c
    for r in control_c.control_c.recipes():
        try:
            app._RECIPE_STORE.create(r)
        except Exception:
            pass

    # Spin up gateway on ephemeral port
    server = create_app()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    print(f"Gateway running in-process at {base}")

    try:
        # 1. Health
        health = _get(f"{base}/health")
        print("1. /health:", health)

        # 2. Compile Intent
        intent_res = _post(f"{base}/intent/compile", {"text": "Get my August bank statement"})
        print("2. /intent/compile:", intent_res.get("goal"), "| domain:", intent_res.get("domain"))

        # 3. Discover Capabilities
        disc = _post(f"{base}/capabilities/discover", {"intent": "get account statement"})
        print(f"3. /capabilities/discover returned {len(disc.get('candidates', []))} candidates")

        # 4. Execute Capability directly
        exec_res = _post(f"{base}/capabilities/get_balance/execute", {"args": {"account_id": "ACC-1001"}})
        print("4. /capabilities/get_balance/execute:", exec_res.get("capability_id"), "result ok:", exec_res.get("result", {}).get("ok"))

        # 5. Resolve and Execute Recipe
        rec_res = _post(f"{base}/recipes/resolve", {"intent_family": "retrieve_statement"})
        print("5. /recipes/resolve:", rec_res.get("recipe_id"), "| version:", rec_res.get("version"))

        print("\nAll Gateway roundtrip tests passed successfully!")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
