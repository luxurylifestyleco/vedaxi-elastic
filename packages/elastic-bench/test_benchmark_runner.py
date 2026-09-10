"""Tests for the ElasticBench V0 runner (Phase 15).

Verifies that the benchmark runner:
  * generates >= 100 synthetic IntentIR tasks,
  * runs all three controls (A, B, C) for every task,
  * writes the three report files (JSON, CSV, Markdown) with real content.
"""

from __future__ import annotations

import csv
import json
import os

import pytest

import benchmark_runner as br

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPORTS = os.path.join(_HERE, "reports")

REPORT_FILES = (
    "benchmark_results.json",
    "benchmark_results.csv",
    "BENCHMARK_REPORT.md",
)


def test_generates_at_least_100_tasks():
    caps = br.build_manifest()
    tasks = br.generate_tasks(caps, variants=2, seed=br.SEED)
    assert len(tasks) >= 100
    # Every task is a valid IntentIR with the required fields populated.
    for t in tasks:
        assert t.intent_id
        assert t.goal
        assert t.domain
        assert t.action
        assert t.object
        assert t.desired_output


def test_generate_tasks_covers_all_capabilities_and_domains():
    caps = br.build_manifest()
    tasks = br.generate_tasks(caps, variants=2, seed=br.SEED)
    goals = {t.goal for t in tasks}
    assert goals == {c.id for c in caps}
    domains = {t.domain for t in tasks}
    assert domains == {c.domain for c in caps}


def test_all_three_controls_run_for_every_task():
    caps = br.build_manifest()
    tasks = br.generate_tasks(caps, variants=2, seed=br.SEED)
    agent_a = br.BaselineAgent(caps)
    agent_b = br.RetrievalAgent(caps)
    harness = br.control_c.ControlC()

    for intent in tasks:
        a = br._run_control_a(agent_a, intent)
        b = br._run_control_b(agent_b, intent)
        c = br._run_control_c(harness, intent)
        # All three return the shared metric fields.
        for metrics in (a, b, c):
            for field in (
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "llm_calls",
                "tool_calls",
                "retrieval_calls",
                "steps",
                "wall_clock_latency_ms",
                "success",
                "estimated_model_cost",
            ):
                assert field in metrics, f"missing metric field {field}"


def test_control_b_uses_retrieval_and_fewer_input_tokens():
    caps = br.build_manifest()
    tasks = br.generate_tasks(caps, variants=2, seed=br.SEED)
    agent_a = br.BaselineAgent(caps)
    agent_b = br.RetrievalAgent(caps)
    for intent in tasks:
        a = agent_a.run(intent)
        b = agent_b.run(intent)
        assert b["retrieval_calls"] >= 1
        assert b["input_tokens"] < a["input_tokens"]


def test_control_c_llm_calls_zero():
    caps = br.build_manifest()
    tasks = br.generate_tasks(caps, variants=2, seed=br.SEED)
    harness = br.control_c.ControlC()
    for intent in tasks:
        c = br._run_control_c(harness, intent)
        assert c["llm_calls"] == 0
        assert c["estimated_model_cost"] == 0.0


def test_report_files_exist_and_nonempty():
    report = br.run_benchmark(num_variants=2, seed=br.SEED)
    for name in REPORT_FILES:
        path = os.path.join(_REPORTS, name)
        assert os.path.exists(path), f"missing report file: {path}"
        assert os.path.getsize(path) > 0, f"empty report file: {path}"

    # JSON report is valid and has the expected structure.
    with open(os.path.join(_REPORTS, "benchmark_results.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["num_tasks"] >= 100
    assert set(data["aggregates"].keys()) == {"control_a", "control_b", "control_c"}
    assert len(data["rows"]) == data["num_tasks"] * 3

    # CSV has one row per (task, control) run.
    with open(os.path.join(_REPORTS, "benchmark_results.csv"), encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == data["num_tasks"] * 3
    assert {r["control"] for r in rows} == {"control_a", "control_b", "control_c"}

    # Markdown report is non-trivial.
    with open(os.path.join(_REPORTS, "BENCHMARK_REPORT.md"), encoding="utf-8") as fh:
        md = fh.read()
    assert "ElasticBench V0" in md
    assert "Control A" in md and "Control B" in md and "Control C" in md
