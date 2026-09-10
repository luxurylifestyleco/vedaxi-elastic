# Elastic Web — System Architecture

Elastic is an **intent-driven semantic presentation layer**. Its job is to take a user's intent and fulfill it at the lowest possible intelligence cost. This document describes the system's components and how they fit together, from intent to execution.

The objective that shapes every design decision:

> **Minimize intelligence cost per successful intent.**

---

## Component overview

```
                    ┌─────────────────────────────────────────────────────┐
                    │                    INTENT IR                        │
                    │  packages/intent-ir/                                │
                    │  IntentIR model · schema.json · compiler.py          │
                    └───────────────────────┬─────────────────────────────┘
                                            │ structured intent
                                            ▼
                    ┌─────────────────────────────────────────────────────┐
                    │              CAPABILITY REGISTRY                    │
                    │  packages/capability-registry/                      │
                    │  capability.py · registry.py · seed.py              │
                    │  mcp_adapter.py · demo_mcp_tools.py                 │
                    └───────────────────────┬─────────────────────────────┘
                                            │ candidate capabilities
                                            ▼
                    ┌─────────────────────────────────────────────────────┐
                    │            CAPABILITY RETRIEVAL                     │
                    │  packages/capability-retrieval/                     │
                    │  retriever.py · strategies.py · factory.py          │
                    │  disclosure.py (progressive disclosure)             │
                    └───────────────────────┬─────────────────────────────┘
                                            │ top-K capabilities
                                            ▼
                    ┌─────────────────────────────────────────────────────┐
                    │   RECIPE STORAGE / EXECUTION  (Control C path)      │
                    │  packages/recipe-schema/                            │
                    │  recipe.py · store.py                               │
                    └───────────────────────┬─────────────────────────────┘
                                            │ step results
                                            ▼
                    ┌─────────────────────────────────────────────────────┐
                    │                 EXECUTION                            │
                    │  apps/demo-bank/bank.py (mock backend)               │
                    │  MCP adapter invocation (mcp_adapter.py)             │
                    └───────────────────────┬─────────────────────────────┘
                                            │ events
                                            ▼
                    ┌─────────────────────────────────────────────────────┐
                    │                 TELEMETRY                            │
                    │  packages/telemetry/                                │
                    │  event_bus.py · telemetry.py                        │
                    └───────────────────────┬─────────────────────────────┘
                                            │ metrics
                                            ▼
                    ┌─────────────────────────────────────────────────────┐
                    │                 BENCHMARKING                        │
                    │  packages/elastic-bench/                            │
                    │  control_a.py · control_b.py · control_c.py         │
                    │  agent_common.py · metrics.py                      │
                    └─────────────────────────────────────────────────────┘
```

---

## 1. Intent IR (packages/intent-ir)

The **IntentIR** model (`intent_ir.py`) is a Pydantic v2 data contract describing a user's intent. It is the schema-validated output of a compiler and the input to capability routing. Its fields:

- `intent_id` — stable unique identifier.
- `goal` — canonical goal (e.g. `retrieve_financial_document`).
- `domain` — functional domain (e.g. `banking`).
- `action` — verb (e.g. `retrieve`).
- `object` — the entity the action applies to (e.g. `account_statement`).
- `constraints` — structured narrowing (e.g. `period`).
- `context` — ambient context (channel, session, source text).
- `desired_output` — requested artifact (e.g. `pdf`).
- `authority` — authorization/entitlement requirements.
- `disclosure` — data-disclosure/privacy requirements.
- `success_conditions` — explicit conditions for fulfillment.
- `confidence` — compiler confidence, 0.0–1.0.
- `metadata` — free-form (compiler version, provenance).

The JSON schema (`schema.json`) is the canonical, language-neutral definition of this contract (draft 2020-12, `additionalProperties: false`).

The **compiler** (`compiler.py`) exposes a stable `compile(text) -> IntentIR` interface via the abstract `IntentCompiler` class. The current implementation is a deterministic **rule-based** compiler (`RuleBasedCompiler`) that recognizes a small set of financial-document patterns (bank statement, statement, invoice, receipt) and extracts a `period` constraint from month names. The interface is deliberately decoupled so a real LLM compiler can be swapped in later without changing downstream consumers.

## 2. Capability registry (packages/capability-registry)

A **capability** (`capability.py`) is a declarative description of an operation a system can perform — the unit of discovery and routing. Fields include `id`, `name`, `description`, `domain`, `inputs`, `outputs`, `permissions`, `provider`, `protocol`, `endpoint`, and performance signals (`estimated_latency`, `estimated_cost`, `historical_success`) plus free-form `metadata`. The model is intentionally generic: it carries no ranking or learning logic.

The **registry** (`registry.py`) is an in-memory source of truth keyed by capability `id`, with CRUD plus a case-insensitive substring `search(query, domain)`. It is deliberately free of ranking logic — selection is the job of the retrieval layer.

**Seed data** (`seed.py`) provides 63 curated demo-bank capabilities across 10 domains (accounts, payments, statements/documents, cards, loans, investments, insurance, KYC/profile, support, offers). The **demo-bank manifest** (`apps/demo-bank/manifest.py`) builds 64 capabilities — one per callable function in `bank.py` — across the same 10 domains, keeping declared metadata in lock-step with implemented functions.

**MCP adapter** (`mcp_adapter.py`) bridges Model Context Protocol tools into the capability model. It discovers tools (from an explicit registry, the MCP SDK if importable, or the local demo registry), normalizes each into a `Capability` (tool name → id, description → description, input/output schema → inputs/outputs), and invokes tools while recording `ExecutionResult`s. The adapter **never modifies MCP** — it only reads tool metadata and invokes callables. `demo_mcp_tools.py` provides four demo tools (`get_statement`, `make_payment`, `get_balance`, `freeze_card`) that stand in for a real MCP server so the adapter works offline.

