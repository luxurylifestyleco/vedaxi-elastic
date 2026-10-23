---
domain: VEDAXI_ELASTIC
---

# Elastic Web — Security Implementation & Engineering Handoff

**Scope:** Elastic Web only. Multi-tenant interoperability gateway for independent customer-owned agents, protocols, tools and business systems.

## Execute from the correct folder

Save this file in the **root of the Elastic Web repository**. Open your coding agent in that repository root and give it this instruction:

> Read `ELASTIC_WEB_SECURITY_IMPLEMENTATION.md` completely. Inspect the actual repository before changing anything. Map existing protocols, agent gateways, identity, routing, connectors, authorization, storage and operations. Implement this specification in incremental phases using the current stack. Do not modify unrelated repositories or invent existing capabilities. Before coding, show a file-level implementation plan and trust-boundary diagram. After each phase, report changed files, real test evidence, latency impact and remaining risks. Never deploy, rotate production credentials or change live policies without explicit approval.

## 1. Non-negotiable boundaries

Elastic Web controls gateway ingress, routing, managed connectors, credential handling, authorization, audit and operations. Customers control their internal agents, models, systems and business rules. Do not claim that Elastic Web can block actions performed outside its routes.

- Authenticate every workload and derive tenant identity from verified credentials, never from agent-supplied text.
- Default-deny unknown agents, actions, resources and destinations.
- Declared tool capabilities are discovery metadata, **not authorization**.
- Distinguish read, write, execute, approve, delete, transmit and delegate permissions.
- Agent messages and tool outputs cannot create privileges or modify policy.
- Delegation must never expand authority.
- Reauthorize consequential actions at the actual execution boundary.
- Cross-tenant requests require caller authorization and provider-side disclosure/operation authorization.
- High-impact actions require bound approvals and authoritative downstream confirmation.
- Fail closed when mandatory security checks or critical audit durability are unavailable.

## 2. Architecture

**Control plane:** Tenant onboarding; agent and connector registration; verified ownership; policy administration; signed versioned policy snapshots; grants; approval routing; revocation; governance; incident management.

**Data plane:** Protocol ingress -> authentication -> canonical request normalization -> task/grant validation -> deterministic local policy evaluation -> managed connector and egress enforcement -> execution -> evidence and response.

Support the protocols **actually implemented** in the repository, potentially MCP, WebMCP, A2A and ACP. Validate exact protocol semantics before implementing adapters. Never silently translate a protocol field into stronger authority.

Use immutable signed policy snapshots distributed to gateway workers. Enforce with a **Policy Decision Point (PDP)** and mandatory **Policy Enforcement Points (PEPs)** at ingress, delegation, cross-tenant routing, connector dispatch and protected execution.

## 3. Eight operational layers

### L1 — Tenant and workload identity

Use tenant-bound identities, appropriate OAuth/OIDC and mTLS, verified issuers/audiences, expiration, key rotation and revocation. Separate tenant admins, security operators, agents, approvers and service workers. Keep connector secrets in a KMS/vault, never in prompts, logs or agent-readable payloads.

### L2 — Agent and capability registry

Register endpoints and capabilities only through authenticated administrators. Verify endpoint ownership; defend against SSRF and DNS rebinding. Version manifests, schemas and destinations. Treat tool descriptions as untrusted; detect schema swaps, name collisions and unreviewed capability changes.

### L3 — Task-scoped authority and delegation

Grants must bind issuer, subject, tenant, audience, task, actions, resources, destinations, data classes, expiration, parent grant, delegation depth, unique ID and policy epoch. Child grants must be subsets of parent authority. Task changes require renewed authorization. Enforce replay and revocation protection.

### L4 — Authorization engine

Build typed deterministic policy decisions: `ALLOW`, `DENY`, `REQUIRE_APPROVAL`, with reason, policy version and obligations. Inputs include authenticated identity, tenant, task, resource, action, destination, classification and constraints. Deny malformed or missing authorization. Bind decisions to canonical operation parameters to prevent time-of-check/time-of-use changes.

### L5 — Prompt injection, data flow and tool isolation

Untrusted webpages, retrieved files, agent messages, tool results and manifests must never be treated as gateway instructions. Validate tool arguments and outbound destinations, restrict egress, protect sensitive data by recipient/classification, constrain redirects and private-network access, enforce payload limits, timeouts and circuit breakers. Prompt filtering is supplementary, not the security boundary.

