# Benchmarking

The benchmark measures the **intelligence cost per successful intent** across three control agents that satisfy the same banking intents. All three record **identical** metric fields so results are directly comparable. The benchmark's purpose is to demonstrate that a pre-authored recipe (Control C) minimizes intelligence cost versus discovery-based approaches (Controls A and B).

## Files

| File | Purpose |
|---|---|
| `packages/elastic-bench/control_a.py` | Control A — baseline agent. |
| `packages/elastic-bench/control_b.py` | Control B — retrieval agent. |
| `packages/elastic-bench/control_c.py` | Control C — recipe-assisted execution. |
| `packages/elastic-bench/agent_common.py` | Shared "LLM" and invocation logic for A and B. |
| `packages/elastic-bench/metrics.py` | Shared metric fields, token estimation, and cost model. |

## The three control agents

| Control | Approach | Model calls | What the model sees |
|---|---|---|---|
| **A — Baseline** | The model is handed the **full** list of every capability description and must select and invoke the right one. | 1 LLM call | All capabilities |
| **B — Retrieval** | Intent → capability retrieval (top-K) → the model sees **only** the top-K descriptions → select → invoke. | 1 LLM call | Top-K capabilities only |
| **C — Recipe** | A hand-written recipe is looked up by intent family and its steps are executed directly against the demo bank. | **0 LLM calls** | Nothing (procedure is pre-encoded) |

### Control A — baseline (`control_a.py`)

`BaselineAgent` is a deterministic, rule-based stand-in for an LLM. It uses the **same** shared "LLM" (`agent_common.llm_select`) and the **same** invocation logic (`agent_common.invoke`) as Control B. The **only** difference is that Control A sees **all** capability descriptions, whereas Control B sees only the top-K retrieved ones. This keeps the benchmark apples-to-apples: the same model, the same capabilities, differing only in how much of the capability surface the model is shown.

Pipeline: `IntentIR → [LLM sees ALL capabilities] → select → invoke → metrics`. `retrieval_calls` is always 0 (the full list is given, no retrieval).

### Control B — retrieval (`control_b.py`)

`RetrievalAgent` runs the pipeline `Intent → capability retrieval (top-K) → LLM sees ONLY the top-K → select → invoke`. It uses the same deterministic rule-based model as Control A; the only difference is that it sees K capabilities instead of all of them, which reduces input tokens. It records **identical** metrics to Control A, with `retrieval_calls >= 1`. The default retriever is `keyword` with `k=5`.

### Control C — recipe (`control_c.py`)

`ControlC` looks up a hand-written recipe by intent family and executes its steps against the demo-bank functions directly — no model calls, no procedure rediscovery. Because the procedure is fully encoded in the recipe, the model is never invoked: `llm_calls` is always 0 and token/cost metrics are 0. The only "retrieval" is the deterministic recipe lookup in the store (`retrieval_calls = 1`). This isolates the value of a pre-authored recipe versus the discovery-based controls.

## Metric fields

Every `run()` result contains the same ten fields (defined in `control_a.py` as `METRIC_FIELDS` and mirrored in `control_c.py`):

| Field | Description |
|---|---|
| `input_tokens` | Estimated input tokens consumed by the model. |
| `output_tokens` | Estimated output tokens produced by the model. |
| `total_tokens` | `input_tokens + output_tokens`. |
| `llm_calls` | Number of model invocations. |
| `tool_calls` | Number of capability/tool invocations. |
| `retrieval_calls` | Number of retrieval operations. |
| `steps` | Number of pipeline steps. |
| `wall_clock_latency_ms` | Wall-clock latency of the run, in milliseconds. |
| `success` | Whether the intent was fulfilled. |
| `estimated_model_cost` | Estimated model cost in USD. |

## The cost model (`metrics.py`)

Token and cost estimation are **deterministic heuristics** (no external model API) so the benchmark is reproducible and dependency-free. The same estimator is used by both controls, so any bias cancels out in the comparison.

```python
MODEL_INPUT_RATE  = 0.000002  # $ per input token
MODEL_OUTPUT_RATE = 0.000008  # $ per output token
```

- `estimate_tokens(text)` — deterministic estimate at ~4 characters per token: `max(1, ceil(len(text) / 4))`.
- `new_metrics()` — a fresh metrics dict with every field zeroed.
- `finalize(metrics)` — fills derived fields:
  - `total_tokens = input_tokens + output_tokens`
  - `estimated_model_cost = input_tokens * MODEL_INPUT_RATE + output_tokens * MODEL_OUTPUT_RATE`

Because output tokens are priced 4× higher than input tokens, the cost model rewards approaches that minimize both, but especially output. Control C makes no model calls, so its cost is always `0.0`.

## How to run the benchmark

The three control agents live in `packages/elastic-bench/`. Each exposes a `run(intent)` entry point that returns a metrics dict.

### Run the tests

```bash
cd C:/Users/m_jor/Documents/elastic-web
.venv/Scripts/python.exe -m pytest packages/elastic-bench -q
# 31 passed
```

### Drive the agents directly

From the repo root, with the sibling packages on the path:

```bash
cd C:/Users/m_jor/Documents/elastic-web
PYTHONPATH="packages/intent-ir:packages/capability-registry:packages/capability-retrieval:packages/recipe-schema:apps/demo-bank" \
  .venv/Scripts/python.exe -c "
from control_a import BaselineAgent
from control_b import RetrievalAgent
from control_c import ControlC
from manifest import build_manifest
from intent_ir import IntentIR

caps = build_manifest()
intent = IntentIR(
    intent_id=IntentIR.new_id(),
    goal='retrieve_financial_document',
    domain='banking',
    action='retrieve',
    object='account_statement',
    desired_output='pdf',
)

a = BaselineAgent(capabilities=caps)
b = RetrievalAgent(capabilities=caps, k=5)
c = ControlC()

print('A baseline:', a.run(intent)['metrics'])
print('B retrieval:', b.run(intent)['metrics'])
print('C recipe:', c.run('Get my August statement')['metrics'])
"
```

### Interpreting results

Compare the ten metric fields across the three controls for the same intent. The expected pattern:

- **Control A** pays the most: it reads the entire capability catalog as input tokens on every intent.
- **Control B** reduces input tokens by showing only the top-K descriptions.
- **Control C** is the minimum: zero tokens, zero LLM calls, zero model cost — the recipe encodes the procedure so no model inference is needed.

The benchmark's headline metric is **`estimated_model_cost` per successful intent** — the objective of Elastic is to minimize it.
