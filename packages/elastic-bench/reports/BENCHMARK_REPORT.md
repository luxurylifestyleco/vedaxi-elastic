# ElasticBench V0 — Benchmark Report

- **Generated:** 2026-11-09T09:48:08+0530
- **Tasks:** 132 synthetic IntentIR tasks
- **Capabilities sampled:** 66 of 66 in the demo-bank manifest
- **Domains covered:** 11
- **Seed:** 20260910

## Controls

- **Control A (baseline):** full capability list in context, no retrieval.
- **Control B (retrieval):** top-K retrieval, LLM sees only K capabilities.
- **Control C (recipe):** pre-authored recipes; no model calls. Only covers 3 intent families (statement, payment, card freeze).

## Summary

| Metric | Control A | Control B | Control C |
|---|---|---|---|
| Success rate | 98.5% | 98.5% | 4.5% |
| Median total tokens | 1141 | 119 | 0 |
| Median latency (ms) | 0.13 | 0.71 | 0.00 |
| Cost / successful intent | $0.002309 | $0.000267 | $0.000000 |

### Per-control detail

### control_a

- Runs: 132 (successes: 130, failures: 2)
- Success rate: 98.5%
- Input tokens: median 1137, p95 1142
- Output tokens: median 4, p95 6
- Total tokens: median 1141, p95 1149
- Latency: median 0.13 ms, p95 0.20 ms
- Total LLM calls: 132
- Total tool calls: 130
- Total retrieval calls: 0
- Total steps: 394
- Total estimated cost: $0.304784
- Cost per successful intent: $0.002309

### control_b

- Runs: 132 (successes: 130, failures: 2)
- Success rate: 98.5%
- Input tokens: median 114, p95 137
- Output tokens: median 4, p95 6
- Total tokens: median 119, p95 142
- Latency: median 0.71 ms, p95 0.90 ms
- Total LLM calls: 132
- Total tool calls: 130
- Total retrieval calls: 132
- Total steps: 526
- Total estimated cost: $0.035272
- Cost per successful intent: $0.000267

### control_c

- Runs: 132 (successes: 6, failures: 126)
- Success rate: 4.5%
- Input tokens: median 0, p95 0
- Output tokens: median 0, p95 0
- Total tokens: median 0, p95 0
- Latency: median 0.00 ms, p95 0.00 ms
- Total LLM calls: 0
- Total tool calls: 8
- Total retrieval calls: 132
- Total steps: 8
- Total estimated cost: $0.000000
- Cost per successful intent: $0.000000

## Notes

- Control C only has hand-written recipes for 3 intent families; tasks outside that coverage are recorded as failures (honest coverage limitation, not a bug).
- Token and cost estimates are deterministic heuristics (see metrics.py); no external LLM API is called.
