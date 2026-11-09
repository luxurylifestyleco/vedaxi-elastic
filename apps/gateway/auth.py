"""Provider-neutral authentication adapter for the gateway transport boundary."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any


_BEARER_TOKEN = re.compile(r"^[A-Za-z0-9\-._~+/]+=*$")


class BearerAuthAdapter:
    """Keep bearer parsing at the gateway and delegate trust to a validator.

    The validator must independently verify the token (for example, its
    signature, issuer, audience, expiry, and revocation state). Without one,
    this adapter rejects every request.
    """

    def __init__(self, validator: Callable[[str], bool] | None = None) -> None:
        self._validator = validator

    def authenticate(self, headers: Mapping[str, Any]) -> bool:
        if not callable(self._validator):
            return False

        authorization = next(
            (value for name, value in headers.items() if name.casefold() == "authorization"),
            None,
        )
        if not isinstance(authorization, str):
            return False
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.casefold() != "bearer" or not _BEARER_TOKEN.fullmatch(token):
            return False
        try:
            return self._validator(token) is True
        except Exception:  # noqa: BLE001 - authentication must fail closed.
            return False
