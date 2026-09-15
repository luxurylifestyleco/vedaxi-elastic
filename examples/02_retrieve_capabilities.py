"""Example 02: Capability Discovery and Retrieval."""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGES_DIR = os.path.join(_REPO_ROOT, "packages")
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "intent-ir"))
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "capability-registry"))
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "capability-retrieval"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "apps", "demo-bank"))

from compiler import RuleBasedCompiler
from factory import build_retriever
from manifest import build_manifest


def main() -> None:
    capabilities = build_manifest()
    print(f"Loaded {len(capabilities)} capabilities from demo-bank manifest.")

    retriever = build_retriever("keyword", capabilities)
    compiler = RuleBasedCompiler(default_year=2026)

    test_queries = [
        "Get my August bank statement",
        "Download credit card statement",
        "Find my paid receipt",
    ]

    print("\n=== Capability Retrieval Results ===")
    for q in test_queries:
        intent = compiler.compile(q)
        candidates = retriever.retrieve(intent, k=3)
        print(f"\nQuery: '{q}'")
        print(f"Compiled Goal: {intent.goal}")
        print("Top 3 Candidate Capabilities:")
        for rank, cand in enumerate(candidates, 1):
            print(f"  {rank}. Capability ID: {cand.capability_id} (Score: {cand.score:.3f}, Latency: {cand.retrieval_latency_ms:.2f}ms)")


if __name__ == "__main__":
    main()
