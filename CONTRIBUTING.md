# Contributing

Thanks for your interest in Elastic Web.

## Ground rules

- **Reuse before building.** Before implementing any substantial component,
  check the existing packages and the dependency matrix. Prefer integrating a
  mature open-source project over copying or reimplementing it.
- **Do not invent the proprietary layer.** The Meta-Policy, Recipe Optimizer,
  automatic recipe learning, and proprietary ranking are explicitly out of
  scope. Do not implement them.
- **This is a PUBLIC repository.** It defines *how Elastic-compatible systems
  communicate and execute* — NOT *how Vedaxi learns to become better than
  other Elastic implementations*. The proprietary adaptive-intelligence layer
  (REUSE/ADAPT/EXPLORE/CHALLENGE logic, recipe generation/mutation/
  generalization, meta-policy, staleness detection, failure/outcome learning,
  intelligence-cost optimization, private training datasets) lives in the
  separate PRIVATE repo `Vedaxi-Elastic-Web-Mastermind`. If a task requires
  proprietary work, create a GitHub issue labeled `private-intelligence-required`
  and stop that component. CI enforces this via `.github/workflows/boundary-check.yml`.
- **Pin dependencies.** Record every dependency, its version, license, and
  purpose in `docs/DEPENDENCY-MATRIX.md`.
- **Never commit secrets.** No API keys, tokens, or real credentials.
- **Keep it runnable.** Every phase must leave the app runnable and tested.

## Workflow

1. Fork the repo and create a feature branch.
2. Make small, atomic commits.
3. Run the full test suite before committing.
4. Open a pull request describing what changed and why.

## Running tests

```bash
# From the repo root, with sibling packages on the path:
PYTHONPATH="packages/capability-registry:packages/intent-ir:packages/capability-retrieval:packages/telemetry:packages/recipe-schema:apps/demo-bank" \
  python3 -m pytest packages apps -q
```

## Running the benchmark

```bash
python3 packages/elastic-bench/benchmark_runner.py
```

Outputs land in `packages/elastic-bench/reports/`.
