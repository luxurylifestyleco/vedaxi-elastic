# IntentIR contract

Two contracts. They stay two.

Conversational Intent IR V1 (`packages/intent-ir/intent_ir.schema.json`) records incomplete, preferred, excluded, and deictic meaning. `POST /intent/v1` validates it. It does not compile it.

Compiled IntentIR (`packages/intent-ir/schema.json`, `compiler.py`) is the filled execution contract. `POST /intent/compile` produces it. Do not add deictic, preference, or revision fields to it.

The hot-path bridge is a third, smaller document: an execution projection. It is not a third intent language. It carries only what orchestration needs:

- intent: raw, normalized, context
- device: device_id, platform, platform_version, capability_profile_ref, runtime_version
- capabilities: installed_refs, enabled_refs, available_refs, plus per-entry states
- user_context: relevant_preferences, active_goals
- constraints: permissions, network, runtime_limits
- request: correlation_id, timestamp, protocol_version

It must not carry complete user memory, the device database, CRM, analytics, developer records, credentials, or execution history. `execute_locally` rejects those keys.

VDX emits V1 by mapping `SonicIntent`. This repository does not replace that parser. The projection is what VDX sends when it asks Elastic Web to orchestrate. Elastic Web does not call the App Store to fill missing fields.

`POST /capabilities/{id}/execute` keeps the existing demo-bank path when no projection is present. When a projection is present, intersection runs first. A failed intersection returns the failure code and does not invoke the tool.
