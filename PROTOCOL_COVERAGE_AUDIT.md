---
domain: VEDAXI_ELASTIC
---

# Elastic Web — Protocol Coverage and Interoperability Audit

**Document type:** Formal Architecture, Protocol & Interoperability Verification Report  
**Date:** October 17, 2026 (Independent Verification & Audit Update)  
**Scope:** `elastic-web` (Primary Open Source Repository) & `Vedaxi-Elastic-Web-Mastermind` (Private Runtime Engine)  
**Auditor:** Automated Engineering Pair (Antigravity on behalf of Cody)  
**Status:** **LOCAL INTEROPERABILITY PROVEN FOR A2A v1 JSON-RPC, MCP STDIO, AND MCP HTTP REQUEST-RESPONSE. WEBMCP IMPERATIVE API NOT RUN. ACP REJECTED (see ACP_INTEGRATION_DECISION.md).**

---

## A. Executive Verdict & Summary

### 1. Actual Test Results

The 397-test figure below is the earlier sandbox run. It is not the current count.

On October 17, 2026, after the A2A v1, independent MCP, declarative WebMCP, and capability-book composer changes, the suite was re-run:

```text
.\.venv\Scripts\python.exe -m pytest -q --tb=line
405 passed in 13.02s
```

Interpreter: `.venv` Python 3.12.13. One earlier run failed `test_stdio_discovery_validation_timeout_and_cleanup` because a 0.4s timeout also covered process startup. The timeout now applies only to the blocking tool call. The 405 count is the run after that fix.

The table under this heading is the older breakdown. Do not add it up and call it the current suite.

#### Granular Test Suite Breakdown

| Test Suite / Directory | Passed | Scope & Verified Functionality |
| :--- | :---: | :--- |
| `packages/assurance-protocol/test_assurance.py` | 3 | Verifiable hashing, execution receipts, and state transition integrity. |
| `packages/capability-registry/test_registry.py` | 18 | Capability specification, manifest indexing, and schema contracts. |
| `packages/capability-registry/test_mcp_adapter.py` | 11 | In-process Python MCP tool normalization and callable invocation. |
| `packages/capability-retrieval/test_retrieval.py` | 17 | Keyword, Vector TF-IDF, and Semantic Router capability retrieval. |
| `packages/capability-retrieval/test_disclosure.py` | 12 | Progressive disclosure levels (L0 name/domain, L1 schema, L2 full docs). |
| `packages/elastic-bench/*` | 167 | Performance benchmarks, failure injection, controls A/B/C, and telemetry. |
| `packages/intent-ir/test_intent_ir.py` | 17 | Compiled IntentIR Pydantic models, JSON schema validation, compiler rules. |
| `packages/intent-ir/test_intent_ir_v1.py` | 25 | Conversational IntentIR V1 draft schema validation and error reporting. |
| `packages/intent-ir/test_decision_state.py` | 21 | State machine transitions across intent compilation and decision cycles. |
| `packages/recipe-schema/test_recipe.py` | 26 | Declarative recipe DAG schema, Kahn's topological sort, dependency cycles. |
| `packages/telemetry/*` | 21 | EventBus emissions, SQLite recorder, duration tracking, credential safety. |
| `apps/dashboard/test_dashboard.py` | 6 | Dashboard metric rendering and telemetry aggregation. |
| `apps/demo-bank/test_bank.py` | 13 | Demo financial banking capabilities (balance, transfer, freeze, statement). |
| `apps/gateway/test_gateway.py` | 22 | Gateway HTTP REST routing, 1 MB payload bounding, error handling. |
| `adapters/mcp/test_remote_mcp.py` | 3 | Remote MCP stdio subprocess JSON-RPC 2.0 handshake, list, call, timeouts. |
| `adapters/a2a/test_a2a.py` | 3 | A2A agent card registration, task lifecycle dispatch, independent agent delegation. |
| `adapters/webmcp/test_webmcp.py` | 2 | WebMCP HTTP GET capability discovery, POST execution, offline fallback. |
| `adapters/security/test_auth_guard.py` | 6 | Invocation-time permissions, token expiry, sensitive approval gates, admin bypass. |
| `tests/test_interoperability_e2e.py` | 2 | Multi-protocol end-to-end intent-to-execution workflow + authorization denial. |
| **Total** | **397** | **100% Pass Rate across all packages, apps, adapters, and tests.** |

