"""ElasticBench V0 runner (Phase 15).

Runs Control A (baseline), Control B (retrieval), and Control C (recipe)
across a synthetic suite of >=100 IntentIR tasks sampled from the 64
capabilities in the demo-bank manifest, and produces honest, comparable
metrics.

Outputs (written to ``reports/`` under this package):
    * benchmark_results.json  — full machine-readable report
    * benchmark_results.csv   — one row per (task, control) run
    * BENCHMARK_REPORT.md     — readable Markdown summary

The runner is standalone: it bootstraps ``sys.path`` so sibling packages
(intent-ir, capability-registry, capability-retrieval, recipe-schema) and
the demo-bank app are importable without pytest's conftest.
"""

from __future__ import annotations

import csv
import json
import os
import random
import statistics
import sys
import time
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Import path bootstrap (mirrors conftest.py + control_c.py) so the runner
# works standalone, not just under pytest.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_PACKAGES_DIR = os.path.dirname(_HERE)  # packages/
_APPS_DIR = os.path.join(os.path.dirname(_PACKAGES_DIR), "apps")

for _name in ("intent-ir", "capability-registry", "capability-retrieval"):
    _p = os.path.join(_PACKAGES_DIR, _name)
    if _p not in sys.path:
        sys.path.insert(0, _p)

_recipe_schema = os.path.join(_PACKAGES_DIR, "recipe-schema")
if _recipe_schema not in sys.path:
    sys.path.insert(0, _recipe_schema)

_demo_bank = os.path.join(_APPS_DIR, "demo-bank")
if _demo_bank not in sys.path:
    sys.path.insert(0, _demo_bank)

from intent_ir import IntentIR  # noqa: E402
from manifest import build_manifest  # noqa: E402

from control_a import BaselineAgent  # noqa: E402
from control_b import RetrievalAgent  # noqa: E402
import control_c  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Number of synthetic task variants generated per capability. With 64
# capabilities this yields 128 tasks (>= 100).
VARIANTS_PER_CAPABILITY = 2

# Deterministic seed so the benchmark is reproducible.
SEED = 20260910

# Control C only has hand-written recipes for these intent families.
# Map capability id -> intent family for the covered subset.
RECIPE_COVERAGE: Dict[str, str] = {
    "get_statement": "retrieve_statement",
    "make_payment": "make_payment",
    "freeze_card": "freeze_card",
}

# Sample values for common input params, used to build varied context.
_SAMPLE_VALUES: Dict[str, Any] = {
    "account_id": "ACC-1001",
    "customer_id": "CUST-0001",
    "card_id": "CARD-9001",
    "period": "2026-08",
    "amount": 142.75,
    "payee": "electricity",
    "months": 6,
    "year": 2026,
    "financial_year": "2025-26",
    "loan_id": "LOAN-5001",
    "policy_id": "POL-1",
    "offer_id": "OFF-1",
    "product_id": "PROD-1",
    "holding_id": "H-1",
    "fd_id": "FD-3001",
    "payment_id": "PAY-1",
    "ticket_id": "TKT-1",
    "document_id": "DOC-0001",
    "biller_id": "BILL-1",
    "to_account": "ACC-1002",
    "from_account": "ACC-1001",
    "from_party": "alice@example.com",
    "participants": ["alice@example.com", "bob@example.com"],
    "limits": {"daily_limit": 1500.0, "monthly_limit": 8000.0},
    "alerts": ["low_balance", "large_transaction"],
    "nominee": {"name": "Alex Smith", "relation": "spouse"},
    "address": {"line1": "2 Oak Avenue", "city": "Springfield", "postcode": "12345"},
    "phone": "+1-555-0100",
    "email": "customer@example.com",
    "subject": "Card not working",
    "description": "My card was declined at a store.",
    "category": "cards",
    "topic": "general",
    "query": "how do I freeze my card",
    "preferred_time": "2026-09-11T10:00:00Z",
    "document_type": "passport",
    "file_name": "passport.pdf",
    "loan_type": "personal",
    "tenure_months": 24,
    "product_type": "mutual_fund",
    "units": 10.0,
    "claim_details": {"reason": "hospitalization"},
    "new_pin": "1234",
    "reason": "damaged",
    "new_number": True,
    "delivery_address": "1 Main Street, Springfield",
    "frequency": "monthly",
    "start_date": "2026-10-01",
    "from_date": "2026-01-01",
    "to_date": "2026-12-31",
    "page": 1,
    "reference": "ref-001",
    "currency": "USD",
    "note": "please pay",
    "from_account": "ACC-1001",
}

# Desired output formats to vary across tasks.
_OUTPUT_FORMATS = ["json", "pdf", "csv", "json", "pdf"]

