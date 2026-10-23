"""Agent-to-Agent (A2A) Delegation Adapter for Elastic Web.

Implements the A2A protocol pattern for discovering remote agents, submitting tasks,
tracking task lifecycles, and normalizing outcomes into Elastic Web's capability layer.

Reuses the existing Capability and ExecutionResult contracts.
"""

from __future__ import annotations

import json
import re
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Union

import sys
import os
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PACKAGES = os.path.join(_REPO_ROOT, "packages")
for _p in (_PACKAGES, os.path.join(_PACKAGES, "capability-registry")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from capability import Capability
from mcp_adapter import ExecutionResult


# A2A v1 JSON TaskState names (a2a.proto). Streaming is not implemented.
_STATE_FROM_SPEC = {
    "TASK_STATE_SUBMITTED": "submitted",
    "TASK_STATE_WORKING": "working",
    "TASK_STATE_COMPLETED": "completed",
    "TASK_STATE_FAILED": "failed",
    "TASK_STATE_CANCELED": "cancelled",
    "TASK_STATE_REJECTED": "failed",
}


class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class A2ATask:
    """Represents a delegated task in the A2A lifecycle."""
    task_id: str
    target_agent: str
    skill: str
    input_data: Dict[str, Any]
    state: TaskState = TaskState.SUBMITTED
    output: Optional[Any] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "target_agent": self.target_agent,
            "skill": self.skill,
            "input_data": self.input_data,
            "state": self.state.value,
            "output": self.output,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class AgentCard:
    """Agent Card describing an independent agent's identity and capabilities."""
    agent_id: str
    name: str
    description: str
    endpoint: str
    skills: List[Dict[str, Any]]
    metadata: Dict[str, Any] = field(default_factory=dict)


class A2AAgentInterface(Protocol):
    """Protocol for an agent that can receive and execute A2A tasks."""
    agent_id: str
    def handle_task(self, task: A2ATask) -> A2ATask: ...


class A2AAdapter:
    """Adapter bridging Agent-to-Agent delegation into Elastic Web.
    
    Discovers remote agents from agent cards/registries, registers their skills
    as Capabilities in the registry, and manages the delegation lifecycle.
    """

    def __init__(self, provider_prefix: str = "a2a") -> None:
        self.provider_prefix = provider_prefix
        self._agents: Dict[str, Union[AgentCard, A2AAgentInterface]] = {}
        self._capabilities: Dict[str, Capability] = {}
        self._tasks: Dict[str, A2ATask] = {}
        self._execution_log: List[ExecutionResult] = []
        self.http_timeout = 5.0

    def register_agent(
        self,
        card_or_agent: Union[AgentCard, A2AAgentInterface],
        agent_card: Optional[AgentCard] = None,
    ) -> List[Capability]:
        """Register an independent agent and normalize its skills into Capabilities."""
        if isinstance(card_or_agent, AgentCard):
            card = card_or_agent
            agent_id = card.agent_id
            self._agents[agent_id] = card
        else:
            agent_id = getattr(card_or_agent, "agent_id", str(uuid.uuid4()))
            self._agents[agent_id] = card_or_agent
            card = agent_card or getattr(card_or_agent, "card", None)
            if card is None:
                # Default card from attributes
                card = AgentCard(
                    agent_id=agent_id,
                    name=getattr(card_or_agent, "name", agent_id),
                    description=getattr(card_or_agent, "description", f"Agent {agent_id}"),
                    endpoint=f"a2a://{agent_id}",
                    skills=getattr(card_or_agent, "skills", []),
                )

        # Normalize skills into Capabilities
        registered_caps: List[Capability] = []
        for skill in card.skills:
            skill_id = skill.get("id") or skill.get("name")
            cap_id = f"{self.provider_prefix}.{agent_id}.{skill_id}"
            cap = Capability(
                id=cap_id,
                name=skill.get("name", skill_id),
                description=skill.get("description", f"Skill provided by agent {card.name}"),
                domain=skill.get("domain", "agent-delegation"),
                inputs=skill.get("inputs", {}),
                outputs=skill.get("outputs", {}),
                permissions=skill.get("permissions", ["a2a:delegate"]),
                provider=agent_id,
                protocol="a2a",
                endpoint=f"{card.endpoint}/tasks/{skill_id}",
                metadata={
                    "agent_id": agent_id,
                    "skill_id": skill_id,
                    "agent_name": card.name,
                    "protocol_version": "a2a-v1",
                    "binding": "jsonrpc" if str(card.endpoint).startswith("http") else "in-process",
                },
            )
            extra = skill.get("metadata")
            if isinstance(extra, dict):
                cap.metadata.update(extra)
            self._capabilities[cap_id] = cap
            registered_caps.append(cap)

        return registered_caps

    def submit_task(self, target_agent: str, skill: str, input_data: Dict[str, Any]) -> A2ATask:
        """Submit a task to a designated remote agent."""
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        task = A2ATask(
            task_id=task_id,
            target_agent=target_agent,
            skill=skill,
            input_data=input_data,
            state=TaskState.SUBMITTED,
        )
        self._tasks[task_id] = task

        # Dispatch task to agent if available
        agent = self._agents.get(target_agent)
        if agent is None:
            task.state = TaskState.FAILED
            task.error = f"Target agent '{target_agent}' not registered"
            task.updated_at = time.time()
            return task

        if hasattr(agent, "handle_task") and callable(agent.handle_task):
            task.state = TaskState.WORKING
            task.updated_at = time.time()
            try:
                updated_task = agent.handle_task(task)
                self._tasks[task_id] = updated_task
                return updated_task
            except Exception as exc:
                task.state = TaskState.FAILED
                task.error = f"Agent execution error: {exc}"
                task.updated_at = time.time()
                return task

        if isinstance(agent, AgentCard) and str(agent.endpoint).startswith("http"):
            return self._submit_http(agent, task)

        task.state = TaskState.FAILED
        task.error = f"Agent '{target_agent}' has no in-process handler or HTTP endpoint"
        task.updated_at = time.time()
        return task

    def discover_http(self, base_url: str) -> List[Capability]:
        """Fetch ``/.well-known/agent-card.json`` and register its skills.

        Uses the A2A v1 JSON-RPC binding (``SendMessage`` / ``GetTask``).
        ``SendStreamingMessage`` is not called.
        """
        root = base_url.rstrip("/")
        card_url = root + "/.well-known/agent-card.json"
        card_doc = self._http_json(card_url, method="GET")
        interfaces = card_doc.get("supportedInterfaces") or []
        rpc_url = None
        for item in interfaces:
            if item.get("protocolBinding") == "JSONRPC" and item.get("url"):
                rpc_url = item["url"]
                break
        if not rpc_url:
            raise ValueError(f"agent card at {card_url} has no JSONRPC interface")

        agent_id = re.sub(r"[^a-z0-9]+", "-", str(card_doc.get("name", "agent")).lower()).strip("-")
        skills = []
        for skill in card_doc.get("skills") or []:
            tags = list(skill.get("tags") or [])
            skills.append({
                "id": skill.get("id"),
                "name": skill.get("name") or skill.get("id"),
                "description": skill.get("description") or "",
                "domain": _tag_value(tags, "domain:") or "agent-delegation",
                "permissions": _perm_tags(tags) or ["a2a:delegate"],
                "metadata": _metadata_from_tags(tags),
            })
        card = AgentCard(
            agent_id=agent_id,
            name=card_doc.get("name") or agent_id,
            description=card_doc.get("description") or "",
            endpoint=rpc_url,
            skills=skills,
            metadata={"specification": "a2a-v1", "streaming": False},
        )
        return self.register_agent(card)

    def get_task(self, task_id: str) -> Optional[A2ATask]:
        """Poll task status. HTTP agents are refreshed with ``GetTask``."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        agent = self._agents.get(task.target_agent)
        if (
            isinstance(agent, AgentCard)
            and str(agent.endpoint).startswith("http")
            and task.state in (TaskState.SUBMITTED, TaskState.WORKING)
        ):
            self._refresh_http(agent, task)
        return task

    def _submit_http(self, card: AgentCard, task: A2ATask) -> A2ATask:
        """SendMessage with returnImmediately so the caller can poll GetTask."""
        message_id = f"msg-{uuid.uuid4().hex}"
        params = {
            "message": {
                "messageId": message_id,
                "role": "ROLE_USER",
                "parts": [{"data": task.input_data, "mediaType": "application/json"}],
                "metadata": {"skillId": task.skill},
            },
            "configuration": {"returnImmediately": True},
        }
        try:
            result = self._http_rpc(card.endpoint, "SendMessage", params)
        except Exception as exc:
            task.state = TaskState.FAILED
            task.error = f"A2A SendMessage failed: {exc}"
            task.updated_at = time.time()
            return task
        remote = result.get("task") if isinstance(result, dict) else None
        if not isinstance(remote, dict) or not remote.get("id"):
            task.state = TaskState.FAILED
            task.error = "A2A SendMessage response did not contain a task"
            task.updated_at = time.time()
            return task
        self._tasks.pop(task.task_id, None)
        task.task_id = str(remote["id"])
        self._tasks[task.task_id] = task
        return self._apply_remote_task(task, remote)

    def _refresh_http(self, card: AgentCard, task: A2ATask) -> A2ATask:
        try:
            result = self._http_rpc(card.endpoint, "GetTask", {"id": task.task_id})
        except Exception as exc:
            task.state = TaskState.FAILED
            task.error = f"A2A GetTask failed: {exc}"
            task.updated_at = time.time()
            return task
        if isinstance(result, dict):
            return self._apply_remote_task(task, result)
        task.state = TaskState.FAILED
        task.error = "A2A GetTask returned no task"
        task.updated_at = time.time()
        return task

    def _apply_remote_task(self, task: A2ATask, remote: Dict[str, Any]) -> A2ATask:
        state_name = str((remote.get("status") or {}).get("state") or "")
        mapped = _STATE_FROM_SPEC.get(state_name)
        if state_name in ("TASK_STATE_INPUT_REQUIRED", "TASK_STATE_AUTH_REQUIRED"):
            task.state = TaskState.FAILED
            task.error = f"task interrupted: {state_name}"
        elif mapped is None:
            task.state = TaskState.FAILED
            task.error = f"unrecognized A2A task state: {state_name or 'missing'}"
        else:
            task.state = TaskState(mapped)
        task.output = _artifact_output(remote)
        if task.state == TaskState.FAILED and not task.error:
            task.error = _status_text(remote) or f"task ended {state_name}"
        task.updated_at = time.time()
        return task

    def _http_rpc(self, url: str, method: str, params: Dict[str, Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        return self._http_json(url, payload=payload)

    def _http_json(self, url: str, payload: Optional[Dict[str, Any]] = None, method: Optional[str] = None) -> Any:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        http_method = method or ("POST" if data is not None else "GET")
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=http_method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.http_timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"HTTP {exc.code}: {raw}") from exc
        if isinstance(body, dict) and "error" in body:
            err = body["error"]
            raise RuntimeError(err.get("message") if isinstance(err, dict) else str(err))
        if isinstance(body, dict) and "result" in body:
            return body["result"]
        return body

    def delegate_and_wait(
        self,
        capability_id: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout: float = 5.0,
    ) -> ExecutionResult:
        """High-level invocation compliant with Elastic Web's executor contract."""
        cap = self._capabilities.get(capability_id)
        if not cap:
            raise KeyError(f"A2A capability not found: {capability_id}")

        agent_id = cap.metadata.get("agent_id")
        skill_id = cap.metadata.get("skill_id")
        start = time.perf_counter()

        task = self.submit_task(agent_id, skill_id, arguments or {})

        # If synchronous or fast agent, task may already be completed
        deadline = time.time() + timeout
        while task.state in (TaskState.SUBMITTED, TaskState.WORKING) and time.time() < deadline:
            time.sleep(0.05)
            polled = self.get_task(task.task_id)
            if polled:
                task = polled

        duration_ms = (time.perf_counter() - start) * 1000.0

        if task.state == TaskState.COMPLETED:
            success = True
            result = task.output
            error = None
        else:
            success = False
            result = task.output
            error = task.error or f"Task ended with state {task.state.value}"

        exec_res = ExecutionResult(
            tool_name=capability_id,
            capability_id=capability_id,
            success=success,
            result=result,
            error=error,
            duration_ms=duration_ms,
        )
        self._execution_log.append(exec_res)
        return exec_res

    def list_capabilities(self) -> List[Capability]:
        return list(self._capabilities.values())


def _tag_value(tags: List[str], prefix: str) -> Optional[str]:
    for tag in tags:
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return None


def _perm_tags(tags: List[str]) -> List[str]:
    return [tag.split(":", 1)[1] for tag in tags if tag.startswith("perm:")]


def _metadata_from_tags(tags: List[str]) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    goals: List[str] = []
    binds: Dict[str, int] = {}
    for tag in tags:
        if tag.startswith("intent:"):
            goals.append(tag.split(":", 1)[1])
        elif tag.startswith("stage:"):
            meta["stage"] = int(tag.split(":", 1)[1])
        elif tag.startswith("produces:"):
            meta["produces"] = tag.split(":", 1)[1]
        elif tag.startswith("binds:"):
            arg, stage = tag.split(":", 1)[1].split("=")
            binds[arg] = int(stage)
    if goals:
        meta["intent_goals"] = goals
    if binds:
        meta["binds"] = binds
    return meta


def _artifact_output(remote: Dict[str, Any]) -> Any:
    for artifact in remote.get("artifacts") or []:
        for part in artifact.get("parts") or []:
            if isinstance(part, dict) and "data" in part and part.get("data") is not None:
                return part["data"]
            text = part.get("text") if isinstance(part, dict) else None
            if text:
                try:
                    return json.loads(text)
                except Exception:
                    return text
    return None


def _status_text(remote: Dict[str, Any]) -> Optional[str]:
    message = (remote.get("status") or {}).get("message") or {}
    parts = message.get("parts") or []
    texts = [part.get("text") for part in parts if isinstance(part, dict) and part.get("text")]
    return "\n".join(texts) if texts else None
