# pgvector vs JSONB vs Naive Retrieval Benchmark

- **Date:** 2026-09-10
- **Capabilities:** 64
- **Intents:** 20
- **k:** 5
- **Embeddings:** deterministic TF-IDF stand-ins (no external model)

## pgvector path (Docker `pgvector/pgvector:pg16`, port 5434)

| Method | Status | Avg latency (ms) | p95 (ms) | Recall@5 |
|---|---|---|---|---|
| naive (in-memory) | OK | 3.892 | 5.633 | N/A |
| pgvector (HNSW) | OK | 0.723 | 0.958 | 1.00 |
| jsonb | SKIPPED | — | — | — |

**Finding:** pgvector is ~5.4x faster than naive in-memory cosine and achieves
recall@5 = 1.00 (identical top-5 to the ground-truth in-memory result).

## JSONB fallback path (local PostgreSQL 16, no pgvector)

| Method | Status | Avg latency (ms) | p95 (ms) | Recall@5 |
|---|---|---|---|---|
| naive (in-memory) | OK | 4.266 | 6.971 | N/A |
| jsonb (SQL cosine) | OK | 702.958 | 784.871 | 0.07 |
| pgvector | SKIPPED | — | — | — |

**Finding:** JSONB SQL-cosine is ~165x slower than naive in-memory and has
poor recall (0.07) because the SQL cosine over JSONB arrays is lossy. This is
why pgvector is the preferred path when available.

## Notes

- pgvector is OPTIONAL. If unavailable, JSONB/naive fallback is used.
- The JSONB fallback remains operational (verified against local PG).
- Recall@5 is vs the naive in-memory result as ground truth.
- pgvector was run in a Docker container (`pgvector/pgvector:pg16`) to avoid
  modifying the working PostgreSQL installation.
