# Elastic Web

![CI](https://github.com/luxurylifestyleco/vedaxi-elastic/actions/workflows/ci.yml/badge.svg)
![Schema Validation](https://github.com/luxurylifestyleco/vedaxi-elastic/actions/workflows/schema-validation.yml/badge.svg)
![Dependency & License](https://github.com/luxurylifestyleco/vedaxi-elastic/actions/workflows/dependency-license.yml/badge.svg)
![Integration](https://github.com/luxurylifestyleco/vedaxi-elastic/actions/workflows/integration.yml/badge.svg)
![DB Migration](https://github.com/luxurylifestyleco/vedaxi-elastic/actions/workflows/db-migration.yml/badge.svg)
![Boundary Check](https://github.com/luxurylifestyleco/vedaxi-elastic/actions/workflows/boundary-check.yml/badge.svg)

Repository stewardship: `luxurylifestyleco/vedaxi-elastic` is the canonical
foundation. Its current GitHub visibility is private; documentation about an
open-source foundation describes its intended boundary, not authorization to
publish it. See [repository ownership](docs/REPOSITORY-OWNERSHIP.md) for contribution,
shared-source parity and application deployment boundaries.

**Elastic is NOT another MCP implementation.** It is an **intent-driven semantic presentation layer** that decides *what* to show and *how* to execute a user's intent. MCP (Model Context Protocol) is just one adapter among many that Elastic can use to reach a capability — it is not the thing Elastic is, and Elastic does not reimplement the protocol.

The objective of Elastic is:

> **Minimize intelligence cost per successful intent.**

That is the single metric the whole architecture is built around: for every user intent that is successfully fulfilled, spend the least possible amount of model inference (tokens, LLM calls, latency, and dollars). Elastic achieves this by structuring intent, retrieving only the capabilities it needs, disclosing capability detail progressively, and — where a procedure is already known — executing a pre-authored recipe with **zero** model calls.

---

## What Elastic is

Elastic is a layered system that turns a natural-language request into a successful, low-cost execution:

1. **Intent IR** — a structured, schema-validated description of what the user wants (`goal`, `domain`, `action`, `object`, `desired_output`, `context`, `constraints`, and more).
2. **Capability registry** — a declarative catalog of every operation a system can perform, plus an **MCP adapter** that normalizes MCP tools into the same capability model.
3. **Capability retrieval** — keyword and vector strategies that surface only the top-K capabilities relevant to an intent, instead of handing a model the entire catalog.
4. **Progressive disclosure** — capability detail is revealed in three levels (id → summary → full schema), so a model only pays for the detail it actually needs at each stage.
5. **Recipes** — declarative, versioned execution plans that encode a known procedure (e.g. "check balance, then pay"). Executing a recipe requires **no model calls at all**.
6. **Telemetry** — a local-only event bus and recorder that captures per-execution token, latency, and outcome data.
7. **Benchmarking** — three control agents that measure the intelligence cost of each approach head-to-head.

### What Elastic is NOT

- **Not an MCP server or client.** Elastic does not implement the MCP protocol. It *uses* MCP as one adapter among many (REST, gRPC, tool, etc.) to reach capabilities.
- **Not an agent framework.** It does not orchestrate autonomous multi-step LLM agents; it routes intents to capabilities and executes known procedures.
- **Not a learning/optimization layer.** Automatic recipe creation, meta-policy, and recipe optimization are explicitly out of scope.

---

## The three control agents and the benchmark

The benchmark compares three ways of satisfying the same banking intents, all recording **identical** metric fields so results are directly comparable:

| Control | Approach | Model calls | What the model sees |
|---|---|---|---|
| **A — Baseline** | The model is handed the **full** list of every capability description and must select and invoke the right one. | 1 LLM call | All capabilities |
| **B — Retrieval** | Intent → capability retrieval (top-K) → the model sees **only** the top-K descriptions → select → invoke. | 1 LLM call | Top-K capabilities only |
| **C — Recipe** | A hand-written recipe is looked up by intent family and its steps are executed directly against the demo bank. | **0 LLM calls** | Nothing (procedure is pre-encoded) |

All three use the **same** deterministic rule-based "LLM" and the **same** demo-bank capabilities — the only difference is how much of the capability surface the model is shown, and whether a procedure is rediscovered or pre-encoded. This keeps the comparison apples-to-apples.

Each run records: `input_tokens`, `output_tokens`, `total_tokens`, `llm_calls`, `tool_calls`, `retrieval_calls`, `steps`, `wall_clock_latency_ms`, `success`, and `estimated_model_cost`. Cost is estimated from fixed per-token rates (`MODEL_INPUT_RATE = 0.000002`, `MODEL_OUTPUT_RATE = 0.000008` USD/token) in `packages/elastic-bench/metrics.py`.

The expected result: **Control C (recipe) minimizes intelligence cost per successful intent** — zero tokens, zero LLM calls, zero model cost — while Control A pays the most because it must read the entire capability catalog on every intent.

---

## Repository layout

```
elastic-web/
├── apps/demo-bank/            # Mock banking backend + capability manifest (64 caps, 10 domains)
├── packages/
│   ├── intent-ir/             # IntentIR model, JSON schema, rule-based compiler
│   ├── capability-registry/   # Capability model, registry, seed data, MCP adapter
│   ├── capability-retrieval/  # Keyword/vector/semantic-router retrievers, progressive disclosure
│   ├── recipe-schema/         # Recipe + RecipeStep models, RecipeStore (storage + execution)
│   ├── telemetry/             # EventBus + TelemetryRecorder (local-only)
│   └── elastic-bench/         # Control A/B/C agents, shared metrics, benchmark harness
├── docs/                      # Architecture, intent IR, capabilities, recipes, benchmarking, dependency matrix
├── db/                        # Postgres/pgvector schema (migrations, seed)
├── adapters/                  # api / browser / mcp adapter scaffolding
├── recipes/                   # Recipe storage (examples, public)
└── tests/                     # (empty; tests live alongside each package)
```

---

## Setup

The repo uses a Python virtual environment. The venv already exists at `.venv/` (Python 3.12) with the runtime dependencies installed: **pydantic**, **pytest**, and **jsonschema**.

```bash
cd C:/Users/m_jor/Documents/elastic-web

# Create the venv (if it does not already exist)
python -m venv .venv

# Activate it
#   Windows (git-bash / cmd):
source .venv/Scripts/activate
#   macOS / Linux:
source .venv/bin/activate

# Install the runtime dependencies
pip install pydantic pytest jsonschema
```

> Note: the packages are not installed as a distribution. Each package's `conftest.py` adds its sibling package directories to `sys.path` so tests can import them directly. The demo-bank app's tests additionally need the `capability-registry` package on the path (see below).

## Running the tests

The full suite is **309 tests** across the seven packages and two apps. Run everything from the repo root with the capability-registry package on the path (required by the demo-bank tests):

```bash
cd C:/Users/m_jor/Documents/elastic-web
PYTHONPATH="packages/capability-registry" .venv/Scripts/python.exe -m pytest -q
# 309 passed
```

Or run each package independently (each has its own `conftest.py` that wires up sibling imports):

```bash
.venv/Scripts/python.exe -m pytest packages/intent-ir -q            # 15 passed
.venv/Scripts/python.exe -m pytest packages/capability-registry -q   # 29 passed
.venv/Scripts/python.exe -m pytest packages/capability-retrieval -q  # 28 passed
.venv/Scripts/python.exe -m pytest packages/elastic-bench -q         # 169 passed
.venv/Scripts/python.exe -m pytest packages/recipe-schema -q        # 25 passed
.venv/Scripts/python.exe -m pytest packages/telemetry -q            # 12 passed
PYTHONPATH="packages/capability-registry" .venv/Scripts/python.exe -m pytest apps/demo-bank -q  # 13 passed
PYTHONPATH="packages/capability-registry" .venv/Scripts/python.exe -m pytest apps/gateway -q    # 18 passed
```

## Running the benchmark

The three control agents live in `packages/elastic-bench/`. Each exposes a `run(intent)` entry point that returns a metrics dict. See [docs/BENCHMARKING.md](docs/BENCHMARKING.md) for the full methodology and how to run the comparison.

---

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — how the pieces fit together and the data flow from intent to execution.
- [docs/INTENT-IR.md](docs/INTENT-IR.md) — the intent intermediate representation.
- [docs/CAPABILITIES.md](docs/CAPABILITIES.md) — the capability model, registry, manifest, and MCP adapter.
- [docs/RECIPES.md](docs/RECIPES.md) — the recipe schema, store, and the three hand-written recipes.
- [docs/BENCHMARKING.md](docs/BENCHMARKING.md) — the benchmark methodology and cost model.
- [docs/DEPENDENCY-MATRIX.md](docs/DEPENDENCY-MATRIX.md) — upstream dependency audit and licensing.
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) — third-party dependencies and licenses.

## License

Licensed under the **Elastic Public License, Version 2 (EGPL2)** — see [LICENSE](LICENSE).
Attribution is mandatory: redistributions must retain the "Built on Vedaxi Elastic Web" credits (§2).
The proprietary adaptive-intelligence core is excluded from this license (§4).

Credits: [CREDITS.md](CREDITS.md) · Third-party dependencies: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
