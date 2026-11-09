from __future__ import annotations

import pytest

from api_discovery import APIDiscoveryAdapter
from capability import Capability
from registry import CapabilityRegistry


OPENAPI = {
    "openapi": "3.0.3",
    "info": {"title": "Fixture API", "version": "1.0.0"},
    "servers": [{"url": "https://fixture.test/v1"}],
    "paths": {"/pets/{pet_id}": {"get": {
        "operationId": "get_pet",
        "summary": "Get a pet",
        "parameters": [{"name": "pet_id", "in": "path", "required": True, "schema": {"type": "string"}}],
        "responses": {"200": {"content": {"application/json": {"schema": {"type": "object", "properties": {"name": {"type": "string"}}}}}}},
    }}}
}

ASYNCAPI = {
    "asyncapi": "2.6.0",
    "info": {"title": "Events", "version": "1.0.0"},
    "servers": [{"url": "mqtt://fixture.test"}],
    "channels": {"pets/updated": {"publish": {
        "operationId": "publish_pet_update",
        "message": {"payload": {"type": "object", "properties": {"pet_id": {"type": "string"}}, "required": ["pet_id"]}},
    }}},
}

ASYNCAPI3 = {
    "asyncapi": "3.0.0",
    "info": {"title": "Events", "version": "1.0.0"},
    "channels": {"pets.updated": {"address": "pets.updated"}},
    "operations": {"receive_pet_update": {
        "action": "receive",
        "channel": {"address": "pets.updated"},
        "messages": [{"payload": {"type": "object", "properties": {"pet_id": {"type": "string"}}}}],
    }},
}

OPENAPI_COMPONENT_REFS = {
    "openapi": "3.0.3",
    "info": {"title": "Referenced API", "version": "1.0.0"},
    "servers": [{"url": "https://fixture.test/v1"}],
    "paths": {"/pets": {"post": {
        "operationId": "create_pet",
        "parameters": [{"$ref": "#/components/parameters/TraceId"}],
        "requestBody": {"$ref": "#/components/requestBodies/Pet"},
        "responses": {"200": {"$ref": "#/components/responses/Pet"}},
    }}},
    "components": {
        "parameters": {"TraceId": {
            "name": "trace_id", "in": "header", "required": True,
            "schema": {"$ref": "#/components/schemas/TraceId"},
        }},
        "requestBodies": {"Pet": {
            "required": True,
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}},
        }},
        "responses": {"Pet": {
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}},
        }},
        "schemas": {
            "TraceId": {"type": "string"},
            "Pet": {"type": "object", "properties": {"name": {"type": "string"}}},
        },
    },
}


def test_openapi_fixture_normalizes_and_registers():
    adapter = APIDiscoveryAdapter(OPENAPI, provider="fixture-provider", domain="pets")
    registry = CapabilityRegistry()
    caps = adapter.register(registry)
    assert len(caps) == 1
    cap = registry.get_by_id("get_pet")
    assert isinstance(cap, Capability)
    assert cap.protocol == "openapi"
    assert cap.endpoint == "https://fixture.test/v1/pets/{pet_id}"
    assert cap.inputs["pet_id"]["required"] is True
    assert cap.outputs == {"name": "string"}


def test_asyncapi_fixture_normalizes_channel_payload():
    cap = APIDiscoveryAdapter(ASYNCAPI).discover()[0]
    assert cap.id == "publish_pet_update"
    assert cap.protocol == "asyncapi"
    assert cap.endpoint == "pets/updated"
    assert cap.inputs["pet_id"]["required"] is True


def test_asyncapi_3_fixture_normalizes_receive_payload():
    cap = APIDiscoveryAdapter(ASYNCAPI3).discover()[0]
    assert cap.id == "receive_pet_update"
    assert cap.outputs == {"pet_id": {"type": "string", "required": False}}
    assert cap.endpoint == "pets.updated"


def test_openapi_component_refs_are_resolved_at_discovery_boundary():
    cap = APIDiscoveryAdapter(OPENAPI_COMPONENT_REFS).discover()[0]
    assert cap.id == "create_pet"
    assert cap.inputs["trace_id"]["type"] == "string"
    assert cap.inputs["name"]["required"] is True
    assert cap.outputs == {"name": "string"}


def test_malformed_and_unsupported_documents_fail_closed():
    with pytest.raises(ValueError, match="expected a JSON mapping"):
        APIDiscoveryAdapter([]).discover()
    with pytest.raises(ValueError, match="unsupported OpenAPI"):
        APIDiscoveryAdapter({"openapi": "2.0", "paths": {}}).discover()
    with pytest.raises(ValueError, match="paths must be an object"):
        APIDiscoveryAdapter({"openapi": "3.0.0", "paths": []}).discover()


def test_ids_are_deterministic_for_same_fixture():
    first = [cap.id for cap in APIDiscoveryAdapter(OPENAPI).discover()]
    second = [cap.id for cap in APIDiscoveryAdapter(dict(OPENAPI)).discover()]
    assert first == second == ["get_pet"]
