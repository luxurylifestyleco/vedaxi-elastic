# Capabilities

A **capability** is a declarative description of an operation a system can perform on behalf of a user. It is the unit of discovery and routing in Elastic: an intent compiler produces an `IntentIR`, and capability routing matches it against registered capabilities. Capabilities are the surface that retrieval, progressive disclosure, and recipes all operate on.

## Files

| File | Purpose |
|---|---|
| `packages/capability-registry/capability.py` | The `Capability` Pydantic v2 model. |
| `packages/capability-registry/registry.py` | The in-memory `CapabilityRegistry`. |
| `packages/capability-registry/seed.py` | 63 curated demo-bank capabilities across 10 domains. |
| `packages/capability-registry/mcp_adapter.py` | The MCP adapter that normalizes MCP tools into capabilities. |
| `packages/capability-registry/demo_mcp_tools.py` | Four demo MCP tools that stand in for a real MCP server. |
| `apps/demo-bank/manifest.py` | 64 capabilities derived from the demo-bank functions. |
| `apps/demo-bank/bank.py` | The mock banking backend each capability maps to. |

## The `Capability` model

`Capability` is a Pydantic v2 `BaseModel` with `model_config = ConfigDict(extra="forbid")`. It is intentionally generic — it carries no ranking or learning logic. Performance and preference signals are stored as plain data fields and interpreted by downstream consumers.

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Stable unique identifier (e.g. `get_balance`). |
| `name` | `str` | Human-readable display name. |
| `description` | `str` | What the capability does, in plain language. |
| `domain` | `str` | Functional domain (e.g. `accounts`). |
| `inputs` | `Dict[str, Any]` | Structured inputs the capability accepts. Default `{}`. |
| `outputs` | `Dict[str, Any]` | Structured outputs the capability produces. Default `{}`. |
| `permissions` | `List[str]` | Authorization/entitlement requirements. Default `[]`. |
| `provider` | `str` | The system/provider that executes it. Default `"demo-bank"`. |
| `protocol` | `str` | Transport/interface protocol (`rest`, `grpc`, `tool`). Default `"rest"`. |
| `endpoint` | `Optional[str]` | Concrete endpoint or tool reference used to invoke it. |
| `estimated_latency` | `Optional[int]` | Expected latency in milliseconds. |
| `estimated_cost` | `Optional[float]` | Expected cost per invocation (arbitrary units). |
| `historical_success` | `Optional[float]` | Historical success rate, 0.0–1.0. |
| `metadata` | `Dict[str, Any]` | Free-form metadata (tags, version, provenance). Default `{}`. |

`Capability.new_id()` generates a fresh id (UUID4 hex).

## The registry

`CapabilityRegistry` (`registry.py`) is the in-memory source of truth for which capabilities are available for routing. It stores `Capability` objects keyed by `id` and exposes:

- `register(capability)` — add or replace by id.
- `update(capability)` — update an existing capability (raises `KeyError` if absent).
- `remove(capability_id)` — remove by id.
- `list()` — all capabilities in insertion order.
- `search(query, domain=None)` — case-insensitive substring match against `id`, `name`, `description`, and `domain`, with an optional domain filter.
- `get_by_id(capability_id)` — fetch by id.

The registry is deliberately free of ranking or learning logic — selection and scoring are the responsibility of the retrieval layer. It is not internally synchronized; callers that mutate it from multiple threads should guard with their own lock.

## Seed data

`seed.py` provides 63 curated demo-bank capabilities across 10 domains. It is mock data only — no real credentials, accounts, or external systems. The domains and counts:

| Domain | Count |
|---|---|
| accounts | 7 |
| payments | 8 |
| statements/documents | 7 |
| cards | 8 |
| loans | 6 |
| investments | 6 |
| insurance | 5 |
| KYC/profile | 6 |
| support | 5 |
| offers | 5 |
| **Total** | **63** |

`seed_registry(registry)` registers all seed capabilities and returns the count. Running `seed.py` directly prints the summary.

## The demo-bank manifest

`apps/demo-bank/manifest.py` builds a `Capability` for every callable function in `bank.py`, reusing the `Capability` model. The manifest is derived from an explicit table so declared metadata stays in lock-step with implemented functions. It verifies each function actually exists and is callable before building the capability.

The manifest exposes **64 capabilities across 10 domains** (one more than the seed — `statements/documents` has 8, including `get_income_proof`). Each capability carries `provider="demo-bank"`, `protocol="rest"`, an endpoint path, `estimated_latency=60`, `estimated_cost=0.002`, `historical_success=0.98`, and metadata tags.

`build_registry()` returns a `CapabilityRegistry` populated with the manifest. Running `manifest.py` directly prints the summary.

## The MCP adapter

`mcp_adapter.py` bridges Model Context Protocol (MCP) tools into the Elastic capability model. It:

1. **Discovers** tools from a local tool registry (or the MCP SDK if importable).
2. **Normalizes** each tool into a `Capability`:

   | Tool attribute | Capability field |
   |---|---|
   | `tool.name` | `id` (and humanized `name`) |
   | `tool.description` | `description` |
   | `tool.input_schema` | `inputs` (flattened name → type/required/default/enum) |
   | `tool.output_schema` | `outputs` (flattened name → type) |
   | `tool.callable` | `endpoint` (tool reference) |

3. **Invokes** selected tools and records `ExecutionResult`s (tool name, capability id, success, result, error, duration, timestamp).
4. Exposes `list_capabilities()`, `get_capability(id)`, and `execution_log()`.

Tool resolution priority: explicit registry → MCP SDK (if importable) → the local demo registry. The official `mcp` Python SDK is **not required** — if importable, the adapter can discover tools from an `mcp.server.Server`'s registered tools; otherwise it works against the minimal local MCP-like interface. The adapter **never modifies MCP** — it only reads tool metadata and invokes tool callables.

### Demo MCP tools

`demo_mcp_tools.py` provides four tools implemented as plain Python callables with JSON-schema input/output definitions, standing in for tools a real MCP server would serve:

| Tool | Description |
|---|---|
| `get_statement` | Retrieve a bank statement for an account over a period. |
| `make_payment` | Initiate a single payment to a payee or account. |
| `get_balance` | Retrieve the current available and ledger balance for an account. |
| `freeze_card` | Temporarily freeze a card to prevent further transactions. |

Each is an `MCPTool` with `name`, `description`, `input_schema`, `output_schema`, and a `callable`. The `DEMO_TOOL_REGISTRY` list mirrors the shape of the MCP SDK's `Tool` type, so swapping in the real SDK is a thin change.

## How capabilities are used

- **Retrieval** scores capabilities against an `IntentIR` (see `packages/capability-retrieval/`).
- **Progressive disclosure** reveals capability detail in three levels (id → summary → full schema).
- **Recipes** reference capabilities by `capability_id` in their steps.
- **The benchmark** invokes capabilities against the demo-bank functions.

## Tests

`packages/capability-registry` contains 29 tests covering the model, registry, and MCP adapter. `apps/demo-bank` contains 13 tests covering the manifest and the five canonical demo intents.
