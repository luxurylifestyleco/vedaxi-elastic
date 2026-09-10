# Elastic Web — HTTP API Gateway

A thin HTTP API gateway for the Elastic Web foundation. It exposes the
foundation packages over HTTP. **All business logic lives in the packages**
under `packages/` and the `demo-bank` app; the gateway controllers only wire
HTTP requests to package functions. No proprietary policy logic lives here.

## Run

```bash
# from the repo root
.venv/Scripts/python.exe apps/gateway/app.py
# or
GATEWAY_PORT=9000 .venv/Scripts/python.exe apps/gateway/app.py
```

Serves on `http://127.0.0.1:8000` by default (override with `GATEWAY_PORT`).

The gateway uses only the Python standard library (`http.server`) — no web
framework dependency is required.

## Endpoint contract

| Method | Path | Body | Returns |
|--------|------|------|---------|
| `POST` | `/intent/compile` | `{"text": str}` | Compiled `IntentIR` dict (via `RuleBasedCompiler`) |
| `POST` | `/capabilities/discover` | `{"intent": str}` | Capability candidates (via `build_retriever("keyword", caps)`) |
| `GET` | `/capabilities/{id}` | — | A capability by id from `build_manifest()` |
| `POST` | `/capabilities/{id}/execute` | `{"args": dict}` | Result of invoking `bank.<id>(**args)` |
| `POST` | `/recipes/resolve` | `{"intent_family": str}` | Resolved recipe from a `RecipeStore` |
| `POST` | `/recipes/{id}/execute` | `{"args": dict}` | Recipe execution results (via `RecipeStore.execute`) |
| `GET` | `/traces/{id}` | — | A telemetry trace by id (from a `TelemetryRecorder`) |
| `GET` | `/health` | — | `{"status": "ok"}` |

### Example

```bash
curl -s -X POST http://127.0.0.1:8000/intent/compile \
  -H 'Content-Type: application/json' \
  -d '{"text": "Get my August bank statement"}'

curl -s -X POST http://127.0.0.1:8000/capabilities/get_balance/execute \
  -H 'Content-Type: application/json' \
  -d '{"args": {"account_id": "ACC-1001"}}'
```

## Tests

```bash
.venv/Scripts/python.exe -m pytest apps/gateway/test_gateway.py -q
```

The tests start the gateway on an ephemeral port in-process and exercise
every endpoint with the standard-library `urllib` client.

## Architecture note

The gateway is intentionally thin. It imports the real packages
(`intent-ir`, `capability-registry`, `capability-retrieval`, `recipe-schema`,
`telemetry`) and the `demo-bank` app, and delegates to their functions. If a
new capability, recipe, or retrieval strategy is added to a package, the
gateway picks it up without code changes.
