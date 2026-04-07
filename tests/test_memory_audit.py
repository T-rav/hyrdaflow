"""Tests for memory_audit.MemoryAuditor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from hindsight import Bank
from memory_audit import _AUDIT_PROMPT, MemoryAuditor


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


@pytest.mark.asyncio()
async def test_audit_bank_calls_reflect(
    auditor: MemoryAuditor, mock_client: AsyncMock
) -> None:
    """audit_bank calls reflect with the correct bank and query."""
    result = await auditor.audit_bank(Bank.TRIBAL)

    mock_client.reflect.assert_awaited_once_with(Bank.TRIBAL, _AUDIT_PROMPT)
    assert result["bank"] == str(Bank.TRIBAL)
    assert result["reflection"] == "reflection text"
    assert "timestamp" in result


@pytest.mark.asyncio()
async def test_audit_all_audits_all_banks(
    auditor: MemoryAuditor, mock_client: AsyncMock
) -> None:
    """audit_all iterates over every Bank member."""
    results = await auditor.audit_all()

    assert len(results) == len(Bank)
    assert mock_client.reflect.await_count == len(Bank)
    bank_ids = {r["bank"] for r in results}
    assert bank_ids == {str(b) for b in Bank}


@pytest.mark.asyncio()
async def test_audit_all_continues_on_failure(
    auditor: MemoryAuditor, mock_client: AsyncMock
) -> None:
    """audit_all skips failing banks and continues with the rest."""
    banks_list = list(Bank)
    failing_bank = banks_list[0]

    async def _side_effect(bank: Bank, query: str) -> str:
        if bank == failing_bank:
            raise RuntimeError("boom")
        return "ok"

    mock_client.reflect = AsyncMock(side_effect=_side_effect)

    results = await auditor.audit_all()

    # One bank failed, so we should get len(Bank) - 1 results
    assert len(results) == len(banks_list) - 1
    returned_banks = {r["bank"] for r in results}
    assert str(failing_bank) not in returned_banks
