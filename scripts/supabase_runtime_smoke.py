"""Run a disposable restart/RLS smoke test against the configured gateway DSN.

Requires ELASTIC_CHAT_POSTGRES_DSN. The gateway's development identity is used
only for the disposable tenant names supplied by this script.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE_TENANTS = ("smoke-tenant-a", "smoke-tenant-b")
HTTP_TIMEOUT_SECONDS = 30


def post(base: str, path: str, body: dict) -> dict:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{path} returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{path} was unreachable: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"{path} timed out after {HTTP_TIMEOUT_SECONDS}s") from exc


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start(tenant: str) -> tuple[subprocess.Popen[str], str, dict, str]:
    port = free_port()
    env = os.environ.copy()
    env.update({
        "GATEWAY_HOST": "127.0.0.1",
        "GATEWAY_PORT": str(port),
        "GATEWAY_ENV": "development",
        "ELASTIC_CHAT_DEV_TENANT": tenant,
        "ELASTIC_CHAT_DEV_PRINCIPAL": f"{tenant}-principal",
    })
    log_file = tempfile.NamedTemporaryFile(
        prefix="elastic-gateway-smoke-", suffix=".log", delete=False
    )
    log_path = log_file.name
    process = subprocess.Popen(
        [sys.executable, "apps/gateway/app.py"],
        cwd=ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log_file.close()
    base = f"http://127.0.0.1:{port}"
    for _ in range(50):
        if process.poll() is not None:
            detail = Path(log_path).read_text(encoding="utf-8", errors="replace")
            stop(process)
            remove_log(log_path)
            raise RuntimeError(f"gateway exited during startup for {tenant}: {detail[-4000:]}")
        try:
            with urllib.request.urlopen(base + "/health", timeout=1) as response:
                if response.status == 200:
                    break
        except (OSError, urllib.error.URLError):
            time.sleep(0.1)
    else:
        detail = Path(log_path).read_text(encoding="utf-8", errors="replace")
        stop(process)
        remove_log(log_path)
        raise RuntimeError(f"gateway did not become ready for {tenant}: {detail[-4000:]}")

    # Liveness is not readiness: force one database-backed operation and return
    # its disposable session so the caller can include it in exact-key cleanup.
    try:
        readiness = post(
            base,
            "/chat/sessions",
            {"consentId": f"smoke-readiness-{tenant}", "scopes": ["support:read"]},
        )
    except Exception as exc:
        detail = Path(log_path).read_text(encoding="utf-8", errors="replace")
        stop(process)
        remove_log(log_path)
        raise RuntimeError(f"gateway database readiness failed for {tenant}: {exc}; {detail[-4000:]}") from exc
    if not all(isinstance(readiness.get(key), str) and readiness[key] for key in ("sessionId", "contextId")):
        detail = Path(log_path).read_text(encoding="utf-8", errors="replace")
        stop(process)
        remove_log(log_path)
        raise RuntimeError(f"gateway database readiness returned an invalid session for {tenant}: {readiness}; {detail[-4000:]}")
    return process, base, readiness, log_path


def stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        process.wait(timeout=1)
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def remove_log(path: str) -> None:
    """Remove a stopped gateway log, tolerating delayed Windows handle release."""
    log_path = Path(path)
    for attempt in range(10):
        try:
            log_path.unlink(missing_ok=True)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.1)


def seed_cancellable_task(dsn: str, *, tenant: str, session: dict) -> str:
    """Create a submitted fixture so cancellation is tested before execution."""
    import psycopg2

    task_id = f"smoke-cancel-{uuid.uuid4().hex}"
    principal_id = f"{tenant}-principal"
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
            cursor.execute(
                """INSERT INTO public.a2a_tasks
                (task_id, tenant_id, principal_id, session_id, context_id, state, cancel_state)
                VALUES (%s, %s, %s, %s, %s, 'submitted', 'not_requested')""",
                (task_id, tenant, principal_id, session["sessionId"], session["contextId"]),
            )
        conn.commit()
        return task_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cleanup(dsn: str, sessions: list[tuple[str, str]], tasks: list[tuple[str, str, str]], messages: list[tuple[str, str, str]]) -> None:
    """Delete only the disposable smoke-tenant rows, respecting the FK graph."""
    import psycopg2

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cursor:
            for tenant in SMOKE_TENANTS:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
                cursor.execute(
                    "UPDATE public.conversation_messages SET task_id = NULL WHERE tenant_id = %s",
                    (tenant,),
                )
                cursor.execute(
                    "DELETE FROM public.a2a_tasks WHERE tenant_id = %s",
                    (tenant,),
                )
                cursor.execute(
                    "DELETE FROM public.conversation_messages WHERE tenant_id = %s",
                    (tenant,),
                )
                cursor.execute(
                    "DELETE FROM public.chat_sessions WHERE tenant_id = %s",
                    (tenant,),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    dsn = os.environ.get("ELASTIC_CHAT_POSTGRES_DSN")
    if not dsn:
        print("ELASTIC_CHAT_POSTGRES_DSN is required", file=sys.stderr)
        return 2
    cleanup_dsn = os.environ.get("ELASTIC_CHAT_SMOKE_CLEANUP_DSN", dsn)

    sessions: list[tuple[str, str]] = []
    tasks: list[tuple[str, str, str]] = []
    messages: list[tuple[str, str, str]] = []
    failure: Exception | None = None
    try:
        process = None
        log_path = None
        try:
            process, base, session, log_path = start("smoke-tenant-a")
            sessions.append(("smoke-tenant-a", session["sessionId"]))
            sent = post(base, "/a2a", {
                "jsonrpc": "2.0", "id": "smoke-send", "method": "message/send",
                "params": {"message": {
                    "messageId": "smoke-message-1", "role": "user",
                    "contextId": session["contextId"],
                    "metadata": {"sessionId": session["sessionId"]},
                    "parts": [{"text": "supabase restart smoke"}],
                }},
            })
            task_id = sent["result"]["id"]
            tasks.append(("smoke-tenant-a", task_id, session["sessionId"]))
            messages.append(("smoke-tenant-a", "smoke-message-1", session["sessionId"]))
            cancel_task_id = seed_cancellable_task(
                dsn, tenant="smoke-tenant-a", session=session
            )
            tasks.append(("smoke-tenant-a", cancel_task_id, session["sessionId"]))
        finally:
            if process is not None:
                stop(process)
            if log_path:
                remove_log(log_path)

        process = None
        log_path = None
        try:
            process, base, readiness, log_path = start("smoke-tenant-a")
            sessions.append(("smoke-tenant-a", readiness["sessionId"]))
            replay = post(base, "/a2a", {
                "jsonrpc": "2.0", "id": "smoke-replay", "method": "message/send",
                "params": {"message": {
                    "messageId": "smoke-message-1", "role": "user",
                    "contextId": session["contextId"],
                    "metadata": {"sessionId": session["sessionId"]},
                    "parts": [{"text": "supabase restart smoke"}],
                }},
            })
            if replay.get("result", {}).get("id") != task_id:
                raise AssertionError(f"persisted chat message was not idempotently recovered: {replay}")
            recovered = post(base, "/a2a", {
                "jsonrpc": "2.0", "id": "smoke-get", "method": "tasks/get",
                "params": {"id": task_id, "sessionId": session["sessionId"], "metadata": {"tenantId": "smoke-tenant-a"}},
            })
            if recovered.get("result", {}).get("id") != task_id:
                raise AssertionError(f"task did not survive gateway restart: {recovered}")
            canceled = post(base, "/a2a", {
                "jsonrpc": "2.0", "id": "smoke-cancel", "method": "tasks/cancel",
                "params": {"id": cancel_task_id, "sessionId": session["sessionId"],
                            "metadata": {"tenantId": "smoke-tenant-a"}},
            })
            canceled_result = canceled.get("result", {})
            if (canceled_result.get("status", {}).get("state") != "canceled"
                    or canceled_result.get("metadata", {}).get("cancelState") != "canceled"):
                raise AssertionError(f"submitted task was not canceled: {canceled}")
        finally:
            if process is not None:
                stop(process)
            if log_path:
                remove_log(log_path)

        process = None
        log_path = None
        try:
            process, base, readiness, log_path = start("smoke-tenant-a")
            sessions.append(("smoke-tenant-a", readiness["sessionId"]))
            canceled_recovered = post(base, "/a2a", {
                "jsonrpc": "2.0", "id": "smoke-cancel-restart", "method": "tasks/get",
                "params": {"id": cancel_task_id, "sessionId": session["sessionId"],
                            "metadata": {"tenantId": "smoke-tenant-a"}},
            })
            recovered_result = canceled_recovered.get("result", {})
            if (recovered_result.get("status", {}).get("state") != "canceled"
                    or recovered_result.get("metadata", {}).get("cancelState") != "canceled"):
                raise AssertionError(f"canceled task did not survive gateway restart: {canceled_recovered}")
        finally:
            if process is not None:
                stop(process)
            if log_path:
                remove_log(log_path)

        process = None
        log_path = None
        try:
            process, base, readiness, log_path = start("smoke-tenant-b")
            sessions.append(("smoke-tenant-b", readiness["sessionId"]))
            denied = post(base, "/a2a", {
                "jsonrpc": "2.0", "id": "smoke-cross-tenant", "method": "tasks/get",
                "params": {"id": task_id, "sessionId": session["sessionId"], "metadata": {"tenantId": "smoke-tenant-b"}},
            })
            if "result" in denied or not isinstance(denied.get("error"), dict):
                raise AssertionError(f"cross-tenant task read was not denied: {denied}")
            if denied["error"].get("code") != -32001:
                raise AssertionError(f"cross-tenant task read returned the wrong denial: {denied}")
        finally:
            if process is not None:
                stop(process)
            if log_path:
                remove_log(log_path)
    except Exception as exc:
        failure = exc
    finally:
        try:
            cleanup(cleanup_dsn, sessions, tasks, messages)
        except Exception as exc:
            failure = failure or RuntimeError(f"automatic cleanup failed: {exc}")
            print(f"automatic cleanup failed: {exc}", file=sys.stderr)

    if failure is not None:
        print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS: Supabase restart persistence and cross-tenant denial")
    print("Cleanup: deleted only this run's tasks, messages, and sessions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
