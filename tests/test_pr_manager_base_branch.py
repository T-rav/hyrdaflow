"""Base-branch routing for create_pr and the new create_promotion_pr."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# conftest handles sys.path
from config import HydraFlowConfig
from pr_manager import PRManager


def _make_cfg(tmp_path: Path, *, staging_enabled: bool) -> HydraFlowConfig:
    return HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        repo="owner/repo",
        staging_enabled=staging_enabled,
    )


@pytest.fixture
def pr_manager_factory(tmp_path: Path):
    def _make(*, staging_enabled: bool) -> tuple[PRManager, HydraFlowConfig]:
        cfg = _make_cfg(tmp_path, staging_enabled=staging_enabled)
        bus = MagicMock()
        bus.publish = AsyncMock()
        pm = PRManager(config=cfg, event_bus=bus)
        return pm, cfg

    return _make


class TestCreatePrBaseBranch:
    async def test_targets_main_when_staging_disabled(
        self, pr_manager_factory, monkeypatch: pytest.MonkeyPatch
    ):
        pm, _ = pr_manager_factory(staging_enabled=False)
        captured: dict[str, tuple] = {}

        async def fake_run(*args, **kwargs):
            captured["cmd"] = args
            return "https://github.com/owner/repo/pull/1"

        monkeypatch.setattr(pm, "_run_with_body_file", fake_run)
        issue = MagicMock()
        issue.number = 42
        issue.title = "t"
        await pm.create_pr(issue=issue, branch="feat/x")
        cmd = captured["cmd"]
        assert "--base" in cmd
        assert cmd[cmd.index("--base") + 1] == "main"

    async def test_targets_staging_when_staging_enabled(
        self, pr_manager_factory, monkeypatch: pytest.MonkeyPatch
    ):
        pm, _ = pr_manager_factory(staging_enabled=True)
        captured: dict[str, tuple] = {}

        async def fake_run(*args, **kwargs):
            captured["cmd"] = args
            return "https://github.com/owner/repo/pull/1"

        monkeypatch.setattr(pm, "_run_with_body_file", fake_run)
        issue = MagicMock()
        issue.number = 42
        issue.title = "t"
        await pm.create_pr(issue=issue, branch="feat/x")
        cmd = captured["cmd"]
        assert cmd[cmd.index("--base") + 1] == "staging"


class TestCreatePromotionPrBaseBranch:
    async def test_always_targets_main_even_when_staging_enabled(
        self, pr_manager_factory, monkeypatch: pytest.MonkeyPatch
    ):
        pm, _ = pr_manager_factory(staging_enabled=True)
        captured: dict[str, tuple] = {}

        async def fake_run(*args, **kwargs):
            captured["cmd"] = args
            return "https://github.com/owner/repo/pull/2"

        monkeypatch.setattr(pm, "_run_with_body_file", fake_run)
        pr_number = await pm.create_promotion_pr(
            rc_branch="rc/2026-04-17-1600",
            title="promote rc/2026-04-17-1600",
            body="body",
        )
        cmd = captured["cmd"]
        assert cmd[cmd.index("--base") + 1] == "main"
        assert cmd[cmd.index("--head") + 1] == "rc/2026-04-17-1600"
        assert pr_number == 2

    async def test_raises_on_non_pr_url_output(
        self, pr_manager_factory, monkeypatch: pytest.MonkeyPatch
    ):
        pm, _ = pr_manager_factory(staging_enabled=True)

        async def fake_run(*args, **kwargs):
            return "some error text no url"

        monkeypatch.setattr(pm, "_run_with_body_file", fake_run)
        with pytest.raises(RuntimeError, match="gh pr create"):
            await pm.create_promotion_pr(
                rc_branch="rc/2026-04-17-1600",
                title="t",
                body="b",
            )
