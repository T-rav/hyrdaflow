"""Tests for park_issue helper in phase_utils."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from phase_utils import park_issue


class TestParkIssue:
    @pytest.mark.asyncio
    async def test_park_issue_swaps_to_parked_label(self) -> None:
        prs = AsyncMock()
        prs.swap_pipeline_labels = AsyncMock()
        prs.post_comment = AsyncMock()

        await park_issue(
            prs,
            issue_number=42,
            parked_label="hydraflow-parked",
            reasons=["Missing acceptance criteria", "No repro steps"],
        )

        prs.swap_pipeline_labels.assert_awaited_once_with(42, "hydraflow-parked")
        prs.post_comment.assert_awaited_once()
        comment = prs.post_comment.call_args.args[1]
        assert "Needs More Information" in comment
        assert "Missing acceptance criteria" in comment
        assert "No repro steps" in comment
        assert "re-apply" in comment

    @pytest.mark.asyncio
    async def test_park_issue_includes_all_reasons(self) -> None:
        prs = AsyncMock()
        prs.swap_pipeline_labels = AsyncMock()
        prs.post_comment = AsyncMock()

        reasons = ["Reason A", "Reason B", "Reason C"]
        await park_issue(
            prs,
            issue_number=10,
            parked_label="hydraflow-parked",
            reasons=reasons,
        )

        comment = prs.post_comment.call_args.args[1]
        for r in reasons:
            assert r in comment
