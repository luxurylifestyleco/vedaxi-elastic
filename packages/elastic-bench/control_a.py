"""Baseline Agent (Phase 9, Control A) for Elastic Web.

Control A is the conventional baseline: an agent that is handed the FULL
list of every available capability description and must select and invoke
the right one for a given :class:`~intent_ir.IntentIR`.

Because no external LLM API is available in this environment, the agent is
a deterministic, rule-based stand-in for an LLM. It uses the SAME shared
"LLM" (``agent_common.llm_select``) and the SAME invocation logic
(``agent_common.invoke``) as Control B — the ONLY difference is that
Control A sees ALL capability descriptions, whereas Control B sees only the
top-K retrieved ones. This keeps the benchmark apples-to-apples: the same
model, the same capabilities, differing only in how much of the capability
surface the model is shown.

It records honest metrics (token estimates, call counts, latency, success,
and an estimated model cost) identical to Control B.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# sys.path bootstrap so this package can import its sibling packages and the
# demo-bank app directly (matches the conftest pattern used elsewhere).
# ---------------------------------------------------------------------------
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))          # packages/elastic-bench
_PACKAGES_DIR = os.path.dirname(_PKG_DIR)                       # packages
_REPO_ROOT = os.path.dirname(_PACKAGES_DIR)                     # elastic-web
_APP_DIR = os.path.join(_REPO_ROOT, "apps", "demo-bank")

for _path in (
    _PACKAGES_DIR,
    os.path.join(_PACKAGES_DIR, "intent-ir"),
    os.path.join(_PACKAGES_DIR, "capability-registry"),
    os.path.join(_PACKAGES_DIR, "capability-retrieval"),
    _APP_DIR,
):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from capability import Capability  # noqa: E402
from intent_ir import IntentIR  # noqa: E402

from agent_common import build_prompt, invoke, llm_select  # noqa: E402
from metrics import estimate_tokens, finalize, new_metrics  # noqa: E402

# The metric fields every run() result must contain (identical to Control B).
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

    Given an :class:`IntentIR` and the FULL list of capability descriptions,
    it uses the shared rule-based "LLM" to select the best capability, invokes
    the matching demo-bank function, and returns a metrics dict. It sees ALL
    capabilities (no retrieval step) — that is what distinguishes Control A
    from Control B.
    """

    def __init__(
        self,
        capabilities: Optional[List[Capability]] = None,
        bank_module: Any = None,
    ) -> None:
        self._bank = bank_module
        self._capabilities: Optional[List[Capability]] = None
        if capabilities is not None:
            self.set_capabilities(capabilities)

    # -- configuration ---------------------------------------------------

    def set_capabilities(self, capabilities: List[Capability]) -> None:
        """Store the full capability list (the entire surface the LLM sees)."""
        self._capabilities = list(capabilities)

    # -- main entry point ------------------------------------------------

    def run(
        self,
        intent: IntentIR,
        capabilities: Optional[List[Capability]] = None,
    ) -> Dict[str, Any]:
        """Select and invoke a capability for ``intent``, returning metrics.

        Args:
            intent: The structured intent to satisfy.
            capabilities: The FULL list of capability descriptions. If
                omitted, the list configured at construction is used.

        Returns:
            A dict with all :data:`METRIC_FIELDS` plus the selected
            capability, selection score, result, and any error.
        """
        if capabilities is not None:
            self.set_capabilities(capabilities)
        if self._capabilities is None:
            raise ValueError("no capabilities provided to the baseline agent")

        start = time.perf_counter()
        metrics = new_metrics()

        # The "LLM" reads the full capability list once and picks a tool.
        metrics["llm_calls"] = 1
        metrics["retrieval_calls"] = 0  # Control A: full list is given, no retrieval.
        metrics["steps"] = 1

        # Build the prompt from ALL capabilities (no retrieval).
        prompt = build_prompt(intent, self._capabilities)
        metrics["input_tokens"] = estimate_tokens(prompt)

        # Select the best capability using the SAME shared LLM as Control B.
        cap = llm_select(intent, self._capabilities)
        metrics["output_tokens"] = estimate_tokens(cap.id)
        metrics["steps"] += 1

        # Invoke the selected capability against the demo-bank functions.
        try:
            result = invoke(cap, intent)
            metrics["tool_calls"] = 1
            metrics["success"] = bool(result.get("ok", True))
            metrics["steps"] += 1
        except Exception as exc:  # noqa: BLE001 - record any failure
            metrics["success"] = False
            metrics["error"] = str(exc)
            result = None

        metrics["wall_clock_latency_ms"] = (time.perf_counter() - start) * 1000.0
        metrics = finalize(metrics)

        metrics["intent_id"] = intent.intent_id
        metrics["selected_capability"] = cap.id
        metrics["result"] = result
        metrics["error"] = metrics.get("error")
        return metrics
