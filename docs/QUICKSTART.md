# Quickstart

Five minutes from clone to a compiled intent, retrieved capabilities, and a recipe run against the demo bank.

## 1. Install

```bash
git clone https://github.com/luxurylifestyleco/vedaxi-elastic.git
cd vedaxi-elastic
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install pydantic pytest jsonschema
```

Packages are imported from `packages/` on disk. They are not on PyPI.

## 2. Compile an intent

```bash
python examples/01_compile_intent.py
```

This uses `RuleBasedCompiler.compile` (`packages/intent-ir/compiler.py`) to turn strings such as `"Get my August bank statement for 2026"` into `IntentIR` objects.

You can do the same in code:

```python
import sys
sys.path.insert(0, "packages/intent-ir")
from compiler import RuleBasedCompiler

ir = RuleBasedCompiler(default_year=2026).compile("Get my August bank statement for 2026")
print(ir.goal, ir.domain, ir.action, ir.object)
```

The compiler is **rule-based**. Queries it does not recognize raise `ValueError`.

## 3. Retrieve capabilities for an intent

```bash
python examples/02_retrieve_capabilities.py
```

Loads capabilities from the demo-bank manifest, builds a keyword retriever, and prints top matches for sample goals.

## 4. Execute a recipe (zero model calls)

```bash
python examples/03_execute_recipe.py
```

Looks up a hand-written recipe in `RecipeStore` and runs its steps against `apps/demo-bank/bank.py`. Control C records `llm_calls = 0`.

## 5. Optional: HTTP gateway roundtrip

```bash
python examples/04_full_gateway_roundtrip.py
```

Starts `apps/gateway` in-process and hits `/health`, `/intent/compile`, `/capabilities/discover`.

## 6. Tests

From the repository root:

```bash
python -m pytest packages/ -q
```

If demo-bank tests fail on imports:

```bash
PYTHONPATH=packages/capability-registry python -m pytest packages/ apps/demo-bank -q
```

On Windows PowerShell: `$env:PYTHONPATH="packages/capability-registry"`.

## Next

- [CONCEPTS.md](CONCEPTS.md) — vocabulary
- [RECIPE_AUTHORING.md](RECIPE_AUTHORING.md) — write your first recipe
- [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) — expose an existing API as capabilities
