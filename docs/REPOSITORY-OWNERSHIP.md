# Foundation ownership

luxurylifestyleco/vedaxi-elastic owns Intent IR, registry/retrieval, recipe
schema/runtime, telemetry, ElasticBench and the demo bank. Current visibility is
private. An intended open boundary is not authorization to publish.

Mastermind embeds shared packages alongside its private adaptive layer. Shared
fixes originate here, receive regression coverage and are carried into Mastermind.
Private adaptive code must never be copied here. The reconciliation preserves
Unicode accounting and RecipeStore.resolve, including lexical version ordering.
All 49 shared non-report files match. Historical reports remain independent.

Run Mastermind's scripts/check_foundation_parity.py against this checkout after
shared changes. Preserve embedded modules until a reviewed packaging migration.
The application and Supabase database belong to Mastermind's deployment;
foundation does not need a duplicate database/API. Publisher code must use an
authenticated application endpoint, never database credentials.

Review codex/repository-governance and merge into foundation main after CI, then
review the corresponding Mastermind ledger/runtime branch.
