"""Thin A2A transport boundary over Elastic compilation and runtime."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlsplit

# The repository runs package tests as source modules.  Add the sibling
# assurance source directory exactly as the gateway bootstrap does, without
# creating a second assurance implementation.
_ASSURANCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assurance-protocol",
)
if _ASSURANCE_DIR not in sys.path:
    sys.path.insert(0, _ASSURANCE_DIR)

from recipe import Recipe, RecipeStep
from evaluator import evaluate_outcome
from outcome import EvidenceRecord, OutcomeEnvelope, OutcomeStatus, transition_outcome
from verification import VerificationContext, VerificationEngine

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class A2AInboundAdapter:
    """Normalize one A2A message through Intent IR, retrieval, and runtime."""

    def __init__(
        self,
        *,
        compiler: Any,
        retriever: Any,
        capability_by_id: Callable[[str], Any],
        runner: Any,
        executor: Callable[[str, Dict[str, Any]], Any],
        bus: Any,
        source_endpoint: str,
        verification_engine: Optional[VerificationEngine] = None,
    ) -> None:
        self.compiler = compiler
        self.retriever = retriever
        self.capability_by_id = capability_by_id
        self.runner = runner
        self.executor = executor
        self.bus = bus
        self.source_endpoint = source_endpoint
        self.verification_engine = verification_engine or VerificationEngine()

    def handle(self, request: Dict[str, Any]) -> Dict[str, Any]:
        message = request.get("message")
        if not isinstance(message, dict) or message.get("role") not in {
            "ROLE_USER",
            "user",
        }:
            raise ValueError("A2A request requires a user message")
        parts = message.get("parts")
        if not isinstance(parts, list) or not parts:
            raise ValueError("A2A message requires at least one part")
        text = "\n".join(
            part["text"].strip()
            for part in parts
            if isinstance(part, dict)
            and isinstance(part.get("text"), str)
            and part["text"].strip()
        )
        if not text:
            raise ValueError("A2A message requires a text part")

        task_id = uuid.uuid4().hex
        context_id = message.get("contextId") or uuid.uuid4().hex
        trace_id = uuid.uuid4().hex
        protocol = {
            "source_protocol": "a2a",
            "source_endpoint": self.source_endpoint,
            "provider": "external-a2a",
        }
        try:
            intent = self.compiler.compile(text)
            self.bus.emit(
                "intent.received",
                trace_id=trace_id,
                intent_id=intent.intent_id,
                payload={"protocol": protocol},
            )
            self.bus.emit(
                "intent.compiled", trace_id=trace_id, intent_id=intent.intent_id
            )
            candidates = self.retriever.retrieve(intent, k=1)
            if not candidates:
                raise LookupError("no Elastic capability matched the A2A request")
            capability_id = candidates[0].capability_id
            capability = self.capability_by_id(capability_id)
            if capability is None:
                raise LookupError(f"selected capability is not registered: {capability_id}")
            protocol["selected_capability"] = capability_id
            protocol["provider"] = capability.provider
            self.bus.emit(
                "capability.selected",
                trace_id=trace_id,
                intent_id=intent.intent_id,
                payload={"capability_id": capability_id, "protocol": protocol},
            )
            args: Dict[str, Any] = dict(intent.constraints)
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get("data"), dict):
                    args.update(part["data"])
            metadata = message.get("metadata")
            if isinstance(metadata, dict) and isinstance(metadata.get("arguments"), dict):
                args.update(metadata["arguments"])
            recipe = Recipe(
                recipe_id=f"a2a-{task_id}",
                intent_family=intent.goal,
                version="1.0.0",
                steps=[
                    RecipeStep(
                        step_id="execute",
                        action=intent.action,
                        capability_id=capability_id,
                        args=args,
                    )
                ],
                success_conditions=intent.success_conditions,
            )
            execution = self.runner.run(
                recipe,
                executor=self.executor,
                trace_id=trace_id,
                intent_id=intent.intent_id,
                raise_on_error=False,
            )
            if not execution.success:
                return self._response(
                    task_id,
                    context_id,
                    "TASK_STATE_FAILED",
                    trace_id,
                    {"error": execution.error},
                )
            assurance = self._assess_execution(
                outcome_id=uuid.uuid4().hex,
                execution_id=trace_id,
                capability_id=capability.id,
                protocol=protocol,
                intent=intent,
                recipe=recipe,
            )
            self.bus.emit(
                "evaluation.completed",
                trace_id=trace_id,
                intent_id=intent.intent_id,
                payload={
                    "protocol": {**protocol, "execution_outcome": "executed_not_verified"},
                    **assurance,
                },
            )
            return self._response(
                task_id,
                context_id,
                "TASK_STATE_COMPLETED"
                if assurance["outcome_status"] == OutcomeStatus.COMPLETED.value
                else "TASK_STATE_WORKING",
                trace_id,
                execution.results,
                outcome_id=assurance["outcome_id"],
                evidence_id=assurance["evidence_id"],
                outcome_status=assurance["outcome_status"],
                verification_status=assurance["verification_status"],
                completion_authoritative=assurance["completion_authoritative"],
            )
        except Exception as exc:
            self.bus.emit(
                "execution.failed",
                trace_id=trace_id,
                payload={
                    "error": f"{type(exc).__name__}: {exc}",
                    "protocol": {**protocol, "execution_outcome": "failed"},
                    "evidence_id": trace_id,
                },
            )
            return self._response(
                task_id,
                context_id,
                "TASK_STATE_FAILED",
                trace_id,
                {"error": str(exc)},
            )

    def _assess_execution(
        self,
        *,
        outcome_id: str,
        execution_id: str,
        capability_id: str,
        protocol: Dict[str, Any],
        intent: Any,
        recipe: Recipe,
    ) -> Dict[str, Any]:
        """Assess local execution without treating it as provider proof."""

        now = datetime.now(timezone.utc)
        outcome = OutcomeEnvelope(
            outcome_id=outcome_id,
            principal_id="a2a-request",
            originating_agent_id="elastic-a2a-inbound",
            intent={"goal": intent.goal, "action": intent.action, "protocol": "a2a"},
            desired_state={"execution": "successful"},
            required_capabilities=[capability_id],
            execution_plan_reference=recipe.recipe_id,
            verification_policy={"required": True, "policy_reference": "a2a-local-execution-v1"},
            completion_criteria=["capability execution completed"],
            evidence_collection_policy={"accepted_types": ["provider_receipt", "attestation"]},
            recovery_policy={"allow_recovery": False},
            created_at=now,
            updated_at=now,
        )
        for next_status in (
            OutcomeStatus.VALIDATING,
            OutcomeStatus.AUTHORIZED,
            OutcomeStatus.PLANNING,
            OutcomeStatus.EXECUTING,
            OutcomeStatus.VERIFYING,
        ):
            outcome = transition_outcome(outcome, next_status)

        evidence_id = f"execution-event-{execution_id}"
        evidence = EvidenceRecord(
            evidence_id=evidence_id,
            tenant_id="unresolved",
            outcome_id=outcome_id,
            execution_id=execution_id,
            evidence_type="execution_event",
            claim=f"Local A2A recipe runner returned successfully for capability {capability_id}",
            subject=capability_id,
            issuer="elastic-a2a-inbound",
            source="local-recipe-runner",
            producer="elastic-a2a-inbound",
            observed_at=now,
            received_at=now,
            artifact_reference=f"trace:{execution_id}",
            protocol_origin=str(protocol["source_protocol"]),
            verification_status="PENDING",
            privacy_classification="internal",
            retention_policy="runtime-default",
        )
        verification = self.verification_engine.verify(
            [evidence],
            VerificationContext(
                outcome_id=outcome_id,
                execution_id=execution_id,
                policy_reference="a2a-local-execution-v1",
                verifier_id="elastic-a2a-inbound",
                required_evidence_ids=[evidence_id],
            ),
            verification_id=f"verification-{execution_id}",
        )
        outcome_status = evaluate_outcome(outcome, [verification])
        if outcome_status is OutcomeStatus.COMPLETED:
            outcome = transition_outcome(outcome, outcome_status, sufficient_evidence=True)
        else:
            outcome = transition_outcome(outcome, outcome_status)
        return {
            "outcome_id": outcome.outcome_id,
            "evidence_id": evidence.evidence_id,
            "outcome_status": outcome.current_status.value,
            "verification_status": verification.status.value,
            "completion_authoritative": outcome.current_status is OutcomeStatus.COMPLETED,
        }

    @staticmethod
    def _response(
        task_id: str,
        context_id: str,
        state: str,
        trace_id: str,
        result: Any,
        *,
        outcome_id: Optional[str] = None,
        evidence_id: Optional[str] = None,
        outcome_status: Optional[str] = None,
        verification_status: Optional[str] = None,
        completion_authoritative: Optional[bool] = None,
    ) -> Dict[str, Any]:
        metadata = {"traceId": trace_id, "evidenceId": evidence_id or trace_id}
        if outcome_id is not None:
            metadata.update(
                {
                    "outcomeId": outcome_id,
                    "outcomeStatus": outcome_status,
                    "verificationStatus": verification_status,
                    "completionAuthoritative": completion_authoritative,
                }
            )
        return {
            "task": {
                "id": task_id,
                "contextId": context_id,
                "status": {"state": state},
                "artifacts": [
                    {
                        "artifactId": f"result-{task_id}",
                        "name": "Elastic result",
                        "parts": [{"data": result, "mediaType": "application/json"}],
                    }
                ],
                "metadata": metadata,
            }
        }


class A2AClient:
    """Isolated outbound adapter for delegating to an A2A HTTP+JSON agent."""

    def __init__(
        self,
        endpoint: str,
        *,
        trusted: bool = False,
        headers: Optional[Dict[str, str]] = None,
        transport: Optional[Callable[[str, Dict[str, Any], Dict[str, str]], Dict[str, Any]]] = None,
    ) -> None:
        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("A2A endpoint must be an absolute HTTP URL")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("A2A endpoint cannot contain credentials or a fragment")
        if parsed.scheme == "http" and parsed.hostname.lower() not in _LOOPBACK_HOSTS:
            raise ValueError("A2A endpoint must use HTTPS (localhost may use HTTP)")
        self.endpoint = endpoint.rstrip("/")
        self.trusted = trusted
        self.headers = dict(headers or {})
        self._transport = transport or self._http_transport

    def send(self, text: str, *, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.trusted:
            raise PermissionError("A2A server is not trusted")
        parts = [{"text": text}]
        if data:
            parts.append({"data": data, "mediaType": "application/json"})
        return self._transport(
            f"{self.endpoint}/message:send",
            {
                "message": {
                    "messageId": uuid.uuid4().hex,
                    "role": "ROLE_USER",
                    "parts": parts,
                }
            },
            self.headers,
        )

    @staticmethod
    def _http_transport(
        url: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> Dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/a2a+json",
                "A2A-Version": "1.0",
                **headers,
            },
            method="POST",
        )
        started = time.perf_counter()
        with urllib.request.build_opener(_NoRedirects()).open(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        result.setdefault("_elastic", {})["latencyMs"] = (
            time.perf_counter() - started
        ) * 1000.0
        return result


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError(f"A2A redirect refused: {newurl}")