### L6 — Approvals and transaction integrity

Approval evidence must bind verified approver, tenant, operation ID, exact action, recipient, amount/currency where relevant, resource, canonical arguments digest, expiration and policy version. Forbid self-approval. Prevent replay and double execution with durable idempotency. Enforce aggregate transaction limits atomically, including concurrent and split transactions. For end-to-end guarantees, integrate an enforcement adapter at the destination business system; document bypass risks otherwise.

### L7 — Governance, accountability and audit

Store verified business owner, security owner, technical owner, approver group and incident contact per tenant/agent. Ownership is administrative metadata, not agent self-declaration. Record trace IDs, principals, task/delegation chain, policy decisions, approvals, connector outcomes and evidence. Minimize payload logging, protect integrity and support retention/residency requirements. Provide incident isolation, revocation, evidence export and notification.

### L8 — Reliability and abuse resistance

Per-tenant quotas, fair scheduling, concurrency controls, backpressure, rate limits, denial-of-wallet protection, connector circuit breakers, signed policy rollout/rollback, revocation propagation, failure recovery and tenant isolation. No hidden bypass for internal clients or test agents.

## 4. Canonical request envelope (illustrative)

```json
{
  "request_id": "uuid",
  "tenant_id": "DERIVED_FROM_AUTH",
  "caller_agent_id": "VERIFIED_ID",
  "target_tenant_id": "RESOLVED_TARGET",
  "target_id": "REGISTERED_AGENT_OR_CONNECTOR",
  "task_id": "AUTHORIZED_TASK",
  "delegation_grant_ids": [],
  "protocol": "a2a",
  "action": "invoice.read",
  "resource": "invoice/123",
  "destination_id": "REGISTERED_DESTINATION",
  "arguments_digest": "sha256:...",
  "policy_version": "v1",
  "idempotency_key": "caller-scoped-key",
  "trace_id": "trace-id"
}
```

The server derives trusted fields; a caller cannot override them. The connector must execute exactly the authorized parameters.

## 5. Customer integration and responsibility

Onboarding: verify tenant -> register agent identity/endpoint -> inspect capabilities -> explicitly authorize scopes/resources -> set task/delegation limits -> configure connector credentials and destinations -> assign verified owners -> configure approvals -> run real integration tests -> activate versioned policy.

| Responsibility | Elastic Web | Customer |
|---|---|---|
| Identity | Verify gateway identities and tenant mapping | Provision/revoke their identities |
| Agent behavior | Enforce gateway operations | Secure internal code, models and memory |
| Capabilities | Register and enforce route-level scopes | Declare tools and choose permissions |
| Transactions | Enforce managed connector policy and approval evidence | Define rules and enforce systems outside gateway |
| Incident | Isolate routes, revoke grants, preserve evidence | Respond within customer infrastructure |

Profiles: **Basic** = authenticated, tenant-isolated, read-only discovery and audit; **Standard** = scoped writes, delegation, connectors, approval routing and egress control; **High Assurance** = transaction-bound approvals, durable evidence, authoritative shared limits and downstream enforcement integration. Mandatory identity and isolation are never optional.

## 6. Performance and UX requirements

- Engineering target: **p95 < 10 ms incremental warm-path gateway security processing**, excluding transit, tool execution and human approvals. Benchmark rather than assert achievement.
- No LLM inference in mandatory authorization; compile policies and evaluate locally.
- Cache safe immutable policy context by tenant, principal, task, action, resource, destination and policy epoch; revoke promptly. Do not cache blanket trust.
- Authenticate bounded sessions but authorize each consequential action.
- Parallelize independent checks, pool connections, prewarm adapters; never speculatively execute side effects.
- Routine telemetry may batch asynchronously; critical pre-execution evidence must be durable.
- Missing fresh authorization for high-risk actions means pause/deny, not silent allow.
- Measure p50/p95/p99, throughput, queue lag, revocation delay, denial rates, tenant isolation and downstream outcome verification.

## 7. Adversarial and operational acceptance tests

Use real gateway paths and instrumented downstream systems; simulated passing tests are insufficient.

