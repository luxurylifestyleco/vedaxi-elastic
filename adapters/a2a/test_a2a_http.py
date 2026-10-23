"""A2A v1 against a separate process that does not import the adapter."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
for _p in (
    os.path.join(_REPO_ROOT, "packages"),
    os.path.join(_REPO_ROOT, "packages", "capability-registry"),
    os.path.join(_REPO_ROOT, "adapters"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from adapters.a2a.a2a_adapter import A2AAdapter, TaskState


def _spawn(script: str, prefix: str, args: list[str] | None = None) -> tuple[subprocess.Popen, int]:
    proc = subprocess.Popen(
        [sys.executable, script, *(args or [])],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    line = proc.stdout.readline()
    if not line.startswith(prefix):
        err = proc.stderr.read() if proc.stderr else ""
        proc.kill()
        raise AssertionError(f"expected {prefix}, got {line!r} stderr={err!r}")
    return proc, int(line.split("=", 1)[1].strip())


@pytest.fixture
def a2a_base():
    script = os.path.join(_REPO_ROOT, "examples", "independent_a2a_agent.py")
    proc, port = _spawn(script, "A2A_PORT=", ["--port", "0"])
    try:
        yield f"http://127.0.0.1:{port}", proc
    finally:
        proc.kill()
        proc.wait(timeout=5)


def test_discover_delegate_poll_and_fail(a2a_base):
    base, proc = a2a_base
    adapter = A2AAdapter()
    adapter.http_timeout = 5
    caps = adapter.discover_http(base)
    assert len(caps) == 1
    cap = caps[0]
    assert cap.protocol == "a2a"
    assert cap.metadata["binding"] == "jsonrpc"
    assert cap.metadata["intent_goals"] == ["prepare_outreach"]
    assert cap.metadata["stage"] == 2
    assert "streaming" not in cap.endpoint

    agent_id = cap.metadata["agent_id"]
    task = adapter.submit_task(
        agent_id,
        cap.metadata["skill_id"],
        {"companies": ["Northwind Labs"], "delay_ms": 400},
    )
    assert task.state == TaskState.SUBMITTED
    seen = {task.state.value}
    current = task
    deadline = time.time() + 3
    while current.state in (TaskState.SUBMITTED, TaskState.WORKING) and time.time() < deadline:
        time.sleep(0.05)
        current = adapter.get_task(current.task_id)
        assert current is not None
        seen.add(current.state.value)
    assert "working" in seen
    assert current.state == TaskState.COMPLETED
    assert current.output["research"][0]["industry"] == "logistics software"
    assert current.output["research"][0]["public"] is True

    failed = adapter.submit_task(agent_id, "not_a_skill", {"companies": ["Northwind Labs"]})
    deadline = time.time() + 3
    while failed.state in (TaskState.SUBMITTED, TaskState.WORKING) and time.time() < deadline:
        time.sleep(0.05)
        failed = adapter.get_task(failed.task_id)
    assert failed.state == TaskState.FAILED
    assert "Unknown skill" in (failed.error or "")

    req = urllib.request.Request(
        base + "/rpc",
        data=json.dumps({
            "jsonrpc": "2.0",
            "id": "stream",
            "method": "SendStreamingMessage",
            "params": {},
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    assert body["error"]["message"] == "streaming is not implemented"
    assert proc.poll() is None