---

## B. Evidence of the End-to-End Execution Path

The end-to-end test (`tests/test_interoperability_e2e.py`) exercises a complete intent-to-execution pipeline connecting all newly implemented adapters through the existing Elastic Web runtime contracts:

```
[1. User Intent Intake]
       │ Text: "bank statement for march" (or multi-step payment intent)
       ▼
[2. IntentIR Compilation]
       │ RuleBasedCompiler().compile() emits IntentIR:
       │ {goal: "retrieve_financial_document", domain: "banking", constraints: {"period": "march"}}
       ▼
[3. Protocol Adapters Registration]
       │ Adapters normalize tools into standard Capability models:
       │  - WebMCPAdapter discovers "webmcp.get_balance" via GET /capabilities/get_balance
       │  - A2AAdapter registers "a2a.agent.external_risk_auditor.compliance_audit" via AgentCard
       │  - RemoteMCPAdapter discovers "make_payment" via stdio JSON-RPC tools/list
       │ Registered into apps/gateway/app.py (_DYNAMIC_CAPABILITIES)
       ▼
[4. Multi-Protocol DAG Formulation]
       │ RecipeStore creates Recipe "recipe.cross_protocol_transfer" with 3 topological steps:
       │   Step 1: webmcp.get_balance [WebMCP]
       │   Step 2: a2a.agent.external_risk_auditor.compliance_audit (depends on Step 1) [A2A]
       │   Step 3: make_payment (depends on Step 2) [Remote MCP Stdio]
       ▼
[5. Topological Execution & Unified Routing]
       │ RecipeStore.execute() iterates through topological order:
       │ For each step -> calls gateway _bank_executor -> _unified_executor:
       │   a. Enforces AuthorizationGuard.check(cap, principal)
       │   b. WebMCP Step: HTTP POST http://127.0.0.1:<port>/capabilities/get_balance/execute
       │   c. A2A Step: submit_task() -> IndependentComplianceAgent.handle_task() -> returns audit token
       │   d. Remote MCP Step: writes JSON-RPC line to Python subprocess stdin -> reads response
       ▼
[6. Result Verification & Telemetry Finalization]
       │ All step results validated against explicit domain invariants:
       │   - Step 1: available_balance == 15000.0 USD
       │   - Step 2: approved == True, audit_token has "AUDIT-SIG-VALID"
       │   - Step 3: status == "pending", amount == 4500.0 USD
       │ Telemetry trace recorded: 3 tool calls, zero credential leakage, event "outcome.delivered"
```

---

## C. Execution Environment Matrix

To maintain strict audit integrity, each test and integration must be categorized by its true runtime environment:

