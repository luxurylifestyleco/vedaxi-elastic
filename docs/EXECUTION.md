# Execution

How a recipe actually runs in this repository.

## Entry points that exist

| Entry | Module | What it does |
|---|---|---|
| `RecipeStore.execute` | `packages/recipe-schema/store.py` | DAG-order step execution + local telemetry events |
| `control_c.run` | `packages/elastic-bench/control_c.py` | Resolve intent family → retrieve recipe → execute against demo-bank |
| `examples/03_execute_recipe.py` | examples | Runs Control C on two sample intents |

There is no hosted "production engine" in this public repo. Demo execution is in-process against `apps/demo-bank/bank.py`.

## DAG order

Each `RecipeStep.depends_on` lists `step_id`s that must complete first. `RecipeStore.execute` topological-sorts steps and calls:

```text
executor(capability_id, args) -> result
```

Control C's executor is `_bank_executor`: `getattr(bank, capability_id)(**args)`. If the demo bank has no matching callable, it raises `AttributeError`.

## Events during a run

From the `RecipeStore` module docstring, execution emits on the local `EventBus`:

- `recipe.started`
- `recipe.step.started`
- `tool.called`
- `tool.completed`
- `recipe.completed`
- failure variants (`execution.failed` / tool failure as implemented)

Telemetry is **local-only**. The store never posts to an external sink. If you omit `bus`, it creates a private in-memory bus.

Canonical event type names: `packages/telemetry/events.py` (`EventType`).

## Control C intent resolution

`control_c.run(intent)` accepts:

- a dict with `intent_family`, or
- a natural-language string matched by `_INTENT_FAMILY_KEYWORDS` (`statement` → `retrieve_statement`, `pay`/`bill` → `make_payment`, `freeze`/`card` → `freeze_card`)

Unknown strings raise `ValueError`. That keyword table is **demo harness**, not a general NLU system.

## Metrics Control C returns

`run` returns `recipe_id`, `intent_family`, `results` (step_id → bank result), and `metrics` with the same fields as Controls A/B (`packages/elastic-bench/metrics.py`): tokens, `llm_calls` (0 for C), `tool_calls`, `steps`, `wall_clock_latency_ms`, `success`, `estimated_model_cost`.

Token and cost fields for Control C are zeros / estimates per that metrics module — there is no billed LLM call.

## What execution does not do here

- No remote worker pool
- No cancellation of in-flight HTTP from this package
- No proprietary EXPLORE / REUSE / ADAPT / CHALLENGE policy (not in this repo)
