# Outcome and Evidence Build Slice

## Decision

Extend the existing `assurance-protocol` boundary. Do not add a second
orchestrator, agent registry, or database.

## What exists

The repository already has versioned intent, permission grants, permission
receipts, step checkpoints, evidence receipts, capability registry and protocol
adapters. Those contracts are source-backed; live deployment and provider proof
remain unverified.

## What this slice adds

- `OutcomeEnvelope` with the protocol-neutral outcome fields and lifecycle states.
- `Delegation` with scoped capabilities/resources, validity, revocation and proof reference.
- `EvidenceRecord` with distinct evidence types and provenance fields.
- `VerificationResult` with structured checks and verdicts.
- Explicit lifecycle transition guards; `COMPLETED` requires sufficient evidence.
- An append-only in-memory ledger reference implementation whose corrections point
  to prior records instead of overwriting them.

## Intentional limits

This is a contract and reference-runtime slice. It does not claim PostgreSQL
persistence, cryptographic signature verification, W3C VC validation, AP2 live
integration, Mission Control UI, or Hermes/AgentOS runtime health. Those require
separate live evidence and approval where external state is involved.

## Verification

Run from `public-repos/vedaxi-elastic`:

```text
python -m pytest packages/assurance-protocol -q
```

The tests cover fail-closed completion, invalid lifecycle transitions, append-only
correction linkage, duplicate detection, and delegation validity.
