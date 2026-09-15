# Build your first recipe

A recipe is a **declarative DAG**, not a prompt. Each step names a `capability_id` that an executor will invoke.

This tutorial uses the public models in `packages/recipe-schema/` and the demo-bank executor used by Control C.

## 1. The schema that actually exists

`RecipeStep` (`packages/recipe-schema/recipe.py`):

- `step_id`, `action`, `capability_id` — required, non-blank
- `args` — dict passed to the executor
- `depends_on` — other `step_id`s that must finish first
- `checkpoints` — optional named checks after the step

`Recipe`:

- `recipe_id`, `intent_family`, `version` (default `1.0.0`)
- `steps` — list of `RecipeStep` (a DAG via `depends_on`)
- `status` — `draft` | `active` | `deprecated` | `retired`
- plus optional lists: `applicability_conditions`, `invariants`, `success_conditions`, `fallbacks`, `skills`, …

Automatic recipe *creation* is **not implemented** here. You author the object and `RecipeStore.create` stores it.

## 2. Copy a working pattern

Control C registers three recipes in `packages/elastic-bench/control_c.py` (`build_store`). The payment recipe is a two-step DAG: balance check, then pay.

Minimal equivalent:

You can construct and store a recipe in tests the same way `packages/recipe-schema/test_recipe.py` does. For a full run against the demo bank (including telemetry imports the store needs), use the existing example instead of copy-pasting a bare `RecipeStore()` from a random working directory:

```bash
python examples/03_execute_recipe.py
```

Minimal object (fields that exist on `Recipe` / `RecipeStep`):

```python
from recipe import Recipe, RecipeStep, RecipeStatus

payment = Recipe(
    recipe_id="make-payment-demo",
    intent_family="make_payment",
    version="1.0.0",
    status=RecipeStatus.ACTIVE,
    steps=[
        RecipeStep(
            step_id="check_balance",
            action="get",
            capability_id="get_balance",
            args={},
        ),
        RecipeStep(
            step_id="pay",
            action="pay",
            capability_id="make_payment",
            args={"amount": 89.50, "payee": "City Power"},
            depends_on=["check_balance"],
        ),
    ],
)
```

Pydantic rejects unknown fields and blank required strings. That **is** validation.

## 3. Execute against the demo bank

`RecipeStore.execute(recipe_id, executor)` runs steps in dependency order. Control C's executor is:

```python
# packages/elastic-bench/control_c.py — _bank_executor
fn = getattr(bank, capability_id, None)
return fn(**args)
```

End-to-end without writing an executor yourself:

```bash
python examples/03_execute_recipe.py
```

`control_c.run("Pay electricity bill", params={"amount": 89.50, "payee": "City Power"})` resolves the intent family by **keyword** (`pay` / `payment` / …) then executes the stored recipe. That keyword map is demo-only (`_INTENT_FAMILY_KEYWORDS` in `control_c.py`). Production systems should pass `{"intent_family": "make_payment"}` explicitly.

## 4. Lifecycle

`RecipeStore` also supports `version` (new version of an existing id), `deprecate`, and `retire`. See [RECIPES.md](RECIPES.md).

## What a recipe is not

- Not an LLM prompt
- Not a learned policy
- Not automatic optimization

Those belong outside this public repository ([PUBLIC_PRIVATE_BOUNDARY.md](PUBLIC_PRIVATE_BOUNDARY.md)).
