# ElasticBench V0 — Benchmark Report

- **Generated:** 2026-09-10T12:49:10+0530
- **Tasks:** 128 synthetic IntentIR tasks
- **Capabilities sampled:** 64 of 64 in the demo-bank manifest
- **Domains covered:** 10
- **Seed:** 20260910

## Controls

- **Control A (baseline):** full capability list in context, no retrieval.
- **Control B (retrieval):** top-K retrieval, LLM sees only K capabilities.
- **Control C (recipe):** pre-authored recipes; no model calls. Only covers 3 intent families (statement, payment, card freeze).

## Summary

| Metric | Control A | Control B | Control C |
|---|---|---|---|
| Success rate | 100.0% | 100.0% | 4.7% |
| Median total tokens | 1111 | 119 | 0 |
| Median latency (ms) | 0.15 | 0.55 | 0.00 |
| Cost / successful intent | $0.002248 | $0.000267 | $0.000000 |

### Per-control detail

### control_a

- Runs: 128 (successes: 128, failures: 0)
- Success rate: 100.0%
- Input tokens: median 1107, p95 1112
- Output tokens: median 4, p95 6
- Total tokens: median 1111, p95 1119
- Latency: median 0.15 ms, p95 0.19 ms
- Total LLM calls: 128
- Total tool calls: 128
- Total retrieval calls: 0
- Total steps: 384
- Total estimated cost: $0.287746
- Cost per successful intent: $0.002248

### control_b

- Runs: 128 (successes: 128, failures: 0)
- Success rate: 100.0%
- Input tokens: median 114, p95 140
- Output tokens: median 4, p95 6
- Total tokens: median 119, p95 144
- Latency: median 0.55 ms, p95 0.68 ms
- Total LLM calls: 128
- Total tool calls: 128
- Total retrieval calls: 128
- Total steps: 512
- Total estimated cost: $0.034238
- Cost per successful intent: $0.000267

### control_c

- Runs: 128 (successes: 6, failures: 122)
- Success rate: 4.7%
- Input tokens: median 0, p95 0
- Output tokens: median 0, p95 0
- Total tokens: median 0, p95 0
- Latency: median 0.00 ms, p95 0.00 ms
- Total LLM calls: 0
- Total tool calls: 8
- Total retrieval calls: 128
- Total steps: 8
- Total estimated cost: $0.000000
- Cost per successful intent: $0.000000

## Notes

- Control C only has hand-written recipes for 3 intent families; tasks outside that coverage are recorded as failures (honest coverage limitation, not a bug).
- Token and cost estimates are deterministic heuristics (see metrics.py); no external LLM API is called.
