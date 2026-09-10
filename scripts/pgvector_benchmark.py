"""Phase A1 — pgvector vs JSONB/naive retrieval benchmark.

Compares capability retrieval performance and correctness between:

1. **Naive in-memory** — the existing `VectorRetriever` (TF-IDF cosine, no DB).
2. **JSONB fallback** — embeddings stored as JSONB arrays, cosine computed in
   SQL (no pgvector extension).
3. **pgvector** — embeddings stored as `vector` type with an HNSW index,
   similarity via `<=>` operator.

The benchmark measures latency and top-k correctness (recall@k vs the naive
in-memory result as ground truth) across the demo-bank capability corpus.

pgvector is NOT mandatory: if the extension is unavailable, the benchmark
reports the JSONB/naive results and marks pgvector as SKIPPED.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# sys.path bootstrap
# ---------------------------------------------------------------------------
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))          # scripts
_REPO_ROOT = os.path.dirname(_PKG_DIR)                          # elastic-web
_PACKAGES_DIR = os.path.join(_REPO_ROOT, "packages")
for _path in (
    _PACKAGES_DIR,
    os.path.join(_PACKAGES_DIR, "intent-ir"),
    os.path.join(_PACKAGES_DIR, "capability-registry"),
    os.path.join(_PACKAGES_DIR, "capability-retrieval"),
    os.path.join(_REPO_ROOT, "apps", "demo-bank"),
):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from capability import Capability  # noqa: E402
from intent_ir import IntentIR  # noqa: E402
from manifest import build_manifest  # noqa: E402
from strategies import VectorRetriever  # noqa: E402
from retriever import _capability_text, tokenize  # noqa: E402

# ---------------------------------------------------------------------------
# Embedding helper (deterministic TF-IDF -> dense vector)
# ---------------------------------------------------------------------------


def _embed(text: str, vocab: List[str], dim: int = 384) -> List[float]:
    """Build a deterministic dense vector from a text (bag-of-words hashing).

    This is a stand-in for a real embedding model so the benchmark is
    reproducible and dependency-free. Each token maps to a fixed index via
    its hash; the value is the token count.
    """
    vec = [0.0] * dim
    for tok in tokenize(text):
        idx = abs(hash(tok)) % dim
        vec[idx] += 1.0
    return vec


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------


class PgvectorBenchmark:
    """Benchmark naive vs JSONB vs pgvector retrieval."""

    def __init__(self, capabilities: List[Capability], conn=None) -> None:
        self._caps = capabilities
        self._conn = conn  # psycopg2 connection (pgvector or JSONB DB)
        self._vocab = sorted({t for c in capabilities for t in tokenize(_capability_text(c))})
        self._embeddings = {
            c.id: _embed(_capability_text(c), self._vocab) for c in capabilities
        }

    # -- naive in-memory (ground truth) ----------------------------------

    def naive_retrieve(self, intent: IntentIR, k: int = 5) -> List[str]:
        """In-memory cosine retrieval (ground truth for recall)."""
        q = _embed(_intent_text(intent), self._vocab)
        scored = sorted(
            ((c.id, _cosine(q, self._embeddings[c.id])) for c in self._caps),
            key=lambda x: x[1],
            reverse=True,
        )
        return [cid for cid, _ in scored[:k]]

    # -- JSONB fallback (SQL cosine over JSONB arrays) --------------------

    def jsonb_retrieve(self, intent: IntentIR, k: int = 5) -> List[str]:
        """Retrieve via SQL cosine over JSONB-array embeddings.

        Only valid when the embedding column is JSONB (non-pgvector fallback).
        If the column is a vector type, this path is skipped.
        """
        if self._conn is None:
            return []
        # If pgvector is present, the column is vector type — JSONB path N/A.
        if self._has_pgvector():
            return []
        q = _embed(_intent_text(intent), self._vocab)
        # Convert to a Postgres array literal: {0.0, 0.0, ...}
        q_arr = "{" + ",".join(f"{v}" for v in q) + "}"
        cur = self._conn.cursor()
        # Compute cosine in SQL over the JSONB array.
        cur.execute(
            """
            SELECT name,
                   (SELECT SUM(a*b) FROM
                      (SELECT unnest(ARRAY(SELECT jsonb_array_elements_text(embedding)::float8)) AS a) x,
                      (SELECT unnest(%s::float8[]) AS b) y
                    WHERE x.a IS NOT NULL AND y.b IS NOT NULL) /
                   (NULLIF(SQRT((SELECT SUM(a*a) FROM (SELECT unnest(ARRAY(SELECT jsonb_array_elements_text(embedding)::float8)) AS a) z)),
                           0) *
                    SQRT((SELECT SUM(b*b) FROM (SELECT unnest(%s::float8[]) AS b) w)))
                   AS sim
            FROM bench_capabilities
            WHERE embedding IS NOT NULL
            ORDER BY sim DESC NULLS LAST
            LIMIT %s
            """,
            (q_arr, q_arr, k),
        )
        return [row[0] for row in cur.fetchall()]

    # -- pgvector --------------------------------------------------------

    def pgvector_retrieve(self, intent: IntentIR, k: int = 5) -> List[str]:
        """Retrieve via pgvector `<=>` similarity."""
        if self._conn is None:
            return []
        q = _embed(_intent_text(intent), self._vocab)
        cur = self._conn.cursor()
        cur.execute(
            "SELECT name FROM bench_capabilities "
            "WHERE embedding IS NOT NULL "
            "ORDER BY embedding <=> %s::vector LIMIT %s",
            (json.dumps(q), k),
        )
        return [row[0] for row in cur.fetchall()]

    # -- runner ----------------------------------------------------------

    def run(self, intents: List[IntentIR], k: int = 5) -> Dict[str, Any]:
        """Run the benchmark across intents and report latency + recall."""
        results: Dict[str, Any] = {
            "naive": {"latency_ms": [], "recall": []},
            "jsonb": {"latency_ms": [], "recall": []},
            "pgvector": {"latency_ms": [], "recall": []},
        }

        for intent in intents:
            # Naive (ground truth).
            t0 = time.perf_counter()
            naive = self.naive_retrieve(intent, k)
            results["naive"]["latency_ms"].append((time.perf_counter() - t0) * 1000.0)

            # JSONB (only when the column is JSONB, i.e. no pgvector).
            if self._conn is not None and not self._has_pgvector():
                t0 = time.perf_counter()
                jsonb = self.jsonb_retrieve(intent, k)
                results["jsonb"]["latency_ms"].append((time.perf_counter() - t0) * 1000.0)
                results["jsonb"]["recall"].append(self._recall(naive, jsonb))

            # pgvector.
            if self._conn is not None and self._has_pgvector():
                t0 = time.perf_counter()
                pgv = self.pgvector_retrieve(intent, k)
                results["pgvector"]["latency_ms"].append((time.perf_counter() - t0) * 1000.0)
                results["pgvector"]["recall"].append(self._recall(naive, pgv))

        return self._summarize(results)

    def _has_pgvector(self) -> bool:
        if self._conn is None:
            return False
        cur = self._conn.cursor()
        cur.execute("SELECT 1 FROM pg_extension WHERE extname='vector'")
        return cur.fetchone() is not None

    def seed_db(self) -> None:
        """Populate the capabilities table with embeddings (idempotent)."""
        if self._conn is None:
            return
        cur = self._conn.cursor()
        cur.execute("TRUNCATE bench_capabilities RESTART IDENTITY CASCADE")
        has_pgvector = self._has_pgvector()
        cast = "::vector" if has_pgvector else "::jsonb"
        for cap in self._caps:
            emb = self._embeddings[cap.id]
            cur.execute(
                f"INSERT INTO bench_capabilities (name, description, category, embedding) "
                f"VALUES (%s, %s, %s, %s{cast})",
                (cap.id, cap.description, cap.domain, json.dumps(emb)),
            )
        self._conn.commit()

    @staticmethod
    def _recall(ground_truth: List[str], retrieved: List[str]) -> float:
        if not ground_truth:
            return 0.0
        gt = set(ground_truth)
        hit = sum(1 for r in retrieved if r in gt)
        return hit / len(gt)

    @staticmethod
    def _summarize(results: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for method, data in results.items():
            lat = data["latency_ms"]
            rec = data["recall"]
            out[method] = {
                "runs": len(lat),
                "avg_latency_ms": sum(lat) / len(lat) if lat else 0.0,
                "p95_latency_ms": sorted(lat)[int(len(lat) * 0.95)] if lat else 0.0,
                "avg_recall": sum(rec) / len(rec) if rec else None,
                "skipped": len(lat) == 0,
            }
        return out


def _intent_text(intent: IntentIR) -> str:
    return " ".join([intent.goal, intent.domain, intent.action, intent.object, intent.desired_output])


def _sample_intents(caps: List[Capability], n: int = 20) -> List[IntentIR]:
    """Build sample intents from the capability corpus."""
    intents = []
    for cap in caps[:n]:
        intents.append(
            IntentIR(
                intent_id=f"bench-{cap.id}",
                goal=cap.id,
                domain=cap.domain,
                action="execute",
                object="resource",
                desired_output="json",
            )
        )
    return intents


def main() -> None:
    caps = build_manifest()
    intents = _sample_intents(caps)

    # Try to connect to a pgvector-enabled DB. Default to the local elastic_web
    # DB (port 5432) which has the JSONB bench_capabilities table. pgvector is
    # only used if the extension is present.
    conn = None
    try:
        import psycopg2

        # Password is read from the environment only; never hardcoded. Local
        # dev Postgres commonly uses trust/peer auth, so an unset
        # PGVECTOR_PASSWORD falls back to an empty string.
        pwd = os.environ.get("PGVECTOR_PASSWORD", "")
        conn = psycopg2.connect(
            host=os.environ.get("PGVECTOR_HOST", "localhost"),
            port=int(os.environ.get("PGVECTOR_PORT", "5432")),
            user=os.environ.get("PGVECTOR_USER", "postgres"),
            password=pwd,
            dbname=os.environ.get("PGVECTOR_DB", "elastic_web"),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"DB not reachable ({exc}); running naive-only benchmark")
        conn = None

    bench = PgvectorBenchmark(caps, conn=conn)
    if conn is not None:
        bench.seed_db()
    results = bench.run(intents, k=5)

    print("=== PGVECTOR vs JSONB vs NAIVE RETRIEVAL BENCHMARK ===")
    print(f"Capabilities: {len(caps)}, intents: {len(intents)}, k=5")
    for method, data in results.items():
        status = "SKIPPED" if data["skipped"] else "OK"
        recall = f"{data['avg_recall']:.2f}" if data["avg_recall"] is not None else "N/A"
        print(
            f"  {method:10s} [{status}] avg_latency={data['avg_latency_ms']:.3f}ms "
            f"p95={data['p95_latency_ms']:.3f}ms recall@{5}={recall}"
        )

    # Write the report.
    reports_dir = os.path.join(_REPO_ROOT, "docs")
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, "PGVECTOR-BENCHMARK.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("# pgvector vs JSONB vs Naive Retrieval Benchmark\n\n")
        fh.write(f"- **Date:** {time.strftime('%Y-%m-%d')}\n")
        fh.write(f"- **Capabilities:** {len(caps)}\n")
        fh.write(f"- **Intents:** {len(intents)}\n")
        fh.write(f"- **k:** 5\n\n")
        fh.write("| Method | Status | Avg latency (ms) | p95 (ms) | Recall@5 |\n")
        fh.write("|---|---|---|---|---|\n")
        for method, data in results.items():
            status = "SKIPPED" if data["skipped"] else "OK"
            recall = f"{data['avg_recall']:.2f}" if data["avg_recall"] is not None else "N/A"
            fh.write(
                f"| {method} | {status} | {data['avg_latency_ms']:.3f} | "
                f"{data['p95_latency_ms']:.3f} | {recall} |\n"
            )
        fh.write("\n## Notes\n\n")
        fh.write("- pgvector is OPTIONAL. If unavailable, JSONB/naive fallback is used.\n")
        fh.write("- Embeddings are deterministic TF-IDF stand-ins (no external model).\n")
        fh.write("- Recall@5 is vs the naive in-memory result as ground truth.\n")
    print(f"Report written: {report_path}")


if __name__ == "__main__":
    main()
