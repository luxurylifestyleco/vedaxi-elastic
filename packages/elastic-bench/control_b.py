"""Control B — retrieval agent (Phase 10).

Pipeline: Intent -> capability retrieval (top-K) -> LLM sees ONLY the
top-K capability descriptions -> select best -> invoke against demo-bank.

The LLM is the SAME deterministic rule-based model as Control A; the only
difference is that it sees K capabilities instead of all of them, which
reduces input tokens. Records IDENTICAL metrics to Control A.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from capability import Capability
from intent_ir import IntentIR

from agent_common import build_prompt, invoke, llm_select
from metrics import estimate_tokens, finalize, new_metrics


class RetrievalAgent:
    """Control B: intent -> retrieval(top-K) -> LLM -> execution."""

    def __init__(
        self,
        capabilities: List[Capability],
        retriever=None,
        k: int = 5,
    ) -> None:
        self._capabilities = list(capabilities)
        self._retriever = retriever
        self._k = k

    def run(self, intent: IntentIR, capabilities=None, k: int = 5) -> Dict[str, Any]:
        """Run the retrieval agent for an intent.

        Args:
            intent: The structured intent to fulfill.
            capabilities: Optional capability list override (defaults to the
                agent's capabilities).
            k: Number of capabilities to retrieve (default 5).

        Returns:
            A metrics dict with all Control-A-identical fields, including
            ``retrieval_calls >= 1``.
        """
        start = time.perf_counter()
        metrics = new_metrics()

        caps = list(capabilities) if capabilities is not None else self._capabilities
        k = k if k is not None else self._k

        # (1) Capability retrieval -> top-K.
        retriever = self._retriever
        if retriever is None:
            from factory import build_retriever

            retriever = build_retriever("keyword", caps)
        candidates = retriever.retrieve(intent, k=k)
        metrics["retrieval_calls"] = 1
        metrics["steps"] = 1

        # Map candidates back to Capability objects, preserving retrieval order.
        by_id = {c.id: c for c in caps}
        top_caps = [by_id[c.capability_id] for c in candidates if c.capability_id in by_id]
        if not top_caps:
            metrics["success"] = False
            metrics["error"] = "retrieval returned no capabilities"
            metrics["wall_clock_latency_ms"] = (time.perf_counter() - start) * 1000.0
            return finalize(metrics)

        # (2) LLM sees ONLY the top-K capability descriptions.
        prompt = build_prompt(intent, top_caps)
        metrics["input_tokens"] = estimate_tokens(prompt)
        metrics["llm_calls"] = 1
        metrics["steps"] += 1

        # (3) Select the best capability.
        cap = llm_select(intent, top_caps)
        metrics["output_tokens"] = estimate_tokens(cap.id)
        metrics["steps"] += 1

        # (4) Invoke against demo-bank.
        try:
            result = invoke(cap, intent)
            metrics["tool_calls"] = 1
            metrics["success"] = bool(result.get("ok", True))
            metrics["steps"] += 1
        except Exception as exc:  # noqa: BLE001
            metrics["success"] = False
            metrics["error"] = str(exc)

        metrics["wall_clock_latency_ms"] = (time.perf_counter() - start) * 1000.0
        return finalize(metrics)
