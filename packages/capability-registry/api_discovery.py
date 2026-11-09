"""Offline OpenAPI and AsyncAPI capability discovery."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional

from capability import Capability


class APIDiscoveryAdapter:
    """Turn one already-loaded OpenAPI or AsyncAPI document into capabilities."""

    def __init__(
        self,
        document: Mapping[str, Any],
        provider: str = "api",
        domain: Optional[str] = None,
    ) -> None:
        self.document = document
        self.provider = provider
        self.domain = domain

    def discover(self) -> List[Capability]:
        document = _document(self.document)
        if "openapi" in document:
            version = document["openapi"]
            if not isinstance(version, str) or not version.startswith("3."):
                raise ValueError("unsupported OpenAPI document: expected OpenAPI 3.x")
            return self._openapi(document)
        if "asyncapi" in document:
            version = document["asyncapi"]
            if not isinstance(version, str) or not (version.startswith("2.") or version.startswith("3.")):
                raise ValueError("unsupported AsyncAPI document: expected AsyncAPI 2.x or 3.x")
            return self._asyncapi(document, version)
        raise ValueError("unsupported API document: expected an OpenAPI 3.x or AsyncAPI 2.x/3.x mapping")

    def register(self, registry: Any) -> List[Capability]:
        capabilities = self.discover()
        for capability in capabilities:
            registry.register(capability)
        return capabilities

    def _openapi(self, document: Mapping[str, Any]) -> List[Capability]:
        paths = _mapping(document.get("paths"), "OpenAPI paths")
        capabilities: List[Capability] = []
        for path, path_item in paths.items():
            if not isinstance(path, str) or not isinstance(path_item, Mapping):
                raise ValueError("malformed OpenAPI document: each path must map to an object")
            for method, operation in path_item.items():
                if method.lower() not in {"get", "put", "post", "patch", "delete", "options", "head", "trace"}:
                    continue
                operation = _mapping(operation, f"OpenAPI operation {method} {path}")
                operation_id = operation.get("operationId")
                if operation_id is not None and (not isinstance(operation_id, str) or not operation_id.strip()):
                    raise ValueError(f"malformed OpenAPI operation {method} {path}: operationId must be a string")
                candidate = operation_id or f"{method.lower()}_{path}"
                inputs = self._parameters(
                    operation.get("parameters", []), f"{method} {path}", document
                )
                body = operation.get("requestBody")
                if body is not None:
                    body = _mapping(
                        _resolve_ref(document, body, f"OpenAPI requestBody {method} {path}"),
                        f"OpenAPI requestBody {method} {path}",
                    )
                    inputs.update(
                        _schema_fields(
                            _content_schema(
                                body.get("content"),
                                document,
                                f"OpenAPI requestBody {method} {path}",
                            ),
                            required=body.get("required", False),
                            document=document,
                        )
                    )
                outputs = _response_fields(
                    operation.get("responses"), f"{method} {path}", document
                )
                capabilities.append(self._capability(
                    "openapi", candidate, operation.get("summary") or operation.get("description"),
                    inputs, outputs, self._endpoint(document, path), method.upper(),
                ))
        if not capabilities:
            raise ValueError("malformed OpenAPI document: no operations found")
        return capabilities

    def _asyncapi(self, document: Mapping[str, Any], version: str) -> List[Capability]:
        capabilities: List[Capability] = []
        if version.startswith("3."):
            operations = _mapping(document.get("operations"), "AsyncAPI operations")
            for key, operation in operations.items():
                operation = _mapping(operation, f"AsyncAPI operation {key}")
                channel = _mapping(_resolve_ref(document, operation.get("channel"), "AsyncAPI channel"), f"AsyncAPI channel for {key}")
                action = operation.get("action")
                if action not in {"send", "receive"}:
                    raise ValueError(f"malformed AsyncAPI operation {key}: action must be send or receive")
                message = operation.get("messages") or operation.get("message")
                if isinstance(message, list):
                    message = message[0] if message else None
                message = _resolve_ref(document, message, "AsyncAPI message")
                endpoint = channel.get("address")
                capabilities.append(self._async_capability(key, operation, action, message, endpoint))
        else:
            channels = _mapping(document.get("channels"), "AsyncAPI channels")
            for channel_name, channel in channels.items():
                channel = _mapping(channel, f"AsyncAPI channel {channel_name}")
                for action in ("publish", "subscribe"):
                    operation = channel.get(action)
                    if operation is None:
                        continue
                    operation = _mapping(operation, f"AsyncAPI {action} {channel_name}")
                    message = _resolve_ref(document, operation.get("message") or channel.get("message"), "AsyncAPI message")
                    capabilities.append(self._async_capability(
                        operation.get("operationId") or f"{action}_{channel_name}",
                        operation, action, message, channel_name,
                    ))
        if not capabilities:
            raise ValueError("malformed AsyncAPI document: no operations found")
        return capabilities

    def _async_capability(self, key: Any, operation: Mapping[str, Any], action: str, message: Any, endpoint: Any) -> Capability:
        message = _mapping(message, f"AsyncAPI message {key}") if message is not None else {}
        payload = message.get("payload", {})
        payload = _mapping(payload, f"AsyncAPI payload {key}") if payload else {}
        inputs = _schema_fields(payload) if action in {"publish", "send"} else {}
        outputs = _schema_fields(payload) if action in {"subscribe", "receive"} else {}
        return self._capability(
            "asyncapi", key, operation.get("summary") or operation.get("description"),
            inputs, outputs, endpoint, action,
        )

    def _parameters(
        self, parameters: Any, label: str, document: Mapping[str, Any]
    ) -> Dict[str, Any]:
        if not isinstance(parameters, list):
            raise ValueError(f"malformed OpenAPI operation {label}: parameters must be a list")
        fields: Dict[str, Any] = {}
        for parameter in parameters:
            parameter = _resolve_ref(document, parameter, f"OpenAPI parameter {label}")
            parameter = _mapping(parameter, f"OpenAPI parameter {label}")
            name = parameter.get("name")
            schema = parameter.get("schema", {})
            if not isinstance(name, str) or not name.strip() or not isinstance(schema, Mapping):
                raise ValueError(f"malformed OpenAPI parameter {label}: name and schema are required")
            fields[name] = _schema_field(
                schema, bool(parameter.get("required")), document
            )
        return fields

    def _capability(self, protocol: str, key: Any, description: Any, inputs: Dict[str, Any], outputs: Dict[str, Any], endpoint: Any, action: str) -> Capability:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("malformed API document: operation identifier must be a non-empty string")
        identifier = key.strip() if re.match(r"^[A-Za-z0-9_.:-]+$", key.strip()) else _slug(key)
        if not identifier:
            raise ValueError("malformed API document: operation identifier is empty")
        return Capability(
            id=identifier,
            name=_humanize(identifier),
            description=str(description or identifier),
            domain=self.domain or str(self.document.get("x-domain") or (_mapping(self.document.get("info", {}), "API info").get("x-domain")) or "api"),
            inputs=inputs,
            outputs=outputs,
            provider=self.provider,
            protocol=protocol,
            endpoint=endpoint if isinstance(endpoint, str) else None,
            metadata={"source": "api-fixture", "action": action},
        )

    def _endpoint(self, document: Mapping[str, Any], path: str) -> Optional[str]:
        servers = document.get("servers", [])
        base = servers[0].get("url") if isinstance(servers, list) and servers and isinstance(servers[0], Mapping) else ""
        return f"{base.rstrip('/')}/{path.lstrip('/')}" if isinstance(base, str) and base else path


def _document(document: Any) -> Mapping[str, Any]:
    if not isinstance(document, Mapping):
        raise ValueError("malformed API document: expected a JSON mapping")
    return document


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"malformed API document: {label} must be an object")
    return value


def _resolve_ref(document: Mapping[str, Any], value: Any, label: str) -> Any:
    if not isinstance(value, Mapping) or "$ref" not in value:
        return value
    reference = value["$ref"]
    if not isinstance(reference, str) or not reference.startswith("#/"):
        raise ValueError(f"malformed API document: {label} reference must be local")
    target: Any = document
    for part in reference[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, Mapping) or part not in target:
            raise ValueError(f"malformed API document: unresolved {label} reference {reference}")
        target = target[part]
    return target


def _content_schema(
    content: Any, document: Mapping[str, Any], label: str = "content"
) -> Mapping[str, Any]:
    content = _mapping(content, "content")
    if not content:
        return {}
    first = next(iter(content.values()))
    media_type = _mapping(first, f"{label} media type")
    return _resolve_ref(document, media_type.get("schema", {}), f"{label} schema")


def _response_fields(
    responses: Any, label: str, document: Mapping[str, Any]
) -> Dict[str, Any]:
    responses = _mapping(responses, f"OpenAPI responses {label}")
    for code, response in responses.items():
        if str(code).startswith("2") or code == "default":
            response = _mapping(
                _resolve_ref(document, response, f"OpenAPI response {label}"),
                f"OpenAPI response {label}",
            )
            return _schema_outputs(
                _content_schema(
                    response.get("content"), document, f"OpenAPI response {label}"
                ),
                document,
            )
    return {}


def _schema_fields(
    schema: Any, required: bool = False, document: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    schema = _mapping(
        _resolve_ref(document, schema, "schema") if document is not None else schema,
        "schema",
    )
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise ValueError("malformed API document: schema properties must be an object")
    required_names = set(schema.get("required", []) or [])
    return {
        name: _schema_field(value, required or name in required_names, document)
        for name, value in properties.items()
        if isinstance(name, str)
    }


def _schema_outputs(
    schema: Any, document: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    schema = _mapping(
        _resolve_ref(document, schema, "schema") if document is not None else schema,
        "schema",
    )
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise ValueError("malformed API document: schema properties must be an object")
    return {
        name: (
            _resolve_ref(document, value, "schema property")
            if document is not None
            else value
        ).get("type", "any")
        for name, value in properties.items()
        if isinstance(name, str) and isinstance(value, Mapping)
    }


def _schema_field(
    schema: Any, required: bool, document: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    schema = _mapping(
        _resolve_ref(document, schema, "schema") if document is not None else schema,
        "schema",
    )
    result = {"type": schema.get("type", "any"), "required": required}
    if "description" in schema:
        result["description"] = schema["description"]
    return result


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()


def _humanize(value: str) -> str:
    return re.sub(r"[_:-]+", " ", value).replace("  ", " ").strip().title()


OpenAPIAdapter = APIDiscoveryAdapter
AsyncAPIAdapter = APIDiscoveryAdapter