## 3. Capability retrieval (packages/capability-retrieval)

Retrieval turns a structured `IntentIR` into a short list of candidate capabilities, so a model never has to read the whole catalog. The swappable contract is `CapabilityRetriever` (`retriever.py`): `retrieve(intent, k=5) -> List[CapabilityCandidate]`, where each candidate carries a `capability_id`, a 0–1 `score`, and `retrieval_latency_ms`. The base class handles latency measurement, sorting, and top-k truncation; subclasses implement `_score`.

Three commodity strategies (`strategies.py`), all implementing the same interface:

- **KeywordRetriever** — scores by term overlap between the intent and each capability's id/name/description/domain.
- **VectorRetriever** — a deterministic, local TF-IDF bag-of-words embedding with cosine similarity. No external embedding API, no pgvector — results are reproducible and dependency-free.
- **SemanticRouterRetriever** — maps the intent's goal/domain/action to a capability domain via a rule table, then scores within the matched domain.

The **factory** (`factory.py`) builds a retriever by strategy name (`keyword`, `vector`, `semantic_router`, plus synonyms) and allows registering custom strategies (e.g. a proprietary ranker) without changing callers.

**Progressive disclosure** (`disclosure.py`) is the cost-control mechanism: never hand a model every full capability schema up front. Instead, disclose in increasing detail:

- **Level 0** `discover(intent)` → capability IDs + categories only.
- **Level 1** `inspect(capability_id)` → short summary (id + name + one-line description).
- **Level 2** `execute(capability_id)` → full capability schema + invocation stub.

The `measure()` helper quantifies the serialized size (characters and estimated tokens at `chars / 4`) at each level, making the token savings directly measurable.

## 4. Recipe storage and execution (packages/recipe-schema)

A **recipe** (`recipe.py`) is a declarative, versioned execution plan that maps an intent family to an ordered set of steps. A `Recipe` carries `recipe_id`, `intent_family`, `version`, `applicability_conditions`, `invariants`, `steps`, `skills`, `adaptation_points`, `checkpoints`, `success_conditions`, `fallbacks`, `freshness_policy`, `metrics`, `status`, and `provenance`. Each `RecipeStep` has `step_id`, `action`, `capability_id`, `args`, `depends_on`, and `checkpoints`. Steps form a **DAG**: the model validator ensures every `depends_on` reference exists and the graph is acyclic, and `topological_order()` (Kahn's algorithm) returns steps in dependency order.

The **store** (`store.py`) is the source of truth for recipes: `create`, `version`, `retrieve`, `execute`, `deprecate`, `retire`. `execute` runs a recipe's steps in topological order, dispatching each to an executor callable `(capability_id, args) -> result`, and emits telemetry events (`recipe.started`, `recipe.step.started`, `tool.called`, `tool.completed`, `recipe.completed`, `execution.failed`) on an `EventBus`. Telemetry is local-only.

## 5. Telemetry (packages/telemetry)

The **EventBus** (`event_bus.py`) is a publish/subscribe bus that decouples event producers (execution stages) from consumers (subscribers). Events carry a `trace_id`, `intent_id`, `timestamp`, and payload. A `ListSubscriber` collects events in memory for tests.

The **TelemetryRecorder** (`telemetry.py`) subscribes to the bus and folds events into per-execution `TelemetryRecord` objects: `trace_id`, `intent_id`, `recipe_id`, `recipe_version`, `capability_ids`, `model`, `provider`, `tokens`, `latency`, `tool_calls`, `errors`, `retries`, `outcome`, and timestamps. Records are finalized on a terminal event (`outcome.delivered` or `execution.failed`) and can be exported as JSON. Telemetry is intentionally local-only — nothing performs network I/O.

## 6. Benchmarking (packages/elastic-bench)

The benchmark compares three control agents that satisfy the same banking intents, all recording identical metric fields. See [docs/BENCHMARKING.md](docs/BENCHMARKING.md) for the full methodology.

---

## Data flow: from intent to execution

**Control A (baseline).** The full capability list is handed to the model. The model reads every description, selects one capability, and invokes it. Cost is highest: the entire catalog is consumed as input tokens on every intent.

```
IntentIR → [LLM sees ALL capabilities] → select → invoke → metrics
```

**Control B (retrieval).** The intent is first run through capability retrieval to get the top-K candidates. The model sees only those K descriptions, selects one, and invokes it. Input tokens drop because the model reads K descriptions instead of all of them.

```
IntentIR → retrieval(top-K) → [LLM sees top-K] → select → invoke → metrics
```

**Control C (recipe).** The intent is resolved to an intent family, which maps to a pre-authored recipe. The recipe's steps are executed directly against the demo bank in DAG order — **no model calls at all**. Tokens, LLM calls, and model cost are all zero.

```
IntentIR → resolve intent family → recipe lookup → execute steps (DAG) → metrics
```

In all three paths, execution results and events flow into telemetry, and each run produces a metrics dict with the ten shared fields. The benchmark's purpose is to show that Control C minimizes intelligence cost per successful intent.

---

## Design principles

- **Decoupled interfaces.** The compiler interface, retriever contract, and executor callable are all swappable — a proprietary ranker or a real LLM compiler can replace the commodity implementations without changing callers.
- **Deterministic and dependency-free.** Retrieval, token estimation, and the rule-based "LLM" are all deterministic, so the benchmark is reproducible and needs no external model API.
- **Local-only telemetry.** Nothing in the telemetry layer performs network I/O or sends data to an external sink.
- **Cost is the metric.** Every design choice — retrieval, progressive disclosure, recipes — exists to reduce the intelligence cost per successful intent.
