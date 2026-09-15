# Telemetry

Public telemetry is a **local event bus plus recorders**. Nothing in these packages phones home.

## Event bus

`packages/telemetry/event_bus.py` — `EventBus.emit` / `subscribe`.

## Event types

`packages/telemetry/events.py` — `EventType`:

- `intent.received`, `intent.compiled`
- `capability.discovery.started`, `capability.candidates`, `capability.selected`
- `recipe.retrieved`, `recipe.started`, `recipe.step.started`
- `tool.called`, `tool.completed`
- `recipe.completed`, `outcome.delivered`, `evaluation.completed`

An `ExecutionEvent` carries `event_type` plus a payload dict.

## In-memory recorder

`TelemetryRecorder` (`packages/telemetry/telemetry.py`) subscribes to the bus and builds a `TelemetryRecord` per `trace_id`:

| Field | Meaning |
|---|---|
| `trace_id` | Correlation id |
| `intent_id`, `recipe_id`, `recipe_version` | If events report them |
| `capability_ids` | Capabilities observed |
| `model`, `provider` | If events report them |
| `tokens` | Map such as prompt / completion / total **as reported** |
| `latency` | Wall-clock **seconds** from first to terminal event |
| `tool_calls` | Ordered `ToolCall` list (`name`, `status`, `duration`) |
| `errors`, `retries`, `outcome` | As observed |
| `started_at`, `completed_at` | Epoch seconds |

`export_json` / `export_to_file` dump records. Token numbers are **whatever events contained** — not independently billed usage.

## Database recorder

`DatabaseTelemetryRecorder` (`packages/telemetry/db_recorder.py`) can persist traces to SQLite (`force_sqlite=True` or default file path) or Postgres (`PG_HOST` / `PG_USER` / `PG_PASSWORD` / `PG_DB`, or a params dict). Passwords come from params or environment — never hardcoded.

SQLite connections use `isolation_level=None` (autocommit). Postgres sets `conn.autocommit = True` after connect.

## Benchmark metrics vs telemetry

The A/B/C harness records a **separate** metrics dict (`packages/elastic-bench/metrics.py`): `input_tokens`, `output_tokens`, `estimated_model_cost` using fixed rates (`MODEL_INPUT_RATE = 0.000002`, `MODEL_OUTPUT_RATE = 0.000008` USD/token). Those costs are **estimates** for comparing controls, not invoices.

## What this repo does not record

Hosted LLM billed usage, proprietary causal graphs, and production operator halt audit trails from the private runtime are outside this public package set.
