"""API key check for admin endpoints."""

import hmac
from typing import Annotated

from fastapi import Header

from app.deps import SettingsDep
from app.errors import Unauthorized

API_KEY_HEADER = "X-API-Key"


def require_admin(
    settings: SettingsDep,
    x_api_key: Annotated[str, Header(alias=API_KEY_HEADER)] = "",
) -> None:
    """Let the request through only if it carries the configured admin key.

    The key is set with ``LIBRARY_ADMIN_KEY`` and sent in the ``X-API-Key``
    header. Comparison is constant-time.
    """
    expected = settings.admin_api_key.encode()
    if not hmac.compare_digest(x_api_key.strip().encode(), expected):
        raise Unauthorized("missing or invalid API key")
