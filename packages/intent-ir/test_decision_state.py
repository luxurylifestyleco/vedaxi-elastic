"""Provider-neutral decision inputs preserve identity without granting authority."""
from copy import deepcopy

import pytest

from decision_state import DecisionCandidate, DecisionState


def sample():
    return {"case_id": "capability.select", "inputs": {"request": "Find papers", "n": 2},
            "candidates": [{"id": "research:crossref", "description": "Find published research"}]}


def test_digest_is_canonical_and_tracks_content():
    raw = sample()
    state = DecisionState.model_validate(raw)
    reordered = deepcopy(raw)
    reordered["inputs"] = {"n": 2, "request": "Find papers"}
    assert state.content_sha256() == DecisionState.model_validate(reordered).content_sha256()
    assert len(state.content_sha256()) == 64
    assert int(state.content_sha256(), 16) >= 0
    reordered["inputs"]["n"] = 3
    assert state.content_sha256() != DecisionState.model_validate(reordered).content_sha256()
    assert set(state.model_dump()) == {"schema_version", "case_id", "intent_revision", "inputs", "candidates"}


@pytest.mark.parametrize("change", [
    {"case_id": ""}, {"case_id": "has spaces"}, {"case_id": "x" * 129},
    {"intent_revision": True}, {"intent_revision": "1"}, {"intent_revision": 0},
    {"model": "jev-1.13.0"}, {"questions": {}}, {"authorization": "approved"},
    {"inputs": {"nested": [float("nan")]}},
    {"inputs": {"nested": {"n": float("inf")}}},
    {"inputs": {"n": -float("inf")}},
    {"inputs": {"not_json": object()}},
])
def test_invalid_state_cannot_cross_boundary(change):
    with pytest.raises(ValueError):
        DecisionState.model_validate({**sample(), **change})


@pytest.mark.parametrize("candidate", [
    {"id": "__none__", "description": "reserved"},
    {"id": "bad id", "description": "invalid"},
    {"id": "ok", "description": " "},
    {"id": "ok", "description": "x" * 4001},
    {"id": "ok", "description": "valid", "attributes": {"n": float("nan")}},
    {"id": "ok", "description": "valid", "approved": True},
])
def test_invalid_candidate_rejected(candidate):
    with pytest.raises(ValueError):
        DecisionCandidate.model_validate(candidate)


def test_candidate_limit_and_duplicates():
    raw = sample()
    raw["candidates"] *= 2
    with pytest.raises(ValueError):
        DecisionState.model_validate(raw)
    raw["candidates"] = [{"id": f"c{i}", "description": "Candidate"} for i in range(254)]
    assert len(DecisionState.model_validate(raw).candidates) == 254
    raw["candidates"].append({"id": "overflow", "description": "Candidate"})
    with pytest.raises(ValueError):
        DecisionState.model_validate(raw)