| Integration / Component | Test File | Environment Type | Environment Details |
| :--- | :--- | :--- | :--- |
| **Remote MCP (Stdio)** | `adapters/mcp/test_remote_mcp.py`<br>`tests/test_interoperability_e2e.py` | **Local Subprocess (Real IPC)** | Spawns a real separate Python OS process (`examples/sample_mcp_server.py`) using `subprocess.Popen`. Uses real OS `stdin`/`stdout`/`stderr` pipes and real JSON-RPC 2.0 line serialization. |
| **Remote MCP (HTTP)** | `adapters/mcp/remote_mcp.py` | **Unit / Mock HTTP** | Uses standard `urllib.request` POST requests. Evaluates status codes, timeouts, and JSON-RPC error responses. |
| **A2A Agent Delegation** | `adapters/a2a/test_a2a.py`<br>`tests/test_interoperability_e2e.py` | **In-Memory Fixture Agent** | Interacts with `ComplianceAuditAgent` and `IndependentComplianceAgent`. Executes real task lifecycle states (`submitted` $\rightarrow$ `working` $\rightarrow$ `completed`), but runs in-process via Python protocol/callable rather than over a remote network host. |
| **WebMCP Web Capabilities** | `adapters/webmcp/test_webmcp.py`<br>`tests/test_interoperability_e2e.py` | **Local Test Server (Real HTTP)** | Runs an ephemeral `ThreadingHTTPServer` bound to `127.0.0.1` on an OS-assigned dynamic port. Dispatches real TCP/HTTP `GET` and `POST` calls, returning simulated banking data. |
| **AuthorizationGuard** | `adapters/security/test_auth_guard.py`<br>`apps/gateway/test_gateway.py` | **In-Memory Guard Unit** | Evaluates real capability permissions against caller principals, timestamps, token expiration, and sensitive flags. |
| **Gateway HTTP API** | `apps/gateway/test_gateway.py` | **Local Test Server (Real HTTP)** | Runs `ThreadingHTTPServer` on `127.0.0.1` testing 9 REST endpoints with simulated HTTP requests and payload limits. |
| **External Live API** | `Vedaxi-Elastic-Web-Mastermind/apps/runtime/provider.py` | **Genuine Live External Service** | Makes outbound HTTPS requests to Crossref API (`https://api.crossref.org/works`) with TLS verification and 512 KB payload bounding. |
| **External Domain Redirect** | Cloudflare Workers (`skillport-redirect`) | **Genuine Live External Service** | Live Cloudflare Edge Worker routing `skillport.vedaxi.com` and `skillsport.vedaxi.com` via HTTP 302 to `https://skills.syed-hasan.com/`. |

---

## D. Standards-Conformance Findings

### 1. Model Context Protocol (MCP)
* **Specification Baseline:** Model Context Protocol (Anthropic/Open Standard, Protocol Version `2024-11-05`).
* **Conformance Status:** **Conforms to JSON-RPC 2.0 Stdio Specification.**
  - Properly executes the MCP initialization handshake: sends `initialize` (with `protocolVersion`, `capabilities.tools`, `clientInfo`), validates server response, and sends `notifications/initialized`.
  - Discovers tools dynamically via `tools/list` and parses the standard MCP `inputSchema` (JSON Schema object properties and required fields) into Elastic Web `Capability.inputs`.
  - Dispatches calls via `tools/call` and unpacks the standard `{content: [{"type": "text", "text": ...}], isError: bool}` response structure.
  - Implements process cleanup with graceful `terminate()`, 1-second timeout wait, and fallback `kill()`.
* **Transport Distinction:**
  - **Stdio:** Fully supported, tested, and verified via separate subprocesses.
  - **HTTP Request-Response:** Implemented and tested via HTTP POST JSON-RPC.
  - **Streamable HTTP / SSE (Server-Sent Events):** **NOT implemented.** Bidirectional streaming subscriptions are not currently supported.

### 2. Agent-to-Agent (A2A) Delegation
* **Specification Baseline:** A2A protocol v1 JSON-RPC (`SendMessage`, `GetTask`, `/.well-known/agent-card.json`). Task states use the proto JSON names (`TASK_STATE_SUBMITTED`, `TASK_STATE_WORKING`, `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`).
* **Conformance Status:** **JSON-RPC request-response against a separate process. Streaming is not implemented.**
  - `examples/independent_a2a_agent.py` does not import the adapter. The test discovers the card, submits a task, observes `working`, then reads the completed artifact.
  - An unknown skill ends in `TASK_STATE_FAILED`.
  - `SendStreamingMessage` is rejected by that agent with "streaming is not implemented".
  - The older in-process `handle_task` path is still used by `test_a2a.py` and the bank end-to-end test. That path is not A2A v1 on the wire.
* **Limitations:**
  - No agent on the public internet was called. OAuth for A2A is not implemented.