# Verb/object derivation from a capability's human name, e.g.
# "Get Account Balance" -> action "get", object "account_balance".
def _action_object_from_name(name: str) -> tuple:
    parts = name.strip().split()
    if not parts:
        return "operate", "resource"
    action = parts[0].lower()
    obj = "_".join(p.lower() for p in parts[1:]) if len(parts) > 1 else "resource"
    return action, obj


# ---------------------------------------------------------------------------
# Synthetic task generation
# ---------------------------------------------------------------------------

def generate_tasks(
    capabilities: List[Any],
    variants: int = VARIANTS_PER_CAPABILITY,
    seed: int = SEED,
) -> List[IntentIR]:
    """Build a varied synthetic IntentIR suite from the capability manifest.

    For each capability we emit ``variants`` tasks, each with the capability
    id as the goal (so the routing signal is well-defined) but with varied
    action/object/desired_output/context so the suite is not degenerate.
    """
    rng = random.Random(seed)  # reserved for future stochastic variation
    tasks: List[IntentIR] = []
    for cap in capabilities:
        action, obj = _action_object_from_name(cap.name)
        for v in range(variants):
            # Build a context dict from the capability's inputs. Include every
            # input param that has a sample value so required (no-default)
            # params are always satisfied — otherwise the synthetic task is
            # under-specified and the control fails for the wrong reason.
            context: Dict[str, Any] = {}
            for key in (cap.inputs or {}).keys():
                if key in _SAMPLE_VALUES:
                    context[key] = _SAMPLE_VALUES[key]

            desired_output = _OUTPUT_FORMATS[(v + len(tasks)) % len(_OUTPUT_FORMATS)]
            tasks.append(
                IntentIR(
                    intent_id=f"synth-{cap.id}-{v}",
                    goal=cap.id,
                    domain=cap.domain,
                    action=action,
                    object=obj,
                    desired_output=desired_output,
                    context=context,
                    constraints={"priority": "normal"},
                    metadata={"source": "elastic-bench-v0", "capability": cap.id},
                )
            )
    return tasks


# ---------------------------------------------------------------------------
# Control execution
# ---------------------------------------------------------------------------

def _run_control_a(agent_a: BaselineAgent, intent: IntentIR) -> Dict[str, Any]:
    return agent_a.run(intent)


def _run_control_b(agent_b: RetrievalAgent, intent: IntentIR) -> Dict[str, Any]:
    return agent_b.run(intent)


def _run_control_c(harness: control_c.ControlC, intent: IntentIR) -> Dict[str, Any]:
    """Run Control C, mapping the intent to a recipe family when covered.

    Control C only has hand-written recipes for a narrow subset of intent
    families (statement, payment, card freeze). For uncovered capabilities
    we record an honest failure with a clear "not covered" error rather than
    passing a natural-language string that could accidentally match a recipe
    keyword and misroute to the wrong recipe.
    """
    family = RECIPE_COVERAGE.get(intent.goal)
    if family is None:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "llm_calls": 0,
            "tool_calls": 0,
            "retrieval_calls": 1,
            "steps": 0,
            "wall_clock_latency_ms": 0.0,
            "success": False,
            "estimated_model_cost": 0.0,
            "error": f"no recipe covers capability '{intent.goal}'",
        }
    intent_arg: Any = {"intent_family": family}
    params: Optional[Dict[str, Any]] = dict(intent.context)
    try:
        result = harness.run(intent_arg, params=params)
        return result["metrics"]
    except Exception as exc:  # noqa: BLE001 - record any failure honestly
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "llm_calls": 0,
            "tool_calls": 0,
            "retrieval_calls": 1,
            "steps": 0,
            "wall_clock_latency_ms": 0.0,
            "success": False,
            "estimated_model_cost": 0.0,
            "error": f"{type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    return statistics.median(values)


