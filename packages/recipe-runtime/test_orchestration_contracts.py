import json

from recipe_runtime.orchestration_contracts import (
    EvidenceReport,
    NextActionDecision,
    VerificationStatus,
    VerificationVerdict,
    WorkerTaskSpec,
    build_verification_prompt,
    build_worker_task_prompt,
)


def test_orchestration_contracts_serialize_and_render_explicit_boundaries():
    spec = WorkerTaskSpec(
        task_id="contracts-1",
        worker_name="Sub Agent 9 // Builder Contracts",
        scope="Add typed orchestration contracts",
        write_boundaries=["packages/recipe-runtime/orchestration_contracts.py", "focused tests"],
        acceptance_criteria=["Models serialize to JSON", "No executor is added"],
        constraints=["Do not modify queue JSON"],
    )
    report = EvidenceReport(
        task_id=spec.task_id,
        changed_files=["packages/recipe-runtime/orchestration_contracts.py"],
        commands=["python -m pytest packages/recipe-runtime/test_orchestration_contracts.py -q"],
        exact_evidence=["2 passed"],
        next_action="Master independently verifies the diff",
    )
    verdict = VerificationVerdict(
        task_id=spec.task_id,
        status=VerificationStatus.PASS,
        checked=["scope", "acceptance", "changed paths"],
        evidence=["focused test output", "git diff --check"],
    )
    decision = NextActionDecision(
        task_id=spec.task_id,
        action="Close verified task",
        reason="All local acceptance criteria have observable evidence",
    )

    payload = json.loads(json.dumps({"spec": spec.model_dump(mode="json"), "report": report.model_dump(mode="json")}))
    assert payload["spec"]["write_boundaries"] == [
        "packages/recipe-runtime/orchestration_contracts.py",
        "focused tests",
    ]
    assert "Sub Agent 9 // Builder Contracts" in str(build_worker_task_prompt(spec).format_messages())
    assert "2 passed" in str(build_verification_prompt(report, verdict).format_messages())
    assert decision.authorization_required is False


def test_orchestration_contracts_reject_missing_evidence_and_extra_fields():
    try:
        EvidenceReport(task_id="x", next_action="stop")
    except ValueError as exc:
        assert "exact_evidence" in str(exc)
    else:
        raise AssertionError("evidence must be explicit")

    try:
        WorkerTaskSpec(
            task_id="x",
            worker_name="worker",
            scope="scope",
            write_boundaries=["module"],
            acceptance_criteria=["criterion"],
            unexpected="not allowed",
        )
    except ValueError as exc:
        assert "unexpected" in str(exc)
    else:
        raise AssertionError("extra fields must be rejected")
