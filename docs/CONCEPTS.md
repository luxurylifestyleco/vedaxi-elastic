# Concepts

The web normally exposes pages and APIs. Vedaxi Elastic exposes **what a service can do**.

This page is the vocabulary. Every term maps to code in this repository.

## Intent

What the user is trying to accomplish — not which URL, tool, or endpoint they should call.

Spoken: `"Find me a hotel in Dubai"`

That is still language. Elastic's first job is to turn it into **Intent IR**.

## Intent IR

A structured, schema-validated record of an intent. Implemented as `IntentIR` in `packages/intent-ir/intent_ir.py`. Fields that actually exist:

| Field | Role |
|---|---|
| `intent_id` | Stable id for this instance |
| `goal` | Canonical goal |
| `domain` | Functional domain (e.g. `travel`, `accounts`) |
| `action` | Verb (`search`, `get`, `pay`) |
| `object` | Entity the action applies to |
| `constraints` | Structured narrowing (dates, amounts, cities) |
| `context` | Ambient context |
| `desired_output` | Requested artifact (`json`, `pdf`, …) |
| `authority` | Entitlement requirements |
| `disclosure` | Disclosure preferences |
| `success_conditions` | What "done" means |
| `confidence` | Compiler confidence |
| `metadata` | Free-form extras |

Unknown fields are **rejected** (`extra="forbid"`). Details: [INTENT-IR.md](INTENT-IR.md).

The public compiler is **rule-based** (`packages/intent-ir/compiler.py`). It can later be swapped for an LLM compiler without changing `compile(text) -> IntentIR`.

## Capability

One useful operation a service can perform. Not "the whole application" — one job.

A hotel API might expose `GET /hotels`, `POST /booking`, `DELETE /booking/{id}`. The intent-facing capabilities might be `search_hotels`, `book_hotel`, `cancel_booking`.

Implemented as `Capability` in `packages/capability-registry/capability.py`. A capability has identity (`id`, `name`, `description`, `domain`), `inputs` / `outputs`, `permissions`, and invocation metadata (`provider`, `protocol`, `endpoint`). Performance fields (`estimated_latency`, `estimated_cost`, `historical_success`) are **plain data**, not a ranking engine.

You do not need to describe your entire application. Describe the useful things your service can do.

Details and a first-capability tutorial: [CAPABILITIES.md](CAPABILITIES.md).

## Capability registry

An in-memory catalog: `CapabilityRegistry` in `packages/capability-registry/registry.py`. Operations: `register`, `update`, `remove`, `list`, `search`, `get_by_id`.

Demo data: `packages/capability-registry/seed.py` (curated demo-bank capabilities) and `apps/demo-bank/manifest.py` (capabilities derived from demo-bank functions).

MCP tools can be normalized into the same model via `MCPAdapter` (`packages/capability-registry/mcp_adapter.py`). Elastic is **not** an MCP server; MCP is one adapter among others (`rest`, `grpc`, `tool`, …).

## Capability retrieval

Given an `IntentIR`, return the **top-K** capabilities that match — not the whole catalog.

Implemented in `packages/capability-retrieval/`. `build_retriever(strategy, capabilities)` in `factory.py` constructs a retriever. The default public strategy is **keyword** scoring (`retriever.py`). Vector / semantic-router strategies exist in `strategies.py` when those backends are configured.

This is the difference from "dump every tool schema into the prompt."

## Progressive disclosure

An agent should not always receive every full capability schema.

`DisclosureEngine` in `packages/capability-retrieval/disclosure.py`:

| Level | Method | Payload |
|---|---|---|
| **0** | `discover(intent)` | `{id, category}` only |
| **1** | `inspect(capability_id)` | `{id, name, description}` |
| **2** | `execute(capability_id, arguments)` | Full `Capability` schema + invocation stub (`provider`, `protocol`, `endpoint`, `arguments`) |

Level 2 `execute` returns a **stub describing how to call** the capability. It does not invoke the backend by itself.

`measure(payload)` reports serialized `chars` and estimated `tokens` (`chars // 4`). Those token figures are **estimates**.

## Recipe

A recipe is **not a prompt**.

- A **capability** is one operation.
- A **recipe** is a versioned execution plan: an ordered DAG of steps, each step naming a `capability_id`.

Example intent: `"Get my August statement"`. A recipe might be a single step that calls `get_statement` with a period argument. A payment recipe might be two steps: check balance, then pay — the second depending on the first.

Implemented as `Recipe` / `RecipeStep` in `packages/recipe-schema/recipe.py`. Status values that exist: `draft`, `active`, `deprecated`, `retired`. Automatic recipe *learning* is **out of scope** in this repository (stated in the module docstring).

Authoring tutorial: [RECIPE_AUTHORING.md](RECIPE_AUTHORING.md). Schema: [RECIPES.md](RECIPES.md).

## Execution

`RecipeStore.execute` runs steps in dependency order against an **executor** callable `(capability_id, args) -> result`. Control C (`packages/elastic-bench/control_c.py`) dispatches those ids to demo-bank functions.

Telemetry events emitted during execution: `recipe.started`, `recipe.step.started`, `tool.called`, `tool.completed`, `recipe.completed` (and failure variants). Local only — the store never sends data to an external sink.

Details: [EXECUTION.md](EXECUTION.md).

## Telemetry

`EventBus` + `TelemetryRecorder` (in-memory) and `DatabaseTelemetryRecorder` (SQLite / Postgres) in `packages/telemetry/`.

A `TelemetryRecord` can hold `trace_id`, selected `recipe_id` / `capability_ids`, `tokens`, `latency` (wall-clock seconds), `tool_calls`, `errors`, `retries`, `outcome`. Token maps are whatever events report — this public recorder does **not** invent billed LLM usage.

Details: [TELEMETRY.md](TELEMETRY.md).

## Benchmark (Controls A / B / C)

Same demo-bank intents, identical metric fields, three approaches:

| Control | What the "model" sees | LLM calls in this harness |
|---|---|---|
| **A** | Entire capability catalog | 1 (deterministic stand-in) |
| **B** | Top-K retrieved descriptions | 1 |
| **C** | Nothing — recipe steps run directly | **0** |

The public "LLM" is a **rule-based selector** (`packages/elastic-bench/agent_common.py`), not a hosted model. Cost numbers in the harness are **estimated** from fixed per-token rates in `metrics.py`. This does not prove universal superiority.

How to run it: [TESTING_AND_BENCHMARKS.md](TESTING_AND_BENCHMARKS.md).
