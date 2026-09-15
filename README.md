# Vedaxi Elastic

[![CI](https://github.com/luxurylifestyleco/vedaxi-elastic/actions/workflows/ci.yml/badge.svg)](https://github.com/luxurylifestyleco/vedaxi-elastic/actions/workflows/ci.yml)
[![Boundary Check](https://github.com/luxurylifestyleco/vedaxi-elastic/actions/workflows/boundary-check.yml/badge.svg)](https://github.com/luxurylifestyleco/vedaxi-elastic/actions/workflows/boundary-check.yml)

The web normally exposes pages and APIs. **Vedaxi Elastic exposes what a service can do.**

This repository is the **open foundation** for making services intent-addressable and composable. It is a protocol and toolkit — not an application you install and run as a product.

A **capability** describes one useful operation a service can perform.
A **recipe** describes how capabilities compose to accomplish an intent.
An **intent** describes what the user is trying to do — not which endpoint, page, or tool they should invoke.

```
User intent: "Find me a hotel in Dubai"
        ↓
   Intent IR   (structured goal / domain / action / object / constraints)
        ↓
 Capability retrieval   (only the relevant operations, not the whole catalog)
        ↓
 Selected capability or recipe
        ↓
 Execution
        ↓
 Result + telemetry
```

Instead of handing an agent every tool schema on every request, Elastic retrieves the capabilities relevant to the current intent and **progressively discloses** more detail only when needed.

---

## Start here

| I want to… | Go here |
|---|---|
| Run something in five minutes | [docs/QUICKSTART.md](docs/QUICKSTART.md) |
| Understand the ideas | [docs/CONCEPTS.md](docs/CONCEPTS.md) |
| Create a capability | [docs/CAPABILITIES.md](docs/CAPABILITIES.md) |
| Create a recipe | [docs/RECIPE_AUTHORING.md](docs/RECIPE_AUTHORING.md) |
| Connect an existing API | [docs/INTEGRATION_GUIDE.md](docs/INTEGRATION_GUIDE.md) |
| See how the pieces fit | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Reproduce the benchmark | [docs/TESTING_AND_BENCHMARKS.md](docs/TESTING_AND_BENCHMARKS.md) |
| Know what is *not* in this repo | [docs/PUBLIC_PRIVATE_BOUNDARY.md](docs/PUBLIC_PRIVATE_BOUNDARY.md) |

Runnable examples live in [`examples/`](examples/README.md).

---

## What this repo contains

| Package | What it is |
|---|---|
| `packages/intent-ir/` | `IntentIR` model, JSON Schema, rule-based compiler |
| `packages/capability-registry/` | `Capability` model, in-memory registry, demo-bank seed, MCP adapter |
| `packages/capability-retrieval/` | Keyword / vector retrievers and L0/L1/L2 progressive disclosure |
| `packages/recipe-schema/` | `Recipe` / `RecipeStep` models and `RecipeStore` (storage + DAG execution) |
| `packages/recipe-runtime/` | Thin runner wrapper over the store |
| `packages/telemetry/` | Local event bus + in-memory / SQLite / Postgres recorders |
| `packages/elastic-bench/` | Three control agents (full catalog / retrieval / recipe) and the benchmark harness |
| `apps/demo-bank/` | Mock banking backend the examples and Control C execute against |
| `apps/gateway/` | Small HTTP gateway used by `examples/04_full_gateway_roundtrip.py` |

Automatic recipe learning, adaptive execution policy, and related intelligence are **not** in this repository. See [PUBLIC_PRIVATE_BOUNDARY.md](docs/PUBLIC_PRIVATE_BOUNDARY.md).

---

## Setup

Python 3.11+ recommended. Packages are imported from source (they are not published to PyPI).

```bash
git clone https://github.com/luxurylifestyleco/vedaxi-elastic.git
cd vedaxi-elastic
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install pydantic pytest jsonschema
```

Tests add sibling package directories to `sys.path` via each package's `conftest.py`. Demo-bank tests also need `packages/capability-registry` on `PYTHONPATH`.

---

## Tests and examples

From the repository root:

```bash
python -m pytest packages/ -q
python examples/01_compile_intent.py
python examples/02_retrieve_capabilities.py
python examples/03_execute_recipe.py
python examples/04_full_gateway_roundtrip.py
```

See [docs/TESTING_AND_BENCHMARKS.md](docs/TESTING_AND_BENCHMARKS.md) for the three-control benchmark (Controls A, B, C) and how to interpret results. The benchmark does **not** claim universal superiority — it measures intelligence cost on a fixed demo-bank intent set.

---

## License and trademarks

Source code is licensed under the **Apache License, Version 2.0** — see [LICENSE](LICENSE).

The Vedaxi name, logos, and branding are **not** licensed under Apache 2.0. See [TRADEMARKS.md](TRADEMARKS.md).

Credits: [CREDITS.md](CREDITS.md) · Third-party notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
