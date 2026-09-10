"""Control A — baseline agent (Phase 9) for Elastic Web.

Control A is the conventional baseline: an agent that is handed the FULL
list of every available capability description and must select and invoke
the right one for a given :class:`~intent_ir.IntentIR`.

Because no external LLM API is available in this environment, the agent is
a deterministic, rule-based stand-in for an LLM. It:

    1. receives the full capability list (all 63-64 descriptions),
    2. scores each capability against the intent using keyword term
       overlap (reusing the keyword-retrieval strategy logic conceptually),
    3. selects the top-scoring capability,
    4. invokes it against the demo-bank functions,
    5. records honest metrics (token estimates, call counts, latency,
       success, and an estimated model cost).

This is CONTROL A: the agent is deliberately given access to ALL capability
descriptions (no retrieval step). The benchmark is NOT tuned to make any
control win — metrics are recorded honestly.

The LLM model, prompt builder, and invocation logic are shared with
Control B via :mod:`agent_common`; the metric fields and token/cost
estimators are shared via :mod:`metrics`. The only difference from
Control B is that this agent sees every capability instead of only the
top-K retrieved ones.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from capability import Capability
from intent_ir import IntentIR

from agent_common import build_prompt, invoke, llm_select
from metrics import estimate_tokens, finalize, new_metrics

# The metric fields every run() result must contain (shared with Control B).
METRIC_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "llm_calls",
    "tool_calls",
    "retrieval_calls",
    "steps",
    "wall_clock_latency_ms",
    "success",
    "estimated_model_cost",
)


class BaselineAgent:
    """Deterministic rule-based stand-in for an LLM-driven baseline agent.

    Given an :class:`IntentIR` and the full list of capability descriptions,
    it scores every capability by keyword term overlap, selects the top one,
    invokes the matching demo-bank function, and returns a metrics dict.
    """

    def __init__(self, capabilities: List[Capability]) -> None:
        self._capabilities = list(capabilities)

    def run(
        self,
        intent: IntentIR,
        capabilities: Optional[List[Capability]] = None,
    ) -> Dict[str, Any]:
        """Select and invoke a capability for ``intent``, returning metrics.

        Args:
            intent: The structured intent to satisfy.
            capabilities: Optional full capability list override (defaults to
                the agent's capabilities).

        Returns:
            A dict with all :data:`METRIC_FIELDS` plus the selected
            capability, selection score, result, and any error.
        """
        start = time.perf_counter()
        metrics = new_metrics()

        caps = list(capabilities) if capabilities is not None else self._capabilities
        if not caps:
            metrics["success"] = False
            metrics["error"] = "no capabilities provided to the baseline agent"
            metrics["wall_clock_latency_ms"] = (time.perf_counter() - start) * 1000.0
            return finalize(metrics)

        # (1) The "LLM" reads the FULL capability list once and picks a tool.
        #     Control A: no retrieval step — every description is in context.
        prompt = build_prompt(intent, caps)
        metrics["input_tokens"] = estimate_tokens(prompt)
        metrics["llm_calls"] = 1
        metrics["retrieval_calls"] = 0
        metrics["steps"] = 1

        # (2) Select the best capability (same model as Control B).
        cap = llm_select(intent, caps)
        metrics["output_tokens"] = estimate_tokens(cap.id)
        metrics["steps"] += 1

        # (3) Invoke against the demo-bank functions.
        try:
            result = invoke(cap, intent)
            metrics["tool_calls"] = 1
            metrics["success"] = bool(result.get("ok", True))
            metrics["steps"] += 1
        except Exception as exc:  # noqa: BLE001 - record any failure
            metrics["success"] = False
            metrics["error"] = str(exc)

        metrics["wall_clock_latency_ms"] = (time.perf_counter() - start) * 1000.0
        metrics["selected_capability"] = cap.id
        return finalize(metrics)
