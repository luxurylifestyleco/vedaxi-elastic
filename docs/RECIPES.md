# Recipes

A **recipe** is a declarative, versioned execution plan that maps an intent family to an ordered set of steps. Recipes are the Control C mechanism: when a procedure is already known, it is encoded once as a recipe and executed directly — with **zero model calls** — instead of letting a model rediscover the procedure on every intent. This is the core of minimizing intelligence cost per successful intent.

> **Scope:** this covers recipe **storage and execution structure only**. Automatic recipe creation and optimization are explicitly out of scope and are not implemented — a recipe is authored and stored as-is, and its steps are executed in dependency (DAG) order.

## Files

| File | Purpose |
|---|---|
| `packages/recipe-schema/recipe.py` | The `Recipe` and `RecipeStep` Pydantic v2 models. |
| `packages/recipe-schema/store.py` | The `RecipeStore` (storage + execution). |
| `packages/elastic-bench/control_c.py` | The three hand-written recipes and the Control C harness. |

## The recipe schema

### `RecipeStep`

A single step in a recipe's execution DAG:

| Field | Type | Description |
|---|---|---|
| `step_id` | `str` | Unique id of the step within the recipe. |
| `action` | `str` | Verb describing what the step does. |
| `capability_id` | `str` | The capability that executes this step. |
| `args` | `Dict[str, Any]` | Arguments passed to the capability. Default `{}`. |
| `depends_on` | `List[str]` | Ids of steps that must complete before this one. Default `[]`. |
| `checkpoints` | `List[str]` | Named checkpoints to verify after the step runs. Default `[]`. |

### `Recipe`

| Field | Type | Description |
|---|---|---|
| `recipe_id` | `str` | Stable unique identifier. |
| `intent_family` | `str` | The family of intents this recipe serves. |
| `version` | `str` | Semantic version of this revision. Default `"1.0.0"`. |
| `applicability_conditions` | `List[str]` | Conditions under which the recipe applies. |
| `invariants` | `List[str]` | Conditions that must hold throughout execution. |
| `steps` | `List[RecipeStep]` | Ordered steps forming a DAG. |
| `skills` | `List[str]` | Skills the recipe draws on. |
| `adaptation_points` | `List[str]` | Points where execution may adapt. |
| `checkpoints` | `List[str]` | Recipe-level checkpoints. |
| `success_conditions` | `List[str]` | Conditions for the recipe to be considered successful. |
| `fallbacks` | `List[Dict[str, Any]]` | Fallback strategies if a step fails. |
| `freshness_policy` | `Dict[str, Any]` | Policy governing data freshness. |
| `metrics` | `List[str]` | Metrics to collect during execution. |
| `status` | `RecipeStatus` | Lifecycle status (`draft`, `active`, `deprecated`, `retired`). Default `active`. |
| `provenance` | `Dict[str, Any]` | Origin/history of the recipe. |

### DAG validation and ordering

Steps form a **directed acyclic graph**. The model validator (`_validate_dag`) enforces two invariants at construction:

1. Every `depends_on` reference must point to an existing step.
2. The dependency graph must be acyclic.

