---
domain: VEDAXI_ELASTIC
---

# Phase 0 — Security audit

**Date:** 2026-10-23  
**Repo:** `elastic-web`  
**Spec:** `ELASTIC_WEB_SECURITY_IMPLEMENTATION.md`  
**Behavior changed:** none. This is the inspection the spec requires before code.

Elastic Web is a single-process demo gateway. It is not a multi-tenant control plane. There is no tenant record, no issuer, no vault, no signed policy snapshot, and no durable approval journal.

## Trust boundary

```text
Caller
  |  HTTP : intent, capabilities, recipes, traces, health
  |  Identity today: absent, or a JSON X-Principal header, or any Bearer token
  v
Gateway process (apps/gateway/app.py)
  |  PEP: AuthorizationGuard.check, only inside _unified_executor
  |  Default principal if no header: demo_anonymous with approval:bypass
  |  Recipe HTTP execute skips the caller and uses that default
  +-- demo-bank functions (in-process, fake balances)
  +-- RemoteMCPAdapter (stdio subprocess or one HTTP POST)
  +-- A2AAdapter (in-process handler, or JSON-RPC SendMessage/GetTask)
  +-- WebMCPAdapter (custom /capabilities API; not the WebMCP spec)
  +-- DeclarativeWebMCPClient (form POST)
  +-- register_local_capability callables
  v
Whatever those adapters can reach. The gateway does not see actions
taken outside these routes.
```

Trusted fields in the spec's envelope (`tenant_id`, `caller_agent_id`) are not derived. The caller can set `subject`, `permissions`, and `is_admin` in `X-Principal`. A Bearer token that is not the literal `EXPIRED_TOKEN` becomes `token_user_<8 chars>` with read permissions. That is not OIDC.

## What exists

| Spec layer | On disk | Gap |
| --- | --- | --- |
| L1 identity | `adapters/security/auth_guard.py` `SecurityPrincipal`; `app.py` `_extract_principal` | No tenant, issuer, audience, mTLS, or revocation list. Admin is a header flag. |
| L2 registry | `Capability` model, demo manifest, adapter `discover` | Any in-process caller can `register_*`. Tool text is stored as description. No ownership proof, no SSRF check on endpoints. |
| L3 grants | Permission strings on a capability | No grant object, no parent/child subset, no task binding, no replay id. |
| L4 PDP | `AuthorizationGuard.check` → allow or raise | No `REQUIRE_APPROVAL` decision object. Sensitive means `metadata.sensitive`, `external_side_effect`, or id/domain heuristics (`pay`, `freeze`, `delete`). `approval:bypass` skips it. |
| L5 isolation | 1 MB body cap; MCP input-type check; A2A does not stream | Tool output is returned to the caller as data. Nothing treats it as policy. No egress allow-list. |
| L6 approvals | `explicit_approval` boolean on one execute call | Not bound to amount, destination, or argument digest. Recipe execute never passes it. No idempotency store. |
| L7 audit | In-memory `TelemetryRecorder` until `outcome.delivered` | Not durable. Trace GET is unauthenticated. No owners, no incident contact. |
| L8 abuse | None | No quotas, no tenant fair-share, no circuit breaker. |

Protocols actually implemented: MCP stdio, MCP HTTP request-response, A2A v1 JSON-RPC, declarative WebMCP forms, and the custom HTTP capability client. ACP was rejected. Do not add it here.

## Routes and the one PEP

| Route | Auth |
| --- | --- |
| `POST /intent/compile`, `/intent/v1`, `/capabilities/discover`, `GET /capabilities/{id}`, `POST /recipes/resolve`, `GET /traces/{id}`, `GET /health` | None |
| `POST /capabilities/{id}/execute` | `_extract_principal`, then `_unified_executor`. Missing principal falls through to `demo_anonymous`. |
| `POST /recipes/{id}/execute` | Calls `_bank_executor` → `_unified_executor` with principal omitted, so the bypass principal runs the recipe. |

`docs/SECURITY.md` already says this tree does not provide a production authorization layer. That statement is still true.

## File plan (later phases, not started)

Phase 1 touches only the enforcement that already exists. No new service, no vault, no OIDC library.

| File | Change |
| --- | --- |
| `apps/gateway/app.py` | Remove `approval:bypass` from the default principal. Recipe execute must pass the same principal as capability execute. Reject `X-Principal` and raw Bearer as identity. Unknown caller is unauthenticated, not admin. |
| `adapters/security/auth_guard.py` | Keep `check`. Add an explicit decision record (`ALLOW` / `DENY` / `REQUIRE_APPROVAL`) instead of only exceptions. Do not add an LLM. |
| `adapters/security/test_auth_guard.py`, `apps/gateway/test_gateway.py` | Negative tests: forged admin header does not grant admin; cross-permission execute is 403; recipe execute without a real principal does not run a sensitive step. |
| `docs/security/PHASE0_AUDIT.md` | This file. Update it when Phase 1 lands with the test command. |

Phase 2 and later (grants, delegation subset, egress, durable approvals, quotas) wait until Phase 1's negative tests fail closed. Those layers have no table, no tenant id, and no destination registry to attach to. Building them now would invent a control plane the process does not have.

Phase 1 is in the gateway. `X-Principal` is rejected. Bearer tokens work only after `register_workload`. The default `approval:bypass` principal is gone. A caller `approval: true` and an `approval:bypass` permission do not authorize a sensitive execute, and the bank function is not called. Recipe execute uses the same principal as capability execute. `is_admin` does not skip permissions. A capability `metadata.tenant_id` that does not match the principal is denied. Test: `python -m pytest adapters/security/test_auth_guard.py apps/gateway/test_gateway.py -q`.