### 3. WebMCP (Web-Native Capabilities)
* **Specification Baseline:** WebMCP is the browser document API. Declarative tools are HTML forms with `toolname` and `tooldescription`. Imperative tools are `document.modelContext.registerTool`. Chrome's early preview needs Chromium and `#enable-webmcp-testing`.
* **Conformance Status:** **Declarative form discovery and HTTP form submit only. The imperative API was not run.**
  - `WebMCPAdapter` talks to `GET /capabilities/{id}` and `POST /capabilities/{id}/execute`. That is a private HTTP API. Discovered capabilities are marked `specification: custom-http-capability-api` and `webmcp_spec: false`.
  - `DeclarativeWebMCPClient` parses those form attributes and submits the form. `examples/company_directory_server.py` is the page. The prospect scenario uses it.
* **Blocker:**
  - No browser with `document.modelContext` was started. Form submit from Python is not that browser mediation. Do not call the custom HTTP client WebMCP.

### 4. Authorization & Safety Enforcement
* **Specification Baseline:** Capability-Based Security and Role-Based Access Control (RBAC).
* **Conformance Status:** **Enforced at Invocation Time.**
  - Permissions are not merely decorative metadata; `AuthorizationGuard.check()` actively gates every call in `_unified_executor`.
  - Unauthenticated calls to protected capabilities are rejected (HTTP 401).
  - Expired tokens are rejected (HTTP 401).
  - Callers missing required capability permissions are denied (HTTP 403).
  - High-risk operations (financial transactions, card freeze, account deletion, sensitive flags) require explicit approval (`explicit_approval=True` or `approval:bypass`), preventing unauthorized external side effects.

---

## E. Explicit Separation of Functionality