`topological_order()` (Kahn's algorithm) returns step ids in dependency order — every step appears after all of its dependencies — and raises `ValueError` if the steps contain a cycle.

## The recipe store

`RecipeStore` (`store.py`) is the source of truth for recipes, keyed by `recipe_id` and `version`:

- `create(recipe)` — store a new recipe (raises if the id+version already exists).
- `version(recipe_id, new_recipe)` — create a new version of an existing recipe.
- `retrieve(recipe_id, version=None)` — fetch a recipe (latest version by default).
- `list_versions(recipe_id)` — all versions in insertion order.
- `deprecate(recipe_id)` / `retire(recipe_id)` — mark lifecycle status.
- `execute(recipe_id, executor=None, trace_id=None, intent_id=None, version=None)` — run the recipe's steps in DAG order.

### Execution

`execute` runs steps in topological order, dispatching each to an executor callable `(capability_id, args) -> result`. If no executor is supplied, a default no-op executor records the call and returns `None`. A retired recipe cannot be executed.

Execution emits telemetry events on an `EventBus`:

- `recipe.started`
- `recipe.step.started`
- `tool.called`
- `tool.completed`
- `recipe.completed`
- `execution.failed` (on any step exception)

Telemetry is **local-only** — the store never sends data to an external sink. If no bus is supplied, a private in-memory bus is created so events remain locally inspectable.

## The three hand-written recipes

`control_c.py` authors three recipes by hand (NOT auto-created) and registers them in a `RecipeStore` via `build_store()`.

### 1. `statement.retrieve` — intent family `retrieve_statement`

Retrieve a bank statement for a period.

- **Steps:** `get_statement(period="2026-08")` — single step, no dependencies.
- **Invariants:** read-only (no data mutation); statement returned for the requested period.
- **Checkpoints:** step-level `statement returned with file_url`; recipe-level `statement delivered as pdf`.
- **Success conditions:** `get_statement returns ok=True`; `statement file_url is present`.
- **Fallbacks:** retry on timeout (max 2); ask user for period on `period_invalid`.
- **Freshness policy:** `max_age_seconds: 3600`, `stale_action: re_fetch`.

### 2. `payment.execute` — intent family `make_payment`

Check balance, then make a payment.

- **Steps (DAG):**
  1. `get_balance` (action `check_balance`) — no dependencies.
  2. `make_payment(amount=142.75, payee="electricity")` (action `pay`) — **depends on** `get_balance`, so the payment is only attempted when the account is in a healthy state.
- **Invariants:** payment amount must be positive; payment must not be initiated if balance is insufficient.
- **Checkpoints:** step-level `balance returned` and `payment completed`; recipe-level `payment confirmed`.
- **Success conditions:** `get_balance returns ok=True`; `make_payment returns status=completed`.
- **Fallbacks:** abort on `insufficient_funds`; retry on timeout (max 2).
- **Freshness policy:** `max_age_seconds: 60`, `stale_action: re_fetch_balance`.

### 3. `card.freeze` — intent family `freeze_card`

Freeze a card to prevent further transactions.

- **Steps:** `freeze_card(card_id="CARD-9001")` — single step, no dependencies.
- **Invariants:** card must be frozen immediately to block transactions; freeze is reversible via unfreeze.
- **Checkpoints:** step-level `card status is frozen`; recipe-level `card frozen`.
- **Success conditions:** `freeze_card returns status=frozen`; `card_id matches the requested card`.
- **Fallbacks:** retry on timeout (max 2); ask user for card id on `card_not_found`.
- **Freshness policy:** `max_age_seconds: 0`, `stale_action: always_execute` (a freeze is an action, not a read — always execute).

All three carry `status=ACTIVE`, `metrics=METRIC_FIELDS`, and provenance `{author: "elastic-bench", control: "C", source: "hand-written", phase: 12}`.

## Intent → recipe resolution

`resolve_intent_family(intent)` maps an intent (a dict with an `intent_family` key, or a natural-language string) to a family by keyword:

| Family | Keywords |
|---|---|
| `retrieve_statement` | `statement`, `august`, `period` |
| `make_payment` | `pay`, `payment`, `electricity`, `bill` |
| `freeze_card` | `freeze`, `stolen`, `card` |

Raises `ValueError` if no family matches.

## Control C execution

`ControlC.run(intent, params=None)`:

1. Resolves the intent to a family.
2. Looks up the matching recipe (the only "retrieval" — deterministic, `retrieval_calls = 1`).
3. Merges any `params` overrides into each step's args.
4. Executes the recipe's steps in DAG order against the demo-bank functions via `_bank_executor` (which dispatches `capability_id` → `bank.<capability_id>`).
5. Records metrics: `steps` and `tool_calls` equal the number of steps; `llm_calls`, tokens, and `estimated_model_cost` are all **0** — no model is ever invoked.

## Why recipes minimize cost

Because the procedure is fully encoded in the recipe, the model is never invoked: `llm_calls` is always 0 and token/cost metrics are 0. This isolates the value of a pre-authored recipe versus the discovery-based controls (A and B), which must spend model tokens to select a capability on every intent.

## Tests

`packages/elastic-bench` contains 31 tests, including coverage of the three recipes, DAG ordering, and Control C execution.
