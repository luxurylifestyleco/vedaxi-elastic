"""Disposable HTTP provider that publishes one signed receipt for local proof."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from provider import (
    FakeProvider,
    LocalTrustRoot,
    ProviderExecutionRequest,
    sign_receipt,
)
from recovery import OperationIdentity


TRUST_ROOT = LocalTrustRoot("synthetic-provider", b"synthetic-provider-fixture-key")
REQUEST = ProviderExecutionRequest(
    operation=OperationIdentity(
        tenant_id="smoke-tenant",
        outcome_id="smoke-outcome",
        execution_id="smoke-execution",
        step_id="smoke-step",
        request_digest="smoke-request-digest",
        operation_key="smoke-operation",
    ),
    provider_id="synthetic-provider",
    protocol="fixture-http",
    capability_id="synthetic.search",
    input_digest="smoke-input-digest",
)
RECEIPT = FakeProvider("synthetic-provider").execute(REQUEST)
DOCUMENT = {
    "receipt": RECEIPT.model_dump(mode="json"),
    "signature": sign_receipt(RECEIPT, TRUST_ROOT),
    "issuer": TRUST_ROOT.issuer_id,
    "trust_root": "fixture-configured",
}


class ProviderFixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/receipt":
            body = json.dumps(DOCUMENT).encode()
            content_type = "application/json"
        elif self.path == "/":
            body = (
                "<!doctype html><meta charset='utf-8'>"
                "<title>Synthetic Provider</title>"
                "<h1>Synthetic Provider</h1>"
                "<p>Disposable signed-receipt fixture.</p>"
                "<a href='/receipt'>Fetch signed receipt</a>"
            ).encode()
            content_type = "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        return None


def create_server(host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), ProviderFixtureHandler)