def aggregate(rows: List[Dict[str, Any]], control: str) -> Dict[str, Any]:
    """Aggregate per-run rows for a single control into summary metrics."""
    runs = [r for r in rows if r["control"] == control]
    n = len(runs)
    successes = [r for r in runs if r["success"]]
    n_success = len(successes)

    def col(key: str) -> List[float]:
        return [float(r[key]) for r in runs]

    def col_success(key: str) -> List[float]:
        return [float(r[key]) for r in successes]

    total_cost = sum(r["estimated_model_cost"] for r in runs)
    cost_per_success = (
        sum(r["estimated_model_cost"] for r in successes) / n_success
        if n_success
        else 0.0
    )

    return {
        "control": control,
        "runs": n,
        "successes": n_success,
        "failures": n - n_success,
        "success_rate": (n_success / n) if n else 0.0,
        "input_tokens": {
            "median": _median(col("input_tokens")),
            "p95": _percentile(col("input_tokens"), 95),
        },
        "output_tokens": {
            "median": _median(col("output_tokens")),
            "p95": _percentile(col("output_tokens"), 95),
        },
        "total_tokens": {
            "median": _median(col("total_tokens")),
            "p95": _percentile(col("total_tokens"), 95),
        },
        "latency_ms": {
            "median": _median(col("wall_clock_latency_ms")),
            "p95": _percentile(col("wall_clock_latency_ms"), 95),
        },
        "total_llm_calls": int(sum(col("llm_calls"))),
        "total_tool_calls": int(sum(col("tool_calls"))),
        "total_retrieval_calls": int(sum(col("retrieval_calls"))),
        "total_steps": int(sum(col("steps"))),
        "total_estimated_cost": total_cost,
        "cost_per_successful_intent": cost_per_success,
    }


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def _write_json(report: Dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
        fh.write("\n")


def _write_csv(rows: List[Dict[str, Any]], path: str) -> None:
    if not rows:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("")
        return
    fieldnames = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _fmt_usd(x: float) -> str:
    return f"${x:.6f}"


def _write_markdown(report: Dict[str, Any], path: str) -> None:
    lines: List[str] = []
    lines.append("# ElasticBench V0 — Benchmark Report")
    lines.append("")
    lines.append(f"- **Generated:** {report['generated_at']}")
    lines.append(f"- **Tasks:** {report['num_tasks']} synthetic IntentIR tasks")
    lines.append(
        f"- **Capabilities sampled:** {report['num_capabilities']} of "
        f"{report['total_capabilities']} in the demo-bank manifest"
    )
    lines.append(f"- **Domains covered:** {report['num_domains']}")
    lines.append(f"- **Seed:** {report['seed']}")
    lines.append("")
    lines.append("## Controls")
    lines.append("")
    lines.append(
        "- **Control A (baseline):** full capability list in context, no retrieval."
    )
    lines.append(
        "- **Control B (retrieval):** top-K retrieval, LLM sees only K capabilities."
    )
    lines.append(
        "- **Control C (recipe):** pre-authored recipes; no model calls. "
        "Only covers 3 intent families (statement, payment, card freeze)."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    a = report["aggregates"]["control_a"]
    b = report["aggregates"]["control_b"]
    c = report["aggregates"]["control_c"]
    lines.append("| Metric | Control A | Control B | Control C |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| Success rate | {_fmt_pct(a['success_rate'])} | "
        f"{_fmt_pct(b['success_rate'])} | {_fmt_pct(c['success_rate'])} |"
    )
    lines.append(
        f"| Median total tokens | {a['total_tokens']['median']:.0f} | "
        f"{b['total_tokens']['median']:.0f} | {c['total_tokens']['median']:.0f} |"
    )
    lines.append(
        f"| Median latency (ms) | {a['latency_ms']['median']:.2f} | "
        f"{b['latency_ms']['median']:.2f} | {c['latency_ms']['median']:.2f} |"
    )
    lines.append(
        f"| Cost / successful intent | {_fmt_usd(a['cost_per_successful_intent'])} | "
        f"{_fmt_usd(b['cost_per_successful_intent'])} | "
        f"{_fmt_usd(c['cost_per_successful_intent'])} |"
    )
    lines.append("")
    lines.append("### Per-control detail")
    lines.append("")
    for ctrl in ("control_a", "control_b", "control_c"):
        agg = report["aggregates"][ctrl]
        lines.append(f"### {ctrl}")
        lines.append("")
        lines.append(f"- Runs: {agg['runs']} (successes: {agg['successes']}, failures: {agg['failures']})")
        lines.append(f"- Success rate: {_fmt_pct(agg['success_rate'])}")
        lines.append(
            f"- Input tokens: median {agg['input_tokens']['median']:.0f}, "
            f"p95 {agg['input_tokens']['p95']:.0f}"
        )
        lines.append(
            f"- Output tokens: median {agg['output_tokens']['median']:.0f}, "
            f"p95 {agg['output_tokens']['p95']:.0f}"
        )
        lines.append(
            f"- Total tokens: median {agg['total_tokens']['median']:.0f}, "
            f"p95 {agg['total_tokens']['p95']:.0f}"
        )
        lines.append(
            f"- Latency: median {agg['latency_ms']['median']:.2f} ms, "
            f"p95 {agg['latency_ms']['p95']:.2f} ms"
        )
        lines.append(f"- Total LLM calls: {agg['total_llm_calls']}")
        lines.append(f"- Total tool calls: {agg['total_tool_calls']}")
        lines.append(f"- Total retrieval calls: {agg['total_retrieval_calls']}")
        lines.append(f"- Total steps: {agg['total_steps']}")
        lines.append(f"- Total estimated cost: {_fmt_usd(agg['total_estimated_cost'])}")
        lines.append(
            f"- Cost per successful intent: {_fmt_usd(agg['cost_per_successful_intent'])}"
        )
        lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Control C only has hand-written recipes for 3 intent families; "
        "tasks outside that coverage are recorded as failures (honest coverage "
        "limitation, not a bug)."
    )
    lines.append(
        "- Token and cost estimates are deterministic heuristics (see metrics.py); "
        "no external LLM API is called."
    )
    lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Main benchmark
# ---------------------------------------------------------------------------

def run_benchmark(
    num_variants: int = VARIANTS_PER_CAPABILITY,
    seed: int = SEED,
    reports_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the full benchmark and write the three report files.

    Returns the JSON report dict.
    """
    if reports_dir is None:
        reports_dir = os.path.join(_HERE, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    capabilities = build_manifest()
    tasks = generate_tasks(capabilities, variants=num_variants, seed=seed)
    if len(tasks) < 100:
        raise RuntimeError(
            f"benchmark requires >=100 tasks, generated only {len(tasks)}"
        )

    agent_a = BaselineAgent(capabilities)
    agent_b = RetrievalAgent(capabilities)
    harness = control_c.ControlC()

    rows: List[Dict[str, Any]] = []
    for intent in tasks:
        for control, run_fn in (
            ("control_a", lambda i: _run_control_a(agent_a, i)),
            ("control_b", lambda i: _run_control_b(agent_b, i)),
            ("control_c", lambda i: _run_control_c(harness, i)),
        ):
            start = time.perf_counter()
            try:
                metrics = run_fn(intent)
            except Exception as exc:  # noqa: BLE001 - never let one task abort the run
                metrics = {
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
                    "error": f"{type(exc).__name__}: {exc}",
                }
            latency = (time.perf_counter() - start) * 1000.0
            row = {
                "intent_id": intent.intent_id,
                "goal": intent.goal,
                "domain": intent.domain,
                "control": control,
                "success": bool(metrics.get("success", False)),
                "input_tokens": int(metrics.get("input_tokens", 0)),
                "output_tokens": int(metrics.get("output_tokens", 0)),
                "total_tokens": int(metrics.get("total_tokens", 0)),
                "llm_calls": int(metrics.get("llm_calls", 0)),
                "tool_calls": int(metrics.get("tool_calls", 0)),
                "retrieval_calls": int(metrics.get("retrieval_calls", 0)),
                "steps": int(metrics.get("steps", 0)),
                "wall_clock_latency_ms": round(
                    float(metrics.get("wall_clock_latency_ms", latency)), 3
                ),
                "estimated_model_cost": float(metrics.get("estimated_model_cost", 0.0)),
                "error": metrics.get("error", ""),
            }
            rows.append(row)

    aggregates = {
        "control_a": aggregate(rows, "control_a"),
        "control_b": aggregate(rows, "control_b"),
        "control_c": aggregate(rows, "control_c"),
    }

    domains = sorted({c.domain for c in capabilities})
    report: Dict[str, Any] = {
        "benchmark": "elastic-bench-v0",
        "phase": 15,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "seed": seed,
        "num_tasks": len(tasks),
        "num_capabilities": len(capabilities),
        "total_capabilities": len(capabilities),
        "num_domains": len(domains),
        "domains": domains,
        "controls": ["control_a", "control_b", "control_c"],
        "aggregates": aggregates,
        "rows": rows,
    }

    json_path = os.path.join(reports_dir, "benchmark_results.json")
    csv_path = os.path.join(reports_dir, "benchmark_results.csv")
    md_path = os.path.join(reports_dir, "BENCHMARK_REPORT.md")

    _write_json(report, json_path)
    _write_csv(rows, csv_path)
    _write_markdown(report, md_path)

    report["outputs"] = {
        "json": json_path,
        "csv": csv_path,
        "markdown": md_path,
    }
    return report


def main() -> None:
    report = run_benchmark()
    print(f"Benchmark complete: {report['num_tasks']} tasks")
    for ctrl in ("control_a", "control_b", "control_c"):
        agg = report["aggregates"][ctrl]
        print(
            f"  {ctrl}: success={agg['success_rate']*100:.1f}% "
            f"({agg['successes']}/{agg['runs']}), "
            f"median_total_tokens={agg['total_tokens']['median']:.0f}, "
            f"median_latency={agg['latency_ms']['median']:.2f}ms, "
            f"cost/success={agg['cost_per_successful_intent']:.6f}"
        )
    for kind, path in report["outputs"].items():
        print(f"  {kind}: {path}")


if __name__ == "__main__":
    main()
