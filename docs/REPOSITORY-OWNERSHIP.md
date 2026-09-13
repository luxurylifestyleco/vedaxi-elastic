# Foundation repository ownership

`luxurylifestyleco/vedaxi-elastic` is the canonical foundation repository.
`SyedHasanCronosPMC/vedaxi-elastic` is its intentionally maintained private Git
copy for continuity and recovery. Both are private as verified on 2026-09-13;
neither is authorized for public release by this change. Personal-copy Actions
are disabled to avoid duplicate CI/deployment execution.

The foundation owns Intent IR, capability registry/retrieval/disclosure, recipe
schema and runtime, telemetry, ElasticBench and the demo bank. Mastermind embeds
these packages alongside its separate private adaptive layer. Shared fixes
should originate here, receive regression coverage, and then be synchronized
into Mastermind explicitly. Private adaptive code must never be copied here.

The September 2026 reconciliation adds regression coverage for deterministic
Unicode disclosure size and the existing `RecipeStore.resolve` API. Its existing
lexical version ordering and exclusion of RETIRED recipes are unchanged; the
docstring now describes that accurately. Mastermind's embedded copies are
aligned to this source. Generated benchmark reports describe separate runs and
are not source drift; no historic report is replaced merely to make files match.

Do not remove shared package directories until a separately reviewed packaging
migration exists. For now, the private Mastermind repository includes a read-only
`scripts/check_foundation_parity.py` that compares all 49 tracked non-report
foundation package files using Git clean filters. Run it against both local
checkouts after any shared-package change.

The public `luxurylifestyleco/vedaxi-elastic-web` publisher demo and
`SyedHasanCronosPMC/vedaxi-protocol-edition` experience are separate surfaces,
not backup destinations for foundation/private runtime code. Related brand names
alone do not establish duplicate repositories.

## Explicit synchronization

Personal copies preserve Git branches, tags and reachable history. They do not
back up GitHub issues, PR conversations, release attachments, secrets, permissions
or deployment settings. The original remains authoritative. Keep the same
default branch (`main`), copy review branches as branches, and merge in the
original before synchronizing the resulting main commit.

The private Mastermind repository provides `scripts/sync_private_sources.py`:
default `--check` is read-only; `--sync` explicitly copies heads/tags with an
atomic, non-force push after owner, identity, privacy and Actions checks. It
refuses unexpected destination refs or destructive updates instead of deleting
them. No recurring synchronization is scheduled. Run it again after Cody merges.

This branch is `codex/repository-governance`, based on
`1cd31f110260bfb266ed46fef7f47acfad5dac36`. Cody should review and merge this branch
into the original foundation `main`; the private personal copy follows that merge.
