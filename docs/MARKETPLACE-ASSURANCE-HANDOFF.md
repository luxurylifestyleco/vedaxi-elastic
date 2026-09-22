# Marketplace assurance handoff

Marketplace remains owned and implemented separately. This change only supplies
public assurance contract formats; it adds no marketplace routes, storage or UI.

The marketplace owner should agree on issuer identity and signature verification,
capability version/digest binding, evidence reference access, revocation and expiry
checks before treating CapabilityTrustClaim as verified. Claims are not trust
scores. A listing must distinguish publisher claims from independent assessment.

Permission grants are scoped to a principal, intent, exact capability/version,
action/resource/input digest, expiry and budget. Marketplace listing or purchase
must not be treated as execution approval. Runtime consumers remain responsible
for approval, budget accounting and provider-boundary enforcement.

Checkpoint and evidence schemas support exchange; they do not implement durable
storage, exactly-once execution, external outcome verification or dispute handling.
Receipts must label internal versus independent verification and unsigned status.
Required acceptance-test coverage must match the original intent.

Integration handoff: `packages/assurance-protocol/assurance.py`, `schema.json`, and
`docs/ASSURANCE-PROTOCOL.md`. No private runtime or customer data belongs in these
public artifacts. Marketplace implementation and release remain separate work.