"""Example 01: Compiling a natural language intent into IntentIR."""

from __future__ import annotations

import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "packages", "intent-ir"))

from compiler import RuleBasedCompiler
from intent_ir import IntentIR


def main() -> None:
    compiler = RuleBasedCompiler(default_year=2026)
    sample_queries = [
        "Get my August bank statement for 2026",
        "Download credit card statement",
        "Retrieve my July invoice",
    ]

    print("=== Elastic Web IntentIR Compilation ===")
    for text in sample_queries:
        ir = compiler.compile(text)
        print(f"\nInput: \"{text}\"")
        print(f"Goal: {ir.goal}")
        print(f"Domain: {ir.domain} | Action: {ir.action} | Object: {ir.object}")
        print(f"Constraints: {ir.constraints}")
        print(f"Desired Output: {ir.desired_output}")
        print("Valid IntentIR:", isinstance(ir, IntentIR))


if __name__ == "__main__":
    main()
