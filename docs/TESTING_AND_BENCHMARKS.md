# Testing and benchmarks

## Tests

From the repository root (with deps: `pydantic`, `pytest`, `jsonschema`):

```bash
python -m pytest packages/ -q
```

Demo-bank tests need the registry on the path:

```bash
PYTHONPATH=packages/capability-registry python -m pytest packages/ apps/demo-bank -q
```

Tests live next to each package (`test_*.py`), not under a top-level `tests/` tree (that directory is empty).

Runnable examples (also used as smoke checks):

```bash
python examples/01_compile_intent.py
python examples/02_retrieve_capabilities.py
python examples/03_execute_recipe.py
python examples/04_full_gateway_roundtrip.py
```

## What the benchmark measures

File: `docs/BENCHMARKING.md` (methodology) and `packages/elastic-bench/`.

**Question:** for the same demo-bank intents, how much "intelligence cost" does each approach spend?

| Control | Code | Approach |
|---|---|---|
| A | `control_a.py` | Deterministic selector sees **all** capability descriptions |
| B | `control_b.py` | Same selector sees **top-K** retrieved descriptions |
| C | `control_c.py` | Hand-written recipe; **no** selector call |

Shared metric fields (`metrics.py`): `input_tokens`, `output_tokens`, `total_tokens`, `llm_calls`, `tool_calls`, `retrieval_calls`, `steps`, `wall_clock_latency_ms`, `success`, `estimated_model_cost`.

The "LLM" is `agent_common.llm_select` — a **rule-based stand-in**, not a hosted model. Token counts and `estimated_model_cost` are **estimates** from character/token helpers and fixed USD/token rates. Latency is **loop-measured** (`wall_clock_latency_ms`).

**Expected pattern on this harness:** Control C → 0 LLM calls / 0 model tokens; Control A pays the most because it reads the full catalog. That is a result **on this demo-bank set**, not a claim of universal superiority.

## How to run a comparison

Each control exposes `run(intent)` returning a metrics dict. See `packages/elastic-bench/test_benchmark_runner.py` and `benchmark_runner.py` for the harness used in CI.

```bash
python -m pytest packages/elastic-bench/test_benchmark_runner.py -q
```

Full methodology, cost model, and file map: [BENCHMARKING.md](BENCHMARKING.md).

Optional pgvector notes: [PGVECTOR-BENCHMARK.md](PGVECTOR-BENCHMARK.md) (only if you run that extra script).

## Limitations

- Demo-bank capabilities and hand-written recipes only
- Deterministic selector, not a production LLM
- Estimated costs, not provider invoices
- Does not evaluate proprietary adaptive policy (not in this repo)
