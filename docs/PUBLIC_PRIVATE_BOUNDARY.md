# Public / private boundary

This GitHub repository (`luxurylifestyleco/vedaxi-elastic`) is the **public foundation**.

It is Apache-2.0 licensed source for intent IR, capabilities, retrieval, progressive disclosure, recipes, local telemetry, and the A/B/C benchmark.

## What is in this repository

- Intent IR model and rule-based compiler
- Capability model, registry, demo seed, MCP **adapter**
- Keyword (and optional vector) retrieval
- L0 / L1 / L2 disclosure
- Recipe schema, store, DAG execution
- Local event bus and recorders
- Demo bank + gateway used by examples
- Benchmark harness (Controls A, B, C)

## What is not in this repository

A separate **private** codebase holds Vedaxi's adaptive-intelligence layer. This public repo's `boundary-check.yml` CI job **fails the build** if proprietary markers appear (for example `packages/adaptive-recipe`, `meta_policy`, `RecipeCandidateCompiler`, and related names). That job is the enforcement mechanism.

Do not expect documentation or code here for:

- Proprietary adaptive execution policy
- Internal EXPLORE / REUSE / ADAPT / CHALLENGE decision engines
- Meta-policy implementation
- Recipe *learning* / self-improvement algorithms
- Private scoring, model routing, or causal-learning machinery
- Hosted production control plane internals

If a public module mentions a future LLM compiler or "optimization out of scope," that is an **interface note**, not an implementation.

## How to talk about the split

You may say: this toolkit makes services intent-addressable; production adaptive intelligence is a separate Vedaxi system.

You may not reconstruct private algorithms from this repo — they are not here.

Trademarks: [TRADEMARKS.md](../TRADEMARKS.md). License: [LICENSE](../LICENSE).
