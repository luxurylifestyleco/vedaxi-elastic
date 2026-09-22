"""Contracts reject unsafe ambiguity; this suite does not prove runtime enforcement."""
import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from assurance import AssuranceDocument, AssuranceIntent, Budget, EvidenceReceipt, PermissionGrant, StepCheckpoint

DIGEST = 'a' * 64
TIME = '2026-09-22T10:00:00Z'


def intent():
    return dict(intent_id='intent-1', goal='Find records', desired_end_state={'records': 1},
                budget={'max_tool_calls': 1, 'max_duration_ms': 10000}, max_risk='low',
                approval_policy={'mode': 'bounded_grant', 'approver': 'user-1', 'required_for': ['disclosure']},
                acceptance_tests=[{'test_id': 'records', 'evaluator': 'record-count-v1', 'target': '/records', 'expected': 1}])


def receipt():
    return dict(receipt_id='r1', intent_id='intent-1', execution_id='e1', step_id='s1',
                input_sha256=DIGEST, output_sha256=DIGEST, checkpoint_sha256=DIGEST,
                issuer='runtime', recorded_at=TIME, status='pass',
                acceptance_results=[{'test_id':'records','status':'pass','evaluator':'record-count-v1','evidence_refs':['event-1']}],
                source_refs=['trace-1'])


def test_roundtrip_and_generated_schema():
    value = AssuranceIntent(**intent())
    assert value.budget.max_cost is None and value.budget.currency is None
    assert AssuranceIntent.model_validate_json(value.model_dump_json()) == value
    evidence = EvidenceReceipt(**receipt())
    assert evidence.signature_ref is None and evidence.verification_scope == 'internal'
    assert json.loads(Path(__file__).with_name('schema.json').read_text()) == AssuranceDocument.model_json_schema()


def test_invalid_boundaries():
    for patch in ({'goal':' '}, {'unexpected':True}, {'schema_version':'2.0'}, {'acceptance_tests':[]}):
        with pytest.raises(ValidationError):
            AssuranceIntent(**{**intent(), **patch})
    doubled = intent()
    doubled['acceptance_tests'] *= 2
    with pytest.raises(ValidationError): AssuranceIntent(**doubled)
    for budget in ({'max_tool_calls': -1,'max_duration_ms':10}, {'max_tool_calls':True,'max_duration_ms':10}, {'max_tool_calls':1,'max_duration_ms':0}, {'max_tool_calls':1,'max_duration_ms':10,'max_cost':float('nan')}):
        with pytest.raises(ValidationError): Budget(**budget)
    for patch in ({'recorded_at':'2026-09-22T10:00:00'}, {'output_sha256':'bad'}, {'status':'unknown'}, {'source_refs':[]}):
        with pytest.raises(ValidationError): EvidenceReceipt(**{**receipt(), **patch})


def test_checkpoint_and_grant_validity():
    checkpoint = dict(execution_id='e1',intent_id='i1',step_id='s1',capability_id='search',capability_version='1',
                      idempotency_key='key',input_sha256=DIGEST,state='started',attempt=1,recorded_at=TIME,permission_receipt_ref='p1')
    assert StepCheckpoint(**checkpoint).output_sha256 is None
    with pytest.raises(ValidationError): StepCheckpoint(**{**checkpoint,'state':'completed'})
    assert StepCheckpoint(**{**checkpoint,'state':'completed','output_sha256':DIGEST,'evidence_receipt_ref':'r1'})
    grant = dict(grant_id='g1',intent_id='i1',principal='user',issuer='issuer',capability_id='search',capability_version='1',
                 action='search',resource='records',input_sha256=DIGEST,budget={'max_tool_calls':1,'max_duration_ms':10},
                 issued_at=TIME,expires_at=TIME,approval_receipt_ref='approval',signature_ref='signature')
    with pytest.raises(ValidationError): PermissionGrant(**grant)
    assert PermissionGrant(**{**grant,'expires_at':'2026-09-22T11:00:00Z'})