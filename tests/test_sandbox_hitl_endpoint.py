"""/api/sandbox-hitl returns sandbox-hitl-labeled PRs.

Companion to ``SandboxFailureFixerLoop`` (Task 3.12): when the loop hits
the 3-attempt auto-fix cap it swaps the ``sandbox-fail-auto-fix`` label
for ``sandbox-hitl`` and the dashboard surfaces those PRs through this
endpoint. Kept separate from ``/api/hitl`` so PR-shaped payloads don't
contaminate the issue-shaped contract there.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from dashboard_routes._hitl_routes import sandbox_hitl_handler


@pytest.mark.asyncio
async def test_sandbox_hitl_returns_labeled_prs() -> None:
    """Handler exposes the PRs returned by list_prs_by_label as items."""
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(
        return_value=[
            MagicMock(
                number=100,
                branch="rc/2026-04-26",
                url="https://github.com/org/repo/pull/100",
                draft=False,
            ),
        ]
    )

    payload = await sandbox_hitl_handler(prs=pr_port)

    assert "items" in payload
    assert len(payload["items"]) == 1
    assert payload["items"][0]["number"] == 100
    assert payload["items"][0]["type"] == "pr"
    assert payload["items"][0]["label"] == "sandbox-hitl"
    assert payload["items"][0]["branch"] == "rc/2026-04-26"


@pytest.mark.asyncio
async def test_sandbox_hitl_empty_when_no_labeled_prs() -> None:
    """Handler returns an empty items list when no PRs carry the label."""
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(return_value=[])

    payload = await sandbox_hitl_handler(prs=pr_port)

    assert payload == {"items": []}


@pytest.mark.asyncio
async def test_sandbox_hitl_calls_pr_port_with_correct_label() -> None:
    """Handler queries PRPort.list_prs_by_label exclusively for `sandbox-hitl`."""
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(return_value=[])

    await sandbox_hitl_handler(prs=pr_port)

    pr_port.list_prs_by_label.assert_called_once_with("sandbox-hitl")
