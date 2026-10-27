---
domain: VEDAXI_ELASTIC
---

# CRUD Control Policy

Elastic capabilities may declare a resource operation in capability metadata:

```json
{
  "crud_resource": "support",
  "crud_action": "create"
}
```

Allowed actions are exactly `create`, `read`, `update`, and `delete`. The
gateway evaluates this declaration at invocation time through the existing
`AuthorizationGuard`; it is not a second policy engine.

Permission requirements are:

- `support:create`, `support:read`, `support:update`, or `support:delete` for
  exact grants;
- legacy `support:write` remains a mutation wildcard for create/update/delete
  only, so existing callers do not break during migration;
- `support:write` never grants read access;
- tenant binding, expiry, sensitive-action approval, and default-deny behavior
  still apply;
- malformed CRUD metadata is rejected before invocation.

New dynamic MCP, A2A, and WebMCP capabilities that represent a CRUD resource
must declare `crud_resource` and `crud_action` in their trusted server-side
metadata. Caller-supplied metadata is not accepted as authorization.

The demo-bank manifest now emits CRUD metadata for its capabilities. Existing
resource-level permissions remain in place until all callers migrate to exact
action grants.

Required regression cases:

1. exact read grant allows read;
2. write grant cannot read;
3. exact create/update/delete grants allow the matching operation only;
4. legacy write allows mutations only;
5. malformed action fails closed;
6. cross-tenant, expired, unauthenticated, and sensitive actions remain denied;
7. recipe execution and direct capability execution use the same guard.
