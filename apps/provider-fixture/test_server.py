from __future__ import annotations

import json
import os
import sys
import threading
import urllib.request

_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_ASSURANCE_DIR = os.path.abspath(os.path.join(_APP_DIR, "..", "..", "packages", "assurance-protocol"))
if _ASSURANCE_DIR not in sys.path:
    sys.path.insert(0, _ASSURANCE_DIR)

from provider import ProviderReceipt, ReceiptVerificationStatus, verify_provider_receipt, verify_receipt_signature  # noqa: E402
from server import DOCUMENT, REQUEST, TRUST_ROOT, create_server  # noqa: E402


def test_web_provider_receipt_is_fetched_and_verified_over_http():
    httpd = create_server()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        with urllib.request.urlopen(f"{base}/") as response:
            assert response.status == 200
            assert "Synthetic Provider" in response.read().decode()
        with urllib.request.urlopen(f"{base}/receipt") as response:
            payload = json.loads(response.read().decode())
        receipt = ProviderReceipt.model_validate(payload["receipt"])
        assert verify_provider_receipt(
            REQUEST, receipt, expected_issuer_id=TRUST_ROOT.issuer_id
        ).status is ReceiptVerificationStatus.VERIFIED
        assert verify_receipt_signature(
            receipt, payload["signature"], trust_root=TRUST_ROOT
        ).status is ReceiptVerificationStatus.VERIFIED
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_web_provider_tampering_is_rejected():
    receipt = ProviderReceipt.model_validate(DOCUMENT["receipt"])
    result = verify_receipt_signature(receipt, "0" * 64, trust_root=TRUST_ROOT)
    assert result.status is ReceiptVerificationStatus.REJECTED
