"""Regression test for issue #6651.

Bug: The ``POST /api/webhooks/whatsapp`` endpoint documents that it validates
the request signature using the WhatsApp app secret (docstring line 2058,
comment line 2064 "Signature verification: reject unsigned or forged
requests"), but no ``X-Hub-Signature-256`` header check is implemented.

Any caller that knows the endpoint URL can inject arbitrary webhook payloads
and forge WhatsApp replies for active shape conversations, causing the shape
phase to advance with spoofed human input.

Expected behaviour after fix:
  - Requests missing the ``X-Hub-Signature-256`` header are rejected with 403.
  - Requests with an invalid HMAC signature are rejected with 403.
  - Only requests with a valid HMAC-SHA256 signature (computed over the raw
    request body using the ``whatsapp_app_secret``) are accepted.

These tests assert the CORRECT (post-fix) behaviour and are therefore RED
against the current buggy code.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import (
    CredentialsFactory,
    find_endpoint,
    make_dashboard_router,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WHATSAPP_APP_SECRET = "test-whatsapp-app-secret"

VALID_WEBHOOK_PAYLOAD = {
    "entry": [
        {
            "changes": [
                {"value": {"messages": [{"text": {"body": "Looks good, ship it #42"}}]}}
            ]
        }
    ]
}


def _make_signature(body: bytes, secret: str) -> str:
    """Compute the X-Hub-Signature-256 header value Meta would send."""
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def _make_request(
    payload: dict,
    *,
    signature_header: str | None = None,
) -> MagicMock:
    """Build a mock ``Request`` with an optional X-Hub-Signature-256 header."""
    body_bytes = json.dumps(payload).encode()
    request = MagicMock()
    request.json = AsyncMock(return_value=payload)
    request.body = AsyncMock(return_value=body_bytes)

    headers: dict[str, str] = {"content-type": "application/json"}
    if signature_header is not None:
        headers["x-hub-signature-256"] = signature_header
    request.headers = headers
    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWhatsAppWebhookSignatureVerification:
    """Issue #6651: POST /api/webhooks/whatsapp must verify X-Hub-Signature-256."""

    @pytest.mark.asyncio
    async def test_missing_signature_header_returns_403(
        self,
        config,
        event_bus,
        state,
        tmp_path,
    ) -> None:
        """A request with no X-Hub-Signature-256 header must be rejected.

        Currently FAILS because the endpoint performs zero signature
        verification — the request is accepted and the spoofed message is
        stored as a shape response.
        """
        config.whatsapp_enabled = True
        router, pr_mgr = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            credentials=CredentialsFactory.create(
                whatsapp_token="tok",
                whatsapp_verify_token="vfy",
            ),
        )
        pr_mgr.post_comment = AsyncMock()

        handler = find_endpoint(router, "/api/webhooks/whatsapp", "POST")
        assert handler is not None

        request = _make_request(VALID_WEBHOOK_PAYLOAD, signature_header=None)
        response = await handler(request)

        assert response.status_code == 403, (
            f"Expected 403 for missing X-Hub-Signature-256 header, "
            f"got {response.status_code}. The endpoint accepts unsigned "
            f"webhook payloads, allowing anyone to spoof WhatsApp messages "
            f"into active shape conversations (issue #6651)."
        )

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_403(
        self,
        config,
        event_bus,
        state,
        tmp_path,
    ) -> None:
        """A request with a wrong HMAC signature must be rejected.

        Currently FAILS because no signature check exists at all.
        """
        config.whatsapp_enabled = True
        router, pr_mgr = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            credentials=CredentialsFactory.create(
                whatsapp_token="tok",
                whatsapp_verify_token="vfy",
            ),
        )
        pr_mgr.post_comment = AsyncMock()

        handler = find_endpoint(router, "/api/webhooks/whatsapp", "POST")
        assert handler is not None

        request = _make_request(
            VALID_WEBHOOK_PAYLOAD,
            signature_header="sha256=deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        )
        response = await handler(request)

        assert response.status_code == 403, (
            f"Expected 403 for invalid X-Hub-Signature-256 header, "
            f"got {response.status_code}. The endpoint ignores the signature "
            f"entirely — forged payloads are processed as legitimate "
            f"WhatsApp messages (issue #6651)."
        )

    @pytest.mark.asyncio
    async def test_unsigned_request_stores_spoofed_response(
        self,
        config,
        event_bus,
        state,
        tmp_path,
    ) -> None:
        """Demonstrate the spoofing impact: an unsigned request writes to state.

        This test shows the concrete harm — a forged payload injects text
        into the shape response store, which the ShapePhase will pick up as
        if it were a genuine human reply.

        After the fix this test should PASS (the request should be rejected
        before reaching set_shape_response).
        """
        config.whatsapp_enabled = True
        router, pr_mgr = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            credentials=CredentialsFactory.create(
                whatsapp_token="tok",
                whatsapp_verify_token="vfy",
            ),
        )
        pr_mgr.post_comment = AsyncMock()

        handler = find_endpoint(router, "/api/webhooks/whatsapp", "POST")
        assert handler is not None

        # Send a completely unsigned request with a spoofed payload
        request = _make_request(VALID_WEBHOOK_PAYLOAD, signature_header=None)
        await handler(request)

        # The bug: the spoofed message was accepted and stored
        spoofed_response = state.get_shape_response(42)
        assert spoofed_response is None, (
            f"An unsigned (potentially spoofed) webhook payload was accepted "
            f"and stored as a shape response: {spoofed_response!r}. "
            f"Without X-Hub-Signature-256 verification, any caller can inject "
            f"forged WhatsApp messages into active shape conversations "
            f"(issue #6651)."
        )
