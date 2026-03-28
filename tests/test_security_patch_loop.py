"""Tests for the SecurityPatchLoop background worker."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from security_patch_loop import SecurityPatchLoop
from tests.helpers import ConfigFactory, make_bg_loop_deps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SEVERITY_ORDER = ["critical", "high", "medium", "low"]


def _make_alert(
    number: int,
    severity: str = "high",
    package: str = "lodash",
    summary: str = "Prototype Pollution",
    first_patched: str | None = "4.17.21",
) -> dict:
    """Build a minimal Dependabot alert dict."""
    vuln = {
        "package": {"name": package, "ecosystem": "npm"},
        "severity": severity,
        "first_patched_version": {"identifier": first_patched}
        if first_patched
        else None,
    }
    return {
        "number": number,
        "state": "open",
        "security_advisory": {"summary": summary},
        "security_vulnerability": vuln,
    }


def _make_loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    dry_run: bool = False,
    severity_threshold: str = "high",
    security_patch_interval: int = 3600,
    alerts: list[dict] | None = None,
    existing_dedup: list[str] | None = None,
) -> tuple[SecurityPatchLoop, AsyncMock, asyncio.Event]:
    """Build a SecurityPatchLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(
        tmp_path,
        enabled=enabled,
        dry_run=dry_run,
        security_patch_interval=security_patch_interval,
        security_patch_severity_threshold=severity_threshold,
    )
    pr_manager = AsyncMock()
    pr_manager.get_dependabot_alerts = AsyncMock(return_value=alerts or [])
    pr_manager.create_issue = AsyncMock(return_value=42)

    # Seed dedup store file if needed
    dedup_path = deps.config.data_root / "memory" / "security_patch_dedup.json"
    if existing_dedup:
        dedup_path.parent.mkdir(parents=True, exist_ok=True)
        dedup_path.write_text(json.dumps(existing_dedup))

    loop = SecurityPatchLoop(
        config=deps.config,
        pr_manager=pr_manager,
        deps=deps.loop_deps,
    )
    return loop, pr_manager, deps.stop_event


# ===========================================================================
# Tests
# ===========================================================================


class TestSecurityPatchLoopBasics:
    def test_worker_name(self, tmp_path: Path) -> None:
        loop, _pm, _stop = _make_loop(tmp_path)
        assert loop._worker_name == "security_patch"

    def test_default_interval_from_config(self, tmp_path: Path) -> None:
        loop, _pm, _stop = _make_loop(tmp_path, security_patch_interval=7200)
        assert loop._get_default_interval() == 7200

    def test_default_interval_config_field(self) -> None:
        config = ConfigFactory.create(security_patch_interval=3600)
        assert config.security_patch_interval == 3600

    def test_severity_threshold_config_field(self) -> None:
        config = ConfigFactory.create(security_patch_severity_threshold="critical")
        assert config.security_patch_severity_threshold == "critical"


class TestSecurityPatchLoopWork:
    @pytest.mark.asyncio
    async def test_no_alerts_returns_zero(self, tmp_path: Path) -> None:
        loop, pm, _stop = _make_loop(tmp_path, alerts=[])
        result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_fixable_alert_files_issue(self, tmp_path: Path) -> None:
        alert = _make_alert(
            1, severity="high", package="lodash", summary="Prototype Pollution"
        )
        loop, pm, _stop = _make_loop(tmp_path, alerts=[alert])
        result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 1
        pm.create_issue.assert_called_once()
        call_args = pm.create_issue.call_args
        assert "[Security]" in call_args[0][0]
        assert "lodash" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_unfixable_alert_skipped(self, tmp_path: Path) -> None:
        alert = _make_alert(2, first_patched=None)
        loop, pm, _stop = _make_loop(tmp_path, alerts=[alert])
        result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        assert result["skipped_unfixable"] == 1
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_alert_not_refiled(self, tmp_path: Path) -> None:
        alert = _make_alert(1)
        loop, pm, _stop = _make_loop(tmp_path, alerts=[alert], existing_dedup=["1"])
        result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        assert result["skipped_dedup"] == 1
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_severity_below_threshold_skipped(self, tmp_path: Path) -> None:
        alert = _make_alert(3, severity="low")
        loop, pm, _stop = _make_loop(
            tmp_path, alerts=[alert], severity_threshold="high"
        )
        result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 0
        assert result["skipped_severity"] == 1
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_returns_none(self, tmp_path: Path) -> None:
        alert = _make_alert(1)
        loop, pm, _stop = _make_loop(tmp_path, alerts=[alert], dry_run=True)
        result = await loop._do_work()
        assert result is None
        pm.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_medium_alert_passes_medium_threshold(self, tmp_path: Path) -> None:
        alert = _make_alert(4, severity="medium")
        loop, pm, _stop = _make_loop(
            tmp_path, alerts=[alert], severity_threshold="medium"
        )
        result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 1

    @pytest.mark.asyncio
    async def test_critical_alert_passes_high_threshold(self, tmp_path: Path) -> None:
        alert = _make_alert(5, severity="critical")
        loop, pm, _stop = _make_loop(
            tmp_path, alerts=[alert], severity_threshold="high"
        )
        result = await loop._do_work()
        assert result is not None
        assert result["filed"] == 1
