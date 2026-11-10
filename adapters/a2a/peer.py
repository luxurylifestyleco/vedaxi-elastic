"""Inbound A2A peer for the Elastic Web gateway.

One switch skill. Demo-bank skills are not published. Streaming and push
are not implemented. Session id is message.contextId; metadata.sessionId
is only an alias when contextId is absent.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Dict, List, Optional


class SessionDenied(Exception):
    """Unknown or foreign contextId. The caller must not execute."""

    def __init__(self, context_id: str) -> None:
        self.context_id = context_id
        super().__init__(context_id)


class A2APeer:
    """In-memory A2A session and task store. Dies with the process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: Dict[str, str] = {}
        self._turns: Dict[str, List[Dict[str, Any]]] = {}
        self._tasks: Dict[str, Dict[str, Any]] = {}

    def agent_card(self, rpc_url: str) -> Dict[str, Any]:
        return {
            "name": "Elastic Web",
            "description": (
                "Resolves an intent to a registered participant. "
                "Does not own the participant."
            ),
            "supportedInterfaces": [
                {
                    "url": rpc_url,
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "1.0",
                }
            ],
            "version": "1.0.0",
            "capabilities": {"streaming": False, "pushNotifications": False},
            "defaultInputModes": ["application/json", "text/plain"],
            "defaultOutputModes": ["application/json"],
            "skills": [
                {
                    "id": "route_intent",
                    "name": "Route intent",
                    "description": (
                        "Resolve an intent and route it through a registered "
                        "participant. Demo-bank skills are not published."
                    ),
                    "tags": ["domain:interop", "perm:a2a:delegate"],
                }
            ],
        }

    def accept(self, subject: str, params: Dict[str, Any]) -> str:
        """Bind a session for this subject.

        A missing id is minted. An unknown or foreign id raises SessionDenied
        and must not be followed by execution.
        """
        message = params.get("message") if isinstance(params.get("message"), dict) else {}
        meta = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        supplied = message.get("contextId") or meta.get("sessionId")
        with self._lock:
            if supplied:
                context_id = str(supplied)
                owner = self._sessions.get(context_id)
                if owner is None or owner != subject:
                    raise SessionDenied(context_id)
            else:
                context_id = f"ctx-{uuid.uuid4().hex}"
                self._sessions[context_id] = subject
                self._turns[context_id] = []
            self._turns.setdefault(context_id, []).append(message)
            return context_id

    def record_turn(self, context_id: str, turn: Dict[str, Any]) -> None:
        with self._lock:
            self._turns.setdefault(context_id, []).append(turn)

    def get_session(self, subject: str, context_id: str) -> Dict[str, Any]:
        with self._lock:
            owner = self._sessions.get(context_id)
            if owner is None or owner != subject:
                raise SessionDenied(context_id)
            return {
                "contextId": context_id,
                "turns": list(self._turns.get(context_id, [])),
            }

    def put_task(self, task: Dict[str, Any]) -> None:
        with self._lock:
            self._tasks[str(task["id"])] = task

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task is not None else None
