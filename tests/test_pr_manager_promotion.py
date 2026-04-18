"""create_rc_branch, find_open_promotion_pr, merge_promotion_pr."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import ConfigFactory, make_pr_manager


def _build(tmp_path: Path, *, dry_run: bool = False):
    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        repo="owner/repo",
        dry_run=dry_run,
    )
    bus = MagicMock()
    bus.publish = AsyncMock()
    return make_pr_manager(cfg, bus), cfg, bus


class TestCreateRcBranch:
    async def test_creates_ref_at_staging_head(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path)
        calls: list[tuple] = []

        async def fake_gh(*args, **_kwargs):
            calls.append(args)
            if "git/refs/heads/staging" in args[2]:
                return '"deadbeef"'
            return ""

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        sha = await pm.create_rc_branch("rc/2026-04-18-1200")
        assert sha == "deadbeef"
        assert len(calls) == 2
        post_args = calls[1]
        assert "repos/owner/repo/git/refs" in post_args[2]
        assert "ref=refs/heads/rc/2026-04-18-1200" in post_args

    async def test_raises_when_staging_sha_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path)

        async def fake_gh(*_args, **_kwargs):
            return ""

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        with pytest.raises(RuntimeError, match="HEAD sha"):
            await pm.create_rc_branch("rc/2026-04-18-1200")

    async def test_skips_api_in_dry_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path, dry_run=True)
        fake_gh = AsyncMock()
        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        sha = await pm.create_rc_branch("rc/x")
        assert sha == "dry-run-sha"
        assert fake_gh.await_count == 0


class TestFindOpenPromotionPr:
    async def test_returns_info_for_first_rc_pr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path)

        async def fake_gh(*_args, **_kwargs):
            return (
                '{"number": 7, "url": "https://x/7", '
                '"isDraft": false, "branch": "rc/2026-04-18-1200"}'
            )

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        pr = await pm.find_open_promotion_pr()
        assert pr is not None
        assert pr.number == 7
        assert pr.branch == "rc/2026-04-18-1200"
        assert pr.issue_number == 0

    async def test_returns_none_when_no_pr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path)

        async def fake_gh(*_args, **_kwargs):
            return ""

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        assert await pm.find_open_promotion_pr() is None

    async def test_returns_none_on_gh_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path)

        async def fake_gh(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        assert await pm.find_open_promotion_pr() is None

    async def test_returns_none_in_dry_run(self, tmp_path: Path) -> None:
        pm, _, _ = _build(tmp_path, dry_run=True)
        assert await pm.find_open_promotion_pr() is None


class TestMergePromotionPr:
    async def test_uses_merge_not_squash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path)
        captured: dict[str, tuple] = {}

        async def fake_run(*args, **_kwargs):
            captured["cmd"] = args
            return ""

        monkeypatch.setattr("pr_manager.run_subprocess", fake_run)
        merged = await pm.merge_promotion_pr(77)
        assert merged is True
        cmd = captured["cmd"]
        assert "--merge" in cmd
        assert "--squash" not in cmd
        assert "--delete-branch" in cmd

    async def test_returns_false_on_merge_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path)

        async def fake_run(*_args, **_kwargs):
            raise RuntimeError("merge blocked")

        monkeypatch.setattr("pr_manager.run_subprocess", fake_run)
        assert await pm.merge_promotion_pr(77) is False

    async def test_skips_gh_in_dry_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path, dry_run=True)
        fake_run = AsyncMock()
        monkeypatch.setattr("pr_manager.run_subprocess", fake_run)
        assert await pm.merge_promotion_pr(77) is True
        assert fake_run.await_count == 0


class TestListRcBranches:
    async def test_returns_branch_and_date_pairs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path)

        async def fake_gh(*args, **_kwargs):
            if "matching-refs" in args[2]:
                return (
                    '[{"ref": "refs/heads/rc/2026-04-01-1200", "sha": "abc"},'
                    ' {"ref": "refs/heads/rc/2026-04-10-1600", "sha": "def"}]'
                )
            if args[2].endswith("/git/commits/abc"):
                return '"2026-04-01T12:00:00Z"'
            if args[2].endswith("/git/commits/def"):
                return '"2026-04-10T16:00:00Z"'
            return ""

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        rows = await pm.list_rc_branches()
        assert rows == [
            ("rc/2026-04-01-1200", "2026-04-01T12:00:00Z"),
            ("rc/2026-04-10-1600", "2026-04-10T16:00:00Z"),
        ]

    async def test_returns_empty_on_api_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path)

        async def fake_gh(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        assert await pm.list_rc_branches() == []

    async def test_returns_empty_in_dry_run(self, tmp_path: Path) -> None:
        pm, _, _ = _build(tmp_path, dry_run=True)
        assert await pm.list_rc_branches() == []


class TestDeleteBranch:
    async def test_calls_delete_api(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path)
        captured: list[tuple] = []

        async def fake_gh(*args, **_kwargs):
            captured.append(args)
            return ""

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        assert await pm.delete_branch("rc/2026-04-01-1200") is True
        args = captured[0]
        assert "DELETE" in args
        assert args[-1].endswith("/git/refs/heads/rc/2026-04-01-1200")

    async def test_returns_false_on_api_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path)

        async def fake_gh(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        assert await pm.delete_branch("rc/2026-04-01-1200") is False

    async def test_skips_gh_in_dry_run(self, tmp_path: Path) -> None:
        pm, _, _ = _build(tmp_path, dry_run=True)
        assert await pm.delete_branch("rc/x") is True


class TestEnsureBranchExists:
    async def test_returns_false_when_branch_already_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path)

        async def fake_gh(*args, **_kwargs):
            if "git/refs/heads/staging" in args[2]:
                return '"refs/heads/staging"'
            raise RuntimeError("unexpected call")

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        assert await pm.ensure_branch_exists("staging", base="main") is False

    async def test_creates_branch_from_base_when_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path)
        call_log: list[tuple] = []

        async def fake_gh(*args, **_kwargs):
            call_log.append(args)
            if args[2].endswith("/git/refs/heads/staging"):
                raise RuntimeError("404")
            if args[2].endswith("/git/refs/heads/main"):
                return '"mainsha"'
            return ""

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        assert await pm.ensure_branch_exists("staging", base="main") is True
        post_args = call_log[-1]
        assert "POST" in post_args
        assert "ref=refs/heads/staging" in post_args
        assert "sha=mainsha" in post_args


class TestApplyStagingBranchProtection:
    async def test_calls_protection_put_with_contexts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm, _, _ = _build(tmp_path)
        captured: dict[str, Any] = {}

        async def fake_gh(*args, **_kwargs):
            captured["args"] = args
            # Read the JSON payload written to the temp file
            if "--input" in args:
                idx = args.index("--input")
                captured["payload"] = Path(args[idx + 1]).read_text(encoding="utf-8")
            return ""

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        result = await pm.apply_staging_branch_protection("staging")
        assert result["status"] == "protected"
        args = captured["args"]
        assert "PUT" in args
        assert "repos/owner/repo/branches/staging/protection" in args
        payload = json.loads(captured["payload"])
        assert payload["allow_force_pushes"] is False
        assert payload["allow_deletions"] is False
        assert "CI" in payload["required_status_checks"]["contexts"]
        assert "Quality" in payload["required_status_checks"]["contexts"]

    async def test_skips_gh_in_dry_run(self, tmp_path: Path) -> None:
        pm, _, _ = _build(tmp_path, dry_run=True)
        result = await pm.apply_staging_branch_protection("staging")
        assert result["status"] == "dry-run"
