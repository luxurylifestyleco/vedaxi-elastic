---
domain: VEDAXI_ELASTIC
---

# Elastic Web customer onboarding

## Outcome

A new customer can choose an agent authority profile, choose how tools enter Elastic Web, choose where the agent runtime is hosted, inspect the resulting CRUD boundary, and approve a deterministic setup plan in three customer actions.

The public dashboard is a safe planning surface. It returns `provisioning: demo_plan_only`; it does not create a tenant, issue credentials, connect an IdP, mutate Supabase, or claim that production RLS is active.

## Customer interfaces

1. **Authority profile** — `read_only`, `operations`, or `full_control`. The selected profile is translated into exact CRUD actions from the trusted capability manifest.
2. **Connection and hosting** — choose `demo`, `api`, or `mcp` as the tool source, then choose `managed`, `bring_your_agent`, or `self_hosted` as the runtime model.
3. **Policy preview** — show every declared capability, resource, action, allowed state, and delete approval requirement.
4. **Approval result** — issue a deterministic draft/workspace identifier and a short list of private-control-plane steps.

The customer should not enter secrets into this public page. Identity-provider setup, connector credentials, tenant binding, and production database policy belong in the private control plane.

## Agent hosting contract

- **Managed**: Elastic Web owns the runtime lifecycle; the gateway remains the enforcement point.
- **Bring your agent**: the customer keeps the agent and sends signed, tenant-scoped requests to the Elastic Web gateway.
- **Self-hosted**: the customer runs the gateway/runtime in its environment and connects it to the private control plane for policy distribution and audit.

Every mode must preserve the same enforcement sequence:

`agent request -> tenant/authentication -> CRUD policy -> approval gate -> capability execution -> audit`

Hosting changes placement and operational ownership; it must not weaken the policy boundary.

## API contract

- `POST /api/onboarding/preview` accepts `profile`, `source`, and `host` and returns a deterministic `draft_id`, the capability CRUD plan, and counts.
- `POST /api/onboarding/activate` accepts the same fields plus `confirm: true` and returns a `workspace_id` and private-control-plane next steps.

Production implementation must replace the demo response with an idempotent tenant-provisioning transaction, bind all grants to `tenant_id`, issue short-lived scoped credentials, and run the live RLS/approval acceptance suite before enabling execution.
