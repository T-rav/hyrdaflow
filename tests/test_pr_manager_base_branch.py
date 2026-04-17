"""Base-branch routing for create_pr and the new create_promotion_pr."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from events import EventType
from tests.helpers import ConfigFactory, make_pr_manager


def _build(tmp_path: Path, *, staging_enabled: bool = False, dry_run: bool = False):
    """Build (pr_manager, config, event_bus_mock) using project factories.

    ConfigFactory.create does not expose ``staging_enabled`` as a kwarg,
    so we set it via mutation after construction. This works because
    HydraFlowConfig is a mutable Pydantic v2 model.
    """
    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        repo="owner/repo",
        dry_run=dry_run,
    )
    cfg.staging_enabled = staging_enabled
    bus = MagicMock()
    bus.publish = AsyncMock()
    return make_pr_manager(cfg, bus), cfg, bus


class TestCreatePrBaseBranch:
    async def test_targets_main_when_staging_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path, staging_enabled=False)
        captured: dict[str, tuple] = {}

        async def fake_run(*args, **_kwargs):
            captured["cmd"] = args
            return "https://github.com/owner/repo/pull/1"

        monkeypatch.setattr(pm, "_run_with_body_file", fake_run)
        issue = MagicMock()
        issue.number = 42
        issue.title = "t"
        await pm.create_pr(issue=issue, branch="feat/x")
        cmd = captured["cmd"]
        assert cmd[cmd.index("--base") + 1] == "main"

    async def test_targets_staging_when_staging_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path, staging_enabled=True)
        captured: dict[str, tuple] = {}

        async def fake_run(*args, **_kwargs):
            captured["cmd"] = args
            return "https://github.com/owner/repo/pull/1"

        monkeypatch.setattr(pm, "_run_with_body_file", fake_run)
        issue = MagicMock()
        issue.number = 42
        issue.title = "t"
        await pm.create_pr(issue=issue, branch="feat/x")
        cmd = captured["cmd"]
        assert cmd[cmd.index("--base") + 1] == "staging"


class TestCreatePromotionPr:
    async def test_always_targets_main_even_when_staging_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path, staging_enabled=True)
        captured: dict[str, tuple] = {}

        async def fake_run(*args, **_kwargs):
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
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path, staging_enabled=True)

        async def fake_run(*_args, **_kwargs):
            return "some error text no url"

        monkeypatch.setattr(pm, "_run_with_body_file", fake_run)
        with pytest.raises(RuntimeError, match="gh pr create"):
            await pm.create_promotion_pr(
                rc_branch="rc/2026-04-17-1600",
                title="t",
                body="b",
            )

    async def test_returns_zero_and_skips_gh_in_dry_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, bus = _build(tmp_path, dry_run=True)
        fake_run = AsyncMock()
        monkeypatch.setattr(pm, "_run_with_body_file", fake_run)
        pr_number = await pm.create_promotion_pr(
            rc_branch="rc/2026-04-17-1600",
            title="t",
            body="b",
        )
        assert pr_number == 0
        assert fake_run.await_count == 0
        assert bus.publish.await_count == 0

    async def test_raises_when_repo_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path)
        monkeypatch.setattr(pm, "_repo", "")
        with pytest.raises(RuntimeError):
            await pm.create_promotion_pr(
                rc_branch="rc/2026-04-17-1600",
                title="t",
                body="b",
            )

    async def test_publishes_pr_created_event_with_sentinel_issue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, bus = _build(tmp_path)

        async def fake_run(*_args, **_kwargs):
            return "https://github.com/owner/repo/pull/99"

        monkeypatch.setattr(pm, "_run_with_body_file", fake_run)
        await pm.create_promotion_pr(
            rc_branch="rc/2026-04-17-1600",
            title="promote rc/...",
            body="body",
        )
        assert bus.publish.await_count == 1
        event = bus.publish.call_args[0][0]
        assert event.type == EventType.PR_CREATED
        assert event.data["pr"] == 99
        assert event.data["issue"] == 0
        assert event.data["branch"] == "rc/2026-04-17-1600"
        assert event.data["draft"] is False
