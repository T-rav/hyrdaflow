"""Tests for the CodeGroomingLoop background worker."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from code_grooming_loop import CodeGroomingLoop
from tests.helpers import ConfigFactory, make_bg_loop_deps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    dry_run: bool = False,
    code_grooming_interval: int = 86400,
    existing_dedup: list[str] | None = None,
) -> tuple[CodeGroomingLoop, AsyncMock, asyncio.Event]:
    """Build a CodeGroomingLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(
        tmp_path,
        enabled=enabled,
        dry_run=dry_run,
        code_grooming_interval=code_grooming_interval,
    )
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)

    # Seed dedup store file if needed
    dedup_path = deps.config.data_root / "memory" / "code_grooming_dedup.json"
    if existing_dedup:
        dedup_path.parent.mkdir(parents=True, exist_ok=True)
        dedup_path.write_text(json.dumps(existing_dedup))

    loop = CodeGroomingLoop(
        config=deps.config,
        pr_manager=pr_manager,
        deps=deps.loop_deps,
    )
    return loop, pr_manager, deps.stop_event


# ===========================================================================
# Tests
# ===========================================================================


class TestCodeGroomingLoopBasics:
    def test_worker_name(self, tmp_path: Path) -> None:
        loop, _pm, _stop = _make_loop(tmp_path)
        assert loop._worker_name == "code_grooming"

    def test_default_interval_from_config(self, tmp_path: Path) -> None:
        loop, _pm, _stop = _make_loop(tmp_path, code_grooming_interval=43200)
        assert loop._get_default_interval() == 43200

    def test_default_interval_config_field(self) -> None:
        config = ConfigFactory.create(code_grooming_interval=86400)
        assert config.code_grooming_interval == 86400


class TestCodeGroomingLoopWork:
    @pytest.mark.asyncio
    async def test_no_findings_returns_zero(self, tmp_path: Path) -> None:
        loop, pm, _stop = _make_loop(tmp_path)
        # Mock the agent to return no findings
        with patch.object(loop, "_run_audit", new_callable=AsyncMock, return_value=[]):
            result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_critical_finding_files_issue(self, tmp_path: Path) -> None:
        finding = {
            "id": "dead-code-auth-module",
            "severity": "critical",
            "title": "Dead code in auth module",
            "description": "Unused function handle_legacy_auth in src/auth.py",
        }
        loop, pm, _stop = _make_loop(tmp_path)
        with patch.object(
            loop, "_run_audit", new_callable=AsyncMock, return_value=[finding]
        ):
            result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 1
        pm.create_issue.assert_called_once()
        call_args = pm.create_issue.call_args
        assert "[Code Grooming]" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_duplicate_finding_skipped(self, tmp_path: Path) -> None:
        finding = {
            "id": "dead-code-auth-module",
            "severity": "high",
            "title": "Dead code in auth module",
            "description": "Unused function",
        }
        loop, pm, _stop = _make_loop(tmp_path, existing_dedup=["dead-code-auth-module"])
        with patch.object(
            loop, "_run_audit", new_callable=AsyncMock, return_value=[finding]
        ):
            result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        assert result["skipped_dedup"] == 1
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_returns_none(self, tmp_path: Path) -> None:
        loop, pm, _stop = _make_loop(tmp_path, dry_run=True)
        result = await loop._do_work()
        assert result is None
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_agent_failure_caught_gracefully(self, tmp_path: Path) -> None:
        loop, pm, _stop = _make_loop(tmp_path)
        with patch.object(
            loop,
            "_run_audit",
            new_callable=AsyncMock,
            side_effect=RuntimeError("agent crashed"),
        ):
            result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        assert result["error"] is True
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_low_severity_finding_skipped(self, tmp_path: Path) -> None:
        finding = {
            "id": "minor-style-issue",
            "severity": "low",
            "title": "Minor style issue",
            "description": "Inconsistent naming",
        }
        loop, pm, _stop = _make_loop(tmp_path)
        with patch.object(
            loop, "_run_audit", new_callable=AsyncMock, return_value=[finding]
        ):
            result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        assert result["skipped_severity"] == 1
