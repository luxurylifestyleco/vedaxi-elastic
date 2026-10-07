# Three-plane architecture

Three systems. Three databases. One execution invariant.

VDX is the device and user plane. It can describe its own device without Elastic Web and without the App Store.

The AI App Store / Skill Port is the ecosystem control plane. It publishes, versions, installs, and revokes capability packages. It is not on the hot path.

Elastic Web is the intent and orchestration plane. It understands the meta-schema and evaluates a projection. It does not own device state, the user profile, App Store CRM, or provider credentials.

```
Platform (Elastic Web)
    → capability ecosystem (Skill Port)
    → installed projection (VDX registry)
    → device / runtime (VDX)
    → execution
```

Hot path:

```
USER → VDX → IntentIR projection → Elastic Web
    → local resolution → tool / recipe → adapter → result
```

The App Store is not between VDX and Elastic Web on that path. After install, VDX and Elastic Web operate on the installed contract. If the required capability is already installed, authorized, and in the local registry, execution does not require the App Store to be online.

KGS may relate Capability to Application, Recipe to Capability, and preference to Capability. It is not the database of those records.

A capability is executable only when platform capability, ecosystem capability, installation state, device capability, and current runtime intersect. `packages/federation/intersection.py` evaluates that from a projection. It does not fetch the missing factor.

Ownership:

- VDX: device profile, local registry, user preferences, what this installation can execute now.
- Skill Port: ecosystem registry, packages, authorization, distribution. Not execution.
- Elastic Web: intent, planning, tool selection, recipes, execution contracts, platform version. Not the device database.

This repository implements the Elastic Web side only. It does not add marketplace routes, storage, or UI. See `docs/MARKETPLACE-ASSURANCE-HANDOFF.md`.
