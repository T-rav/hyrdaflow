"""Regression test for issue #6987.

``MemoryAuditor.audit_all`` iterates every memory bank inside a broad
``except Exception`` handler (memory_audit.py:50).  When ``audit_bank``
raises ``AuthenticationError`` or ``CreditExhaustedError`` — both
``RuntimeError`` subclasses — the error is logged at WARNING level and
the next bank is processed.  The orchestrator never learns that
credentials are invalid, and the audit loop keeps burning API calls.

Strategy
--------
Mock the Hindsight client's ``reflect`` to raise ``AuthenticationError``
(or ``CreditExhaustedError``).  Call ``audit_all`` and assert that the
exception propagates.  Today the broad ``except Exception`` catches it
and returns partial results — the test therefore fails, proving the bug.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from memory_audit import MemoryAuditor
from subprocess_util import AuthenticationError, CreditExhaustedError


@pytest.fixture()
def mock_client() -> AsyncMock:
    client = AsyncMock()
    client.reflect = AsyncMock(return_value="reflection text")
    return client


@pytest.fixture()
def mock_config() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def auditor(mock_client: AsyncMock, mock_config: MagicMock) -> MemoryAuditor:
    return MemoryAuditor(mock_client, mock_config)


class TestAuthErrorPropagatesFromAuditAll:
    """AuthenticationError must not be silently swallowed by audit_all."""

    @pytest.mark.asyncio
    async def test_authentication_error_propagates(
        self, auditor: MemoryAuditor, mock_client: AsyncMock
    ) -> None:
        """When reflect raises AuthenticationError, audit_all must let it
        propagate rather than catching it as a per-bank warning.

        BUG: The broad ``except Exception`` at memory_audit.py:50 catches
        AuthenticationError, logs a warning, and continues to the next bank.
        This test expects the exception to propagate — it will fail (RED)
        until the handler is fixed to re-raise auth errors.
        """
        mock_client.reflect = AsyncMock(
            side_effect=AuthenticationError("gh: authentication required"),
        )

        with pytest.raises(AuthenticationError):
            await auditor.audit_all()

    @pytest.mark.asyncio
    async def test_credit_exhausted_error_propagates(
        self, auditor: MemoryAuditor, mock_client: AsyncMock
    ) -> None:
        """When reflect raises CreditExhaustedError, audit_all must let it
        propagate rather than catching it as a per-bank warning.

        BUG: Same broad ``except Exception`` swallows CreditExhaustedError.
        """
        mock_client.reflect = AsyncMock(
            side_effect=CreditExhaustedError("API credits exhausted"),
        )

        with pytest.raises(CreditExhaustedError):
            await auditor.audit_all()

    @pytest.mark.asyncio
    async def test_value_error_propagates_via_reraise(
        self, auditor: MemoryAuditor, mock_client: AsyncMock
    ) -> None:
        """ValueError is a likely-bug exception and should also propagate
        via reraise_on_credit_or_bug rather than being silently caught.

        BUG: The broad handler also swallows likely-bug exceptions.
        """
        mock_client.reflect = AsyncMock(
            side_effect=ValueError("unexpected None in bank data"),
        )

        with pytest.raises(ValueError, match="unexpected None"):
            await auditor.audit_all()
