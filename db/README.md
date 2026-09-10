# Elastic Web — Database

Local PostgreSQL infrastructure for the Elastic Web project.

## Quick start

```bash
./scripts/db-init.sh     # create DB (if missing) + apply migrations + load seed
./scripts/db-health.sh   # verify connectivity, pgvector, and all 8 tables
```

Both scripts are idempotent and safe to re-run.

## Requirements

- PostgreSQL 16 running on `localhost:5432` (service `postgresql-x64-16`).
- `psql` at `C:/Program Files/PostgreSQL/16/bin/psql.exe` (override with `PSQL` env var).
- Default credentials: `postgres` / `postgres` (override with `PGUSER` / `PGPASSWORD`).

## Schema

Eight tables, using JSONB generously for evolving Elastic structures (no over-normalization):

| Table | Purpose |
|-------|---------|
| `capabilities` | Named, versioned units of functionality (e.g. `bank.transfer`) |
| `intent_examples` | Sample utterances mapped to a capability + extracted parameters |
| `recipes` | Reusable, versioned plans (current version pointer) |
| `recipe_versions` | Immutable snapshots of a recipe's step-graph definition |
| `execution_traces` | One row per recipe execution run (lifecycle + outcome) |
| `execution_steps` | Individual steps within a trace (nested via `parent_step_id`) |
| `evaluations` | Results of evaluating a capability/recipe/intent |
| `benchmark_runs` | Benchmark suite runs + aggregate results |

Flexible payloads (`schema`, `metadata`, `parameters`, `definition`, `input`, `output`, `score`, `results`, ...) are JSONB, indexed with GIN where queried.

## pgvector status

> **pgvector is NOT installed on this server.**

`pg_available_extensions` returns 0 rows for `vector`, so the extension cannot be
enabled. The migration is **tolerant**: it attempts `CREATE EXTENSION IF NOT EXISTS
vector;` inside a `DO` block that catches failure and logs a notice instead of
aborting. Embeddings are therefore stored as **JSONB arrays** so the schema works
with or without pgvector.

To enable real vector columns later:
1. Install pgvector for PostgreSQL 16 (e.g. via the EDB installer or `make && make install`).
2. Re-run `./scripts/db-init.sh` — the migration will then enable the extension.
3. Add `vector` columns / `<=>` operators as needed.

Do **not** attempt to install pgvector from source into this setup unless you
explicitly want to; the current schema is fully functional with JSONB embeddings.

## Files

```
db/migrations/001_init.sql   # schema (idempotent)
db/seed.sql                  # sample rows for every table
scripts/db-init.sh           # create DB + migrate + seed
scripts/db-health.sh         # connectivity + pgvector + table verification
```
