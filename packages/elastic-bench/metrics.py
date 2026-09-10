"""Shared benchmark metrics for Elastic Web Control A and Control B.

Both controls record IDENTICAL metric fields so results are directly
comparable. The metric set is:

    input_tokens, output_tokens, total_tokens, llm_calls, tool_calls,
    retrieval_calls, steps, wall_clock_latency_ms, success,
    estimated_model_cost

Token and cost estimation are deterministic heuristics (no external model
API) so the benchmark is reproducible and dependency-free. The same
estimator is used by both controls, so any bias cancels out in the
comparison.
"""

from __future__ import annotations

from typing import Any, Dict

# ---------------------------------------------------------------------------
# Model pricing (arbitrary but fixed, per-token USD). Identical for both
# controls so the cost comparison is apples-to-apples.
# ---------------------------------------------------------------------------
MODEL_INPUT_RATE = 0.000002  # $ per input token
MODEL_OUTPUT_RATE = 0.000008  # $ per output token

# Deterministic token estimate: ~4 characters per token.
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in ``text`` (deterministic heuristic)."""
    if not text:
        return 0
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


def new_metrics() -> Dict[str, Any]:
    """Return a fresh metrics dict with every field initialized to zero."""
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "llm_calls": 0,
        "tool_calls": 0,
        "retrieval_calls": 0,
        "steps": 0,
        "wall_clock_latency_ms": 0.0,
        "success": False,
        "estimated_model_cost": 0.0,
    }


def finalize(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Fill derived fields (total_tokens, cost) from the raw counters."""
    metrics["total_tokens"] = metrics["input_tokens"] + metrics["output_tokens"]
    metrics["estimated_model_cost"] = (
        metrics["input_tokens"] * MODEL_INPUT_RATE
        + metrics["output_tokens"] * MODEL_OUTPUT_RATE
    )
    return metrics
