"""Session rules for the inbound A2A peer. No gateway, no executor."""

from __future__ import annotations

import pytest

from adapters.a2a.peer import A2APeer, SessionDenied


def test_card_publishes_switch_skill_only():
    card = A2APeer().agent_card("http://127.0.0.1/rpc")
    skill_ids = [skill["id"] for skill in card["skills"]]
    assert skill_ids == ["route_intent"]
    assert "get_balance" not in skill_ids
    assert card["capabilities"]["streaming"] is False
    assert card["capabilities"]["pushNotifications"] is False


def test_unknown_or_foreign_session_does_not_resolve():
    peer = A2APeer()
    context_id = peer.accept("owner", {"message": {"role": "ROLE_USER"}})
    with pytest.raises(SessionDenied):
        peer.accept("owner", {"message": {"contextId": "ctx-missing"}})
    with pytest.raises(SessionDenied):
        peer.accept("other", {"message": {"contextId": context_id}})
    with pytest.raises(SessionDenied):
        peer.get_session("other", context_id)
    session = peer.get_session("owner", context_id)
    assert session["contextId"] == context_id
    assert len(session["turns"]) == 1


def test_session_id_alias_is_not_a_second_store():
    peer = A2APeer()
    minted = peer.accept("owner", {"message": {"metadata": {"sessionId": ""}}})
    assert minted.startswith("ctx-")
    with pytest.raises(SessionDenied):
        peer.accept("owner", {"message": {"metadata": {"sessionId": "alias-unknown"}}})
    again = peer.accept(
        "owner",
        {"message": {"metadata": {"sessionId": minted}, "role": "ROLE_USER"}},
    )
    assert again == minted
    preferred = peer.accept(
        "owner",
        {"message": {"contextId": minted, "metadata": {"sessionId": "ignored"}}},
    )
    assert preferred == minted
