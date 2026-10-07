# Federation adapters

Adapters cross a plane boundary. They do not share a database.

Required set, declared in `packages/federation/adapters.py`:

- CapabilityAdapter
- AuthorizationAdapter
- InstallationAdapter
- DeviceExecutionAdapter
- ToolExecutionAdapter
- SchemaAdapter
- PlatformCompatibilityAdapter

Each contract has version, input schema, output schema, failure schema, timeout, compatibility range, correlation id, and an observability key. The public package declares the contract. The owning plane implements it.

Direction:

- VDX → Skill Port: device identity, platform, supported classes, installed and enabled capability refs, compatibility status. Not user memory, private content, or execution history.
- Skill Port → VDX: capability manifests, schemas, versions, permissions, compatibility, updates, revocations. Not the store database.
- Elastic Web → Skill Port: discovery, schema, version, availability. Cache it. Do not block execution on it.
- Elastic Web → VDX: device capability query, local execution, result. Via the projection and an execution adapter.

Correlation id is required. A timeout is required. A failure schema is required so a plane cannot collapse every miss into one error string.