To avoid conflating testbed success with public internet interoperability, functionality is strictly separated into three categories:

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 1. MOCKED / FIXTURE DATA (Sandboxed Demo Entities)                                              │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ • Banking account balances ($15,000.00 / $8,750.50).                                           │
│ • Sample MCP Server tool implementations in examples/sample_mcp_server.py.                    │
│ • In-memory IndependentComplianceAgent AML/KYC rule evaluation.                                │
│ • No real bank accounts, real credit cards, or customer money was touched.                     │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 2. LOCALLY INTEGRATED (Real Protocols, Transports & Runtime Plumbing)                          │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ • Real OS Subprocess execution over stdin/stdout pipes for Remote MCP JSON-RPC 2.0.            │
│ • Real TCP localhost socket binding and HTTP GET/POST handling for WebMCP and Gateway REST.    │
│ • Real topological DAG dependency resolution (Kahn's algorithm) in RecipeStore.                │
│ • Real runtime entitlement and token expiration enforcement in AuthorizationGuard.             │
│ • Real event-driven telemetry capture and hashing across EventBus and TelemetryRecorder.       │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 3. EXTERNALLY VERIFIED (Live Internet Services)                                                │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ • Live Cloudflare Worker routing: skillport.vedaxi.com & skillsport.vedaxi.com -> 302 Found.  │
│ • Live Crossref Academic Search: https://api.crossref.org/works (Mastermind runtime).          │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## F. Protocol Coverage Matrix

| Protocol / Interface | Role in Current Product | Status | Implementation & Registration Evidence | Tests & Results | Live / Demo Evidence | Gaps & Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **IntentIR** | Common contract for intent representation | **IMPLEMENTED_TESTED** | `packages/intent-ir/intent_ir.py`, `intent_ir_v1.py`, `compiler.py`. Registered in `apps/gateway/app.py:POST /intent/compile`. | **63 tests passed**. | Verified in gateway live responses. | Rule-based compilation bridges conversational input to formal IntentIR. |
| **A2A (Agent-to-Agent)** | Task delegation between independent agents | **IMPLEMENTED_TESTED** | `adapters/a2a/a2a_adapter.py`. In-process `handle_task` remains. HTTP uses A2A v1 `/.well-known/agent-card.json`, JSON-RPC `SendMessage` and `GetTask`. | `adapters/a2a/test_a2a.py` and `test_a2a_http.py`, plus `tests/test_prospect_outreach.py`. | Separate process `examples/independent_a2a_agent.py`. It does not import the adapter. States observed: submitted, working, completed, failed. | `SendStreamingMessage` returns "streaming is not implemented". No public-internet agent. |
| **MCP (Model Context Protocol)** | Tool discovery, schema normalization, execution | **IMPLEMENTED_TESTED** | Local: `packages/capability-registry/mcp_adapter.py`. Remote: `adapters/mcp/remote_mcp.py`. Stdio, and HTTP as one JSON-RPC POST and one JSON body. | `test_mcp_adapter.py`, `test_remote_mcp.py`, `adapters/mcp/test_independent_mcp.py`. | Separate process `examples/independent_mcp_server.py` (stdio and `--http`). It does not import the adapter. SSE-only `Accept` gets HTTP 406. | Streamable HTTP and SSE are not implemented. A stdio timeout can leave the pipe unread; the client then closes the process. |
| **WebMCP** | Browser document tools (`document.modelContext` or `<form toolname tooldescription>`) | **PARTIAL** | `adapters/webmcp/webmcp_adapter.py` is a custom HTTP capability client (`specification: custom-http-capability-api`). It is not WebMCP. `adapters/webmcp/declarative.py` reads declarative form attributes and submits the form. | `test_webmcp.py` covers the custom client. `tests/test_prospect_outreach.py` covers the form. | `examples/company_directory_server.py` serves one declarative form. | Imperative `document.modelContext.registerTool` was not executed. No Chromium session with `#enable-webmcp-testing` was run. |
| **AuthorizationGuard** | Invocation-time security & entitlement enforcement | **IMPLEMENTED_TESTED** | `adapters/security/auth_guard.py` (`AuthorizationGuard`, `SecurityPrincipal`). Enforced in `apps/gateway/app.py:_unified_executor`. | **6 tests passed** in `test_auth_guard.py` + verified in E2E proof. | Blocks unauthorized and sensitive unapproved calls at runtime. | Reuses `Capability.permissions`; dynamic OAuth refresh flows remain upstream. |
| **HTTP / REST & OpenAPI** | Conventional API integration & gateway | **LIVE_VERIFIED** | `apps/gateway/app.py` (9 endpoints), `apps/runtime/provider.py` (Crossref API). | **22 tests passed** in `test_gateway.py`. | **Live verified** against `https://api.crossref.org/works` in Render runtime. | REST endpoints fully functional; body bounded at 1 MB. |
| **ACP (Agent Client Protocol)** | Hermes editor-host session (`hermes acp`). Not A2A. | **REJECTED** | No adapter. Decision in `ACP_INTEGRATION_DECISION.md`. | Not implemented. Docs compared with A2A, MCP, and HTTP. | None. No Hermes process was started. | Does not publish book capabilities. Streaming and host-answered approvals are Hermes editor UX. Recipes return one result per step; `AuthorizationGuard` already gates the call. |
| **WebSocket** | Real-time bidirectional event transport | **DOCUMENTED_ONLY** | Mentioned in `docs/research-upgrade/COMPLETION_MATRIX.md` as planned 3D telemetry pipe. | None. | None. | Synchronous HTTP REST and EventBus satisfy current needs. |
| **Server-Sent Events (SSE)** | Event streaming to clients | **DOCUMENTED_ONLY** | Documented in `docs/DEPENDENCY-MATRIX.md`. | None. | None. | Gateway responses are standard JSON payloads. |
| **OAuth 2.0 / OIDC** | Delegated authorization & consent | **DOCUMENTED_ONLY** | Referenced in `scripts/security_baseline.py`. Token validity checked by `AuthorizationGuard`. | Verified via `SecurityPrincipal` token validation. | None. | Dynamic browser PKCE handshake and token refresh deferred to upstream gateway. |
| **Browser / DOM Automation** | Fallback for web capabilities lacking APIs | **DOCUMENTED_ONLY** | Investigated in Phase 14 (`PH14-DELTA.md`: *Browserbase/Stagehand study-only*). | None. | None. | WebMCP and structured REST APIs are prioritized over brittle browser scraping. |
| **H2A (Human-to-Agent)** | User interaction protocol | **NOT_FOUND** | Not defined as a separate protocol; mediated by IntentIR V1 and Web UI. | None. | None. | Covered conceptually by IntentIR V1. |
| **UDP** | Low-latency datagram transport | **NOT_APPLICABLE** | No requirements or use cases in project scope. | None. | None. | HTTP/TCP satisfies all requirements. |
| **Demo Bank Local Adapter** | In-process execution of core financial capabilities | **LIVE_VERIFIED** | `apps/demo-bank/bank.py`, `manifest.py`, `apps/gateway/app.py:_bank_executor`. | **13 tests passed** in `test_bank.py`. | Powers the primary benchmark controls (Control A, B, C). | Operates in-memory; reliable baseline for benchmarking. |
| **Assurance & Integrity Protocol** | Result verification, hashing, and audit ledger | **IMPLEMENTED_TESTED** | `packages/assurance-protocol/test_assurance.py`, `Vedaxi-Elastic-Web-Mastermind/apps/runtime/assurance_runtime.py`. | **3 tests passed** in `test_assurance.py`. | Generates tamper-evident receipts and contracts in runtime. | Ensures outputs are cryptographically verifiable. |

---

## G. Remaining Limitations and Smallest Necessary Next Steps

| Limitation | Impact | Smallest Necessary Next Step |
| :--- | :--- | :--- |
| **1. WebMCP imperative API** | Declarative form submit is tested. Browser `document.modelContext` is not. | Run the company-directory page in Chromium with WebMCP enabled and confirm the tool list and a form submit from the browser, not from `urllib`. |
| **2. Streamable HTTP / SSE for MCP** | Servers that only speak `text/event-stream` are refused (HTTP 406 on the test server). | Do not claim Streamable HTTP. Add it only when a real MCP server in this product requires it. |
| **3. Automated OAuth Token Refresh** | Expired tokens raise `CredentialsExpiredError`. There is no refresh grant. | Leave it. No product flow needs a live OAuth refresh yet. |
| **4. Hard-coded bank recipe** | `tests/test_interoperability_e2e.py` still builds its steps in Python. The prospect scenario does not. | Leave the bank test as a regression. New intents go through `compose_recipe` and capability metadata (`intent_goals`, `stage`, `binds`). |

---

## H. Final Verification Verdict

> **FINAL VERDICT: ARCHITECTURALLY GENUINE INTEROPERABILITY PROVEN IN A CONTROLLED LOCAL TESTBED; NOT A CLAIM OF UNIVERSAL INTERNET PROTOCOL COMPATIBILITY.**
>
> 1. **What the 2026-10-17 re-run proves:** The prospect intent is compiled to `prepare_outreach` with no embedded steps. `KeywordRetriever` drops `get_balance`. `compose_recipe` orders book capabilities by `stage` and withholds `send_outreach`. Execution uses a separate MCP stdio server, a separate A2A v1 process, and a declarative WebMCP form. The report lists Ben Ortiz and Cleo Park for human approval, leaves Ava Shah clear, sets `contact_sent` false, and does not record a send. `AuthorizationGuard` denies `send_outreach` without explicit approval. With approval, the local function still raises `refusing to contact prospects`. Telemetry on that trace has four tool calls and no errors.
> 2. **What is not claimed:** Streamable HTTP, MCP SSE, A2A streaming, imperative WebMCP, OAuth refresh, and any public-internet agent or website. The older bank end-to-end test still hand-builds its recipe and still uses the in-process A2A object and the custom HTTP capability client.
