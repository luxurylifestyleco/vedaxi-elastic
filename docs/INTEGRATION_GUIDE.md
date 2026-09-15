# Make your service intent-addressable

Walkthrough for an existing HTTP (or tool) API. Uses only public interfaces in this repository.

## Idea

You do not wrap the entire application. You declare the **useful operations**.

Traditional surface:

```
GET  /hotels
POST /booking
GET  /booking/{id}
DELETE /booking/{id}
```

Intent-facing capabilities (conceptual names — you choose `id`s):

```
search_hotels
book_hotel
get_booking
cancel_booking
```

## 1. Declare a capability

`Capability` lives in `packages/capability-registry/capability.py`. Required conceptual fields: `id`, `name`, `description`, `domain`. Invocation metadata: `provider`, `protocol`, `endpoint`.

```python
import sys
sys.path.insert(0, "packages/capability-registry")
from capability import Capability
from registry import CapabilityRegistry

search_hotels = Capability(
    id="search_hotels",
    name="Search hotels",
    description="Find hotels in a city for given stay dates.",
    domain="travel",
    inputs={"city": "string", "check_in": "date", "check_out": "date"},
    outputs={"hotels": "list"},
    provider="my-hotel-service",
    protocol="rest",
    endpoint="GET /hotels",
)

registry = CapabilityRegistry()
registry.register(search_hotels)
print(registry.get_by_id("search_hotels").endpoint)
```

Look at `apps/demo-bank/manifest.py` for many real examples derived from functions in `apps/demo-bank/bank.py`.

## 2. Register and retrieve

```python
import sys
sys.path.insert(0, "packages/intent-ir")
sys.path.insert(0, "packages/capability-registry")
sys.path.insert(0, "packages/capability-retrieval")
from intent_ir import IntentIR
from factory import build_retriever

intent = IntentIR(
    intent_id="demo-1",
    goal="Find a hotel in Dubai",
    domain="travel",
    action="search",
    object="hotels",
    desired_output="json",
)
retriever = build_retriever("keyword", registry.list())
ranked = retriever.retrieve(intent, k=5)
print([c.capability_id for c in ranked])
```

`build_retriever("keyword", capabilities)` is the public default. Other strategy names: see `available_strategies()` in `packages/capability-retrieval/factory.py`.

## 3. Disclose detail only when needed

```python
from disclosure import DisclosureEngine

engine = DisclosureEngine(registry)
print(engine.discover("hotel"))          # L0: id + category
print(engine.inspect("search_hotels"))   # L1: id, name, description
print(engine.execute("search_hotels", {"city": "Dubai"}))  # L2 schema + invocation stub
```

`DisclosureEngine.execute` does **not** call your HTTP API. It returns `provider` / `protocol` / `endpoint` / `arguments` so *your* executor can.

## 4. Optional: a recipe that composes your capabilities

Follow [RECIPE_AUTHORING.md](RECIPE_AUTHORING.md). Point `RecipeStore.execute`'s executor at your client:

```python
def my_executor(capability_id, args):
    cap = registry.get_by_id(capability_id)
    # cap.endpoint / cap.protocol describe how you call your service
    return call_my_api(cap, args)
```

`call_my_api` is **your** code. This repo does not ship a generic HTTP client for arbitrary endpoints.

## 5. Telemetry

Pass an `EventBus` into `RecipeStore(bus=...)`. Subscribe a `TelemetryRecorder` (`packages/telemetry/telemetry.py`) to capture `trace_id`, capabilities, latency, tool calls. See [TELEMETRY.md](TELEMETRY.md).

## MCP

If your tools already speak MCP, `MCPAdapter` (`packages/capability-registry/mcp_adapter.py`) normalizes them into `Capability` objects. If the MCP SDK is importable but no server is configured, discovery falls back to the **demo** tool list so the adapter works offline. Elastic does not implement the MCP protocol itself.

## What this guide does not cover

Hosted production runtime, adaptive recipe learning, and proprietary execution policy are outside this repository ([PUBLIC_PRIVATE_BOUNDARY.md](PUBLIC_PRIVATE_BOUNDARY.md)).
