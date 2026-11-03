from __future__ import annotations

import pytest

from webmcp_boundary import WebMCPBoundary


ORIGIN = "https://shop.example/tools"


def test_webmcp_register_invoke_and_remove_are_correlated_to_origin():
    boundary = WebMCPBoundary(ORIGIN)
    assert boundary.register("search", lambda args: {"query": args["query"]}, origin=ORIGIN)["status"] == "registered"
    assert boundary.invoke("search", {"query": "shoes"}, origin="https://shop.example/other") == {"query": "shoes"}
    assert boundary.remove("search", origin=ORIGIN)["status"] == "removed"
    assert boundary.registered_tools() == ()


def test_webmcp_rejects_wrong_origin_and_does_not_execute():
    calls = []
    boundary = WebMCPBoundary(ORIGIN)
    boundary.register("search", lambda args: calls.append(args), origin=ORIGIN)
    with pytest.raises(PermissionError, match="origin"):
        boundary.invoke("search", {}, origin="https://evil.example")
    with pytest.raises(PermissionError, match="origin"):
        boundary.remove("search", origin="https://evil.example")
    assert calls == []


def test_webmcp_rejects_duplicate_and_unknown_tools():
    boundary = WebMCPBoundary(ORIGIN)
    boundary.register("search", lambda _: None, origin=ORIGIN)
    with pytest.raises(ValueError, match="already registered"):
        boundary.register("search", lambda _: None, origin=ORIGIN)
    with pytest.raises(KeyError, match="not registered"):
        boundary.invoke("missing", {}, origin=ORIGIN)
