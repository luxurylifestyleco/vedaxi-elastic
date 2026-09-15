"""Example 03: Multi-step Recipe Execution with Demo Bank."""

from __future__ import annotations

import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGES_DIR = os.path.join(_REPO_ROOT, "packages")
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "recipe-schema"))
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "elastic-bench"))
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "telemetry"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "apps", "demo-bank"))

import control_c


def main() -> None:
    print("=== Multi-step Recipe Execution (Control C) ===")
    store = control_c.build_store()
    print(f"Store initialized with {len(store)} pre-registered recipes.")

    # 1. Statement retrieval recipe
    print("\n1. Running 'retrieve_statement' recipe:")
    res1 = control_c.run("Get my statement for 2026-08")
    print(f"   Recipe ID: {res1.get('recipe_id')}")
    print(f"   Success: {res1.get('metrics', {}).get('success')}")
    print(f"   Latency: {res1.get('metrics', {}).get('wall_clock_latency_ms')}ms")
    print(f"   Result: {json.dumps(res1.get('results'), default=str)}")

    # 2. Payment execution recipe (two-step DAG: check_balance -> make_payment)
    print("\n2. Running 'make_payment' recipe:")
    res2 = control_c.run("Pay electricity bill", params={"amount": 89.50, "payee": "City Power"})
    print(f"   Recipe ID: {res2.get('recipe_id')}")
    print(f"   Success: {res2.get('metrics', {}).get('success')}")
    print(f"   Steps Executed: {res2.get('metrics', {}).get('steps')}")
    print(f"   Results by step:")
    for step_id, step_res in res2.get("results", {}).items():
        print(f"     - {step_id}: {step_res}")


if __name__ == "__main__":
    main()