1. Forged tenant, agent, issuer/audience, expired and revoked credentials.
2. Cross-tenant resource substitution, unauthorized disclosure and recipient changes.
3. Malicious tool manifest, schema swap, prompt injection in tool output.
4. Agent A delegates to B and B attempts broader privileges; multi-hop and replay.
5. Approval thresholds at $9,999/$10,000/$10,001, two $6,000 payments, simultaneous payments, currency normalization.
6. Self-approval, forged approval, expired approval, approver unavailable, changed amount/destination.
7. Duplicate request, ambiguous timeout, partial failure, fake connector success.
8. SSRF, DNS rebinding, redirects, oversized payloads and unauthorized egress.
9. Policy service outage, stale snapshots, revocation race, audit queue saturation.
10. Noisy-neighbor load, quota exhaustion and incident isolation.

For each test record request, authenticated principal, decision, actual downstream effect, trace, latency and reproducible evidence. Independently verify absence of unauthorized side effects.

## 8. Build phases and completion gates

**Phase 0 — Audit:** Inventory actual code, protocols, trust boundaries, deployment and gaps. Deliver threat model and file map before changing behavior.

**Phase 1 — Security boundary:** Verified identities, tenant isolation, canonical envelope, PDP/PEPs and deny-by-default. Gate: unauthorized operations cannot reach downstream systems.

**Phase 2 — Interoperability:** Registry, manifests, scoped grants, delegation and protocol preservation. Gate: no privilege expansion across any supported adapter.

**Phase 3 — Managed execution:** Secret isolation, egress restrictions, approvals, durable operation journal, idempotency and downstream confirmation. Gate: protected side effects require verified authorization.

**Phase 4 — Operations:** Governance owners, incident isolation, quotas, revocation, monitoring and policy rollout. Gate: compromised agent/tenant can be contained and independently verified.

**Phase 5 — Assurance:** Real integration red-team tests, concurrency/fault injection, latency/load benchmarks, rollback drills and residual-risk report.

## 9. Sequential coding-agent work orders

### Work order A — Repository inspection
> Audit the Elastic Web repository. Identify actual protocol ingress paths, tenant identity derivation, routing, connector execution, existing policies, database schemas, audit logging and operational controls. Create a threat model, trust-boundary diagram and precise file-by-file implementation plan. Do not assume a capability exists based on documentation alone.

### Work order B — Enforce identity and policy
> Implement authenticated tenant/workload identity, canonical action envelope, typed deterministic policy engine and mandatory enforcement points across all actual gateway routes and connector execution. Deny unknown actions by default. Demonstrate real negative tests for forged identity, cross-tenant access and unauthorized writes.

### Work order C — Secure protocol interoperability
> Implement registry validation, versioned tool manifests, task-scoped grants and strict delegation subset checks. Preserve authority and identity across each supported protocol adapter. Prove that no protocol translation or multi-hop delegation can increase privileges.

### Work order D — Secure connectors and approvals
> Implement credential isolation, destination/argument restrictions, idempotency, durable sensitive-operation evidence, transaction-bound approvals and authoritative aggregate limits where applicable. Verify real downstream effects and safe recovery from ambiguous timeouts.

### Work order E — Governance and operations
> Implement verified ownership manifests, incident response, revocation propagation, tenant quotas, secure policy distribution, observability and rollout/rollback controls. Add operational runbooks and prove containment in integration tests.

### Work order F — Performance and independent validation
> Benchmark realistic multi-tenant workloads at p50/p95/p99, including cold/warm paths, revocation and faults. Conduct adversarial tests against real gateway and connector boundaries. Optimize without skipping security checks. Report measured overhead, exact evidence and unresolved limitations; do not claim readiness solely from unit-test counts.

## 10. Expected engineering outputs

Create these documents in the repository's existing documentation structure (adapt paths to convention): threat model, trust-boundary map, protocol-security matrix, policy/grant schema, incident runbook, customer onboarding guide, integration test evidence, performance report and deployment/rollback plan.

**Definition of done:** Enforcement occurs at actual controlled boundaries; tenant isolation and task restrictions are demonstrated; approval/replay controls protect real managed operations; customers can configure ownership and policies; revocation and incident containment work; measured performance meets agreed budgets or deviations are disclosed; all residual risks and bypass limits are documented.
