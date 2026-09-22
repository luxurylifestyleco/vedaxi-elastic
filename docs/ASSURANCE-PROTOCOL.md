# Assurance protocol 1.0

These opt-in sidecar contracts bind existing intent, capability, execution and
step IDs. Existing IntentIR, Capability and RecipeStep formats are unchanged.
Import `assurance` from `packages/assurance-protocol` (Pydantic v2). JSON Schema
is generated from `AssuranceDocument.model_json_schema()`; application validators
also enforce aggregate statuses, unique test IDs, time ordering and completed
checkpoint evidence, which JSON Schema alone does not fully express.

Five controls are represented:

1. AssuranceIntent: explicit goal/end state, constraints, budget, risk ceiling,
   approval requirements and evaluator-named acceptance tests. Missing monetary
   budget means unspecified, not zero spending. No evaluator code is executed.
2. CapabilityTrustClaim: issuer/publisher, version/digest, evidence, validity and
   signature reference. It is a claim, never a trust certification.
3. PermissionGrant and PermissionReceipt: principal, exact capability/version,
   action/resource/input digest, expiry, budget and policy decision references.
4. StepCheckpoint: stable intent/execution/step, idempotency key and input digest,
   attempt/state, prior checkpoint and output/evidence references.
5. EvidenceReceipt: input/output/checkpoint digests and evaluator results. The
   default verification scope is internal, and unsigned receipts retain a null
   signature reference. Sources can reference ledger traces for failed outcomes.

A consumer must authenticate issuers, verify signatures, match every binding,
check expiry/revocation, enforce budgets and approvals at the provider boundary,
run all required intent acceptance tests, and persist checkpoint/side-effect
transitions atomically. Schema validity cannot prove any of these controls.
A repeated idempotency key with changed input must be rejected. An indeterminate
external write must be reconciled rather than automatically retried. Consumers
must check receipt test IDs exactly cover the intent tests before accepting PASS.
Never resolve arbitrary evidence references or execute evaluator names as code.
Use defined canonical serialization before hashing; digest syntax validation
alone does not establish content integrity or issuer identity.

Run `python -m pytest packages/assurance-protocol -q`.
Regenerate schema from this directory with:
`python -c "import json; from assurance import AssuranceDocument; open('schema.json','w').write(json.dumps(AssuranceDocument.model_json_schema(),indent=2)+'\\n')"`.

Marketplace implementation belongs to its separate owner. No marketplace,
payment processing, private execution policy, trust score or signing service is
implemented by these contracts.