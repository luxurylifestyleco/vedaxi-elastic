# pgvector vs JSONB vs Naive Retrieval Benchmark

- **Date:** 2026-09-10
- **Capabilities:** 64
- **Intents:** 20
- **k:** 5

| Method | Status | Avg latency (ms) | p95 (ms) | Recall@5 |
|---|---|---|---|---|
| naive | OK | 3.848 | 4.268 | N/A |
| jsonb | OK | 669.372 | 745.354 | 0.03 |
| pgvector | SKIPPED | 0.000 | 0.000 | N/A |

## Notes

- pgvector is OPTIONAL. If unavailable, JSONB/naive fallback is used.
- Embeddings are deterministic TF-IDF stand-ins (no external model).
- Recall@5 is vs the naive in-memory result as ground truth.
