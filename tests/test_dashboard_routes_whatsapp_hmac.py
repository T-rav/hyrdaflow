"""Unit tests for WhatsApp webhook HMAC-SHA256 signature verification.

Covers the X-Hub-Signature-256 verification introduced to fix issue #6651.
These tests are distinct from tests/regressions/test_issue_6651.py, which
anchors the original bug report.  These tests validate the full behaviour of
the fixed endpoint including the valid-signature happy path.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.helpers import (
    CredentialsFactory,
    find_endpoint,
    make_dashboard_router,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_APP_SECRET = "unit-test-app-secret"

_VALID_PAYLOAD = {
    "entry": [
        {
            "changes": [
                {"value": {"messages": [{"text": {"body": "LGTM, ship it #99"}}]}}
            ]
        }
    ]
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sig(body: bytes, secret: str) -> str:
    """Compute the X-Hub-Signature-256 header value Meta would send."""
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def _make_request(
    payload: dict,
    *,
    signature_header: str | None,
) -> MagicMock:
    """Build a mock Request with an optional X-Hub-Signature-256 header."""
    body_bytes = json.dumps(payload).encode()
    request = MagicMock()
    request.body = AsyncMock(return_value=body_bytes)
    request.json = AsyncMock(return_value=payload)

    headers: dict[str, str] = {"content-type": "application/json"}
    if signature_header is not None:
        headers["x-hub-signature-256"] = signature_header
    request.headers = headers
    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWhatsAppWebhookHMAC:
    """Unit tests for HMAC-SHA256 verification on POST /api/webhooks/whatsapp."""

    @pytest.mark.asyncio
    async def test_missing_header_returns_403(
        self,
        config,
        event_bus,
        state,
        tmp_path,
    ) -> None:
        """No X-Hub-Signature-256 header → 403 Forbidden."""
        config.whatsapp_enabled = True
        router, _ = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            credentials=CredentialsFactory.create(
                whatsapp_token="tok",
                whatsapp_app_secret=_APP_SECRET,
            ),
        )

        handler = find_endpoint(router, "/api/webhooks/whatsapp", "POST")
        assert handler is not None

        request = _make_request(_VALID_PAYLOAD, signature_header=None)
        response = await handler(request)

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_forged_body_returns_403(
        self,
        config,
        event_bus,
        state,
        tmp_path,
    ) -> None:
        """Signature computed over a *different* body → 403 Forbidden.

        Simulates a MITM attacker that sends a valid signature header from a
        prior request but swaps the body for a forged payload.
        """
        config.whatsapp_enabled = True
        router, _ = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            credentials=CredentialsFactory.create(
                whatsapp_token="tok",
                whatsapp_app_secret=_APP_SECRET,
            ),
        )

        handler = find_endpoint(router, "/api/webhooks/whatsapp", "POST")
        assert handler is not None

        # Signature covers the *original* legitimate body, not _VALID_PAYLOAD.
        legitimate_body = b'{"entry": []}'
        forged_sig = _make_sig(legitimate_body, _APP_SECRET)

        request = _make_request(_VALID_PAYLOAD, signature_header=forged_sig)
        response = await handler(request)

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_wrong_secret_returns_403(
        self,
        config,
        event_bus,
        state,
        tmp_path,
    ) -> None:
        """Signature computed with the wrong secret → 403 Forbidden."""
        config.whatsapp_enabled = True
        router, _ = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            credentials=CredentialsFactory.create(
                whatsapp_token="tok",
                whatsapp_app_secret=_APP_SECRET,
            ),
        )

        handler = find_endpoint(router, "/api/webhooks/whatsapp", "POST")
        assert handler is not None

        body_bytes = json.dumps(_VALID_PAYLOAD).encode()
        bad_sig = _make_sig(body_bytes, "wrong-secret")

        request = _make_request(_VALID_PAYLOAD, signature_header=bad_sig)
        response = await handler(request)

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_valid_signature_returns_200(
        self,
        config,
        event_bus,
        state,
        tmp_path,
    ) -> None:
        """Request with a correct X-Hub-Signature-256 → 200 OK.

        Requires WhatsApp bridge to successfully parse the payload.
        """
        config.whatsapp_enabled = True
        router, pr_mgr = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            credentials=CredentialsFactory.create(
                whatsapp_token="tok",
                whatsapp_app_secret=_APP_SECRET,
            ),
        )
        pr_mgr.post_comment = AsyncMock()

        handler = find_endpoint(router, "/api/webhooks/whatsapp", "POST")
        assert handler is not None

        body_bytes = json.dumps(_VALID_PAYLOAD).encode()
        valid_sig = _make_sig(body_bytes, _APP_SECRET)

        request = _make_request(_VALID_PAYLOAD, signature_header=valid_sig)

        with patch(
            "whatsapp_bridge.WhatsAppBridge.parse_webhook",
            return_value=("LGTM, ship it #99", 99),
        ):
            response = await handler(request)

        assert response.status_code == 200
