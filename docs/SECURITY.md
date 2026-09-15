# Security (public toolkit)

This document describes **what the public code actually does**. It is not an enterprise security certification.

## Trust boundaries

| Surface | What happens |
|---|---|
| `IntentIR` | Pydantic `extra="forbid"`; required strings must be non-blank |
| `Capability` / `Recipe` | Same: unknown fields rejected; required ids non-blank |
| `RecipeStore.execute` | Runs **your** executor with `capability_id` + `args`. A malicious recipe can invoke whatever the executor allows |
| `DisclosureEngine` | Read-only views over the registry; L2 `execute` does not call backends |
| `MCPAdapter` | Normalizes tool objects into capabilities; empty SDK discovery falls back to **demo** tools |
| Telemetry DB | SQLite or Postgres from env/params; no hardcoded credentials |
| CI `boundary-check.yml` | Fails if proprietary-intelligence patterns appear in this public tree |
| CI secret scan | Heuristic grep; can false-positive on `password=` *code shapes* |

Externally supplied recipes and capabilities are **data**. Validate them with the Pydantic models before execute. Do not point `RecipeStore.execute` at a privileged executor without your own authorization layer — this repo does not provide one.

## Demo bank

`apps/demo-bank/` is a **mock**. It is not a real bank. Do not treat demo payloads as production secrets.

## What we do not claim

- No formal verification of the DAG executor
- No multi-tenant isolation in `RecipeStore` (in-memory)
- No guarantee that progressive disclosure prevents prompt injection against a real LLM (the public selector is rule-based)
- `docs/SECURITY-BASELINE.md` is a dated static scan script output; treat it as historical notes, not a live attestation

For production deployments, run real scanners (`pip-audit`, `bandit`, `gitleaks`, etc.) on **your** fork and executor.
