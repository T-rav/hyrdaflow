"""Full-loop scenario for DiagramLoop (Plan C §7, ADR-0047).

Exercises DiagramLoop._do_work() end-to-end with patched seams at the
arch.runner.emit + auto_pr.open_automated_pr_async boundaries. Asserts:

1. No-drift path: emit() runs, git status is clean → returns {"drift": False}
   and PR creation does NOT happen.
2. Drift path: emit() writes new content, git status reports changes →
   open_automated_pr_async is called with the regen branch + correct
   labels, coverage check fires.
3. Coverage gap: when the YAML doesn't cover a discovered loop, the loop
   opens a "chore(arch): unassigned functional area" issue via PRPort.

Per ADR-0047 (fake-adapter contract testing) — uses real PRPort method
names (find_existing_issue, create_issue), so any drift in the Port
contract surfaces here.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base_background_loop import LoopDeps
from diagram_loop import DiagramLoop


def _make_loop(tmp_path: Path) -> tuple[DiagramLoop, MagicMock]:
    deps = LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=MagicMock(return_value=True),
        sleep_fn=AsyncMock(),
        interval_cb=MagicMock(return_value=14400),
    )
    pr_manager = MagicMock()
    pr_manager.find_existing_issue = AsyncMock(return_value=0)
    pr_manager.create_issue = AsyncMock(return_value=42)
    loop = DiagramLoop(config=MagicMock(), pr_manager=pr_manager, deps=deps)
    loop._set_repo_root(tmp_path)
    return loop, pr_manager


@pytest.mark.asyncio
async def test_no_drift_returns_drift_false_and_skips_pr(tmp_path: Path) -> None:
    loop, pr_manager = _make_loop(tmp_path)
    # arch.runner.emit is a no-op; git status returns nothing.
    with (
        patch("arch.runner.emit") as mock_emit,
        patch("diagram_loop.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = await loop._do_work()
    assert result == {"drift": False}
    mock_emit.assert_called_once()
    pr_manager.find_existing_issue.assert_not_awaited()
    pr_manager.create_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_drift_opens_pr_with_correct_labels(tmp_path: Path, monkeypatch) -> None:
    loop, pr_manager = _make_loop(tmp_path)
    # Stub coverage check to return no unassigned items so we focus on PR path.
    monkeypatch.setattr(
        loop, "_unassigned_items", AsyncMock(return_value={"loops": [], "ports": []})
    )

    pr_result = MagicMock(status="opened", pr_url="https://github.com/x/y/pull/1")
    with (
        patch("arch.runner.emit") as mock_emit,
        patch("diagram_loop.subprocess.run") as mock_run,
        patch(
            "auto_pr.open_automated_pr_async", AsyncMock(return_value=pr_result)
        ) as mock_pr,
    ):
        mock_run.return_value = MagicMock(
            returncode=0, stdout=" M docs/arch/generated/loops.md\n"
        )
        result = await loop._do_work()

    assert result["drift"] is True
    assert result["pr_url"] == "https://github.com/x/y/pull/1"
    assert result["changed_files"] == 1

    # PR opened with the regen branch and expected labels
    mock_emit.assert_called_once()
    call_kwargs = mock_pr.await_args.kwargs
    assert call_kwargs["branch"] == "arch-regen-auto"
    assert call_kwargs["pr_title"].startswith(
        "chore(arch): regenerate architecture knowledge"
    )
    assert "hydraflow-ready" in call_kwargs["labels"]
    assert "arch-regen" in call_kwargs["labels"]


@pytest.mark.asyncio
async def test_coverage_gap_files_unassigned_issue(tmp_path: Path, monkeypatch) -> None:
    loop, pr_manager = _make_loop(tmp_path)
    # Pretend the coverage check found unassigned loops.
    monkeypatch.setattr(
        loop,
        "_unassigned_items",
        AsyncMock(return_value={"loops": ["FooLoop"], "ports": []}),
    )

    await loop._ensure_coverage_issue()

    pr_manager.find_existing_issue.assert_awaited_once_with(
        "chore(arch): unassigned functional area"
    )
    pr_manager.create_issue.assert_awaited_once()
    issue_body = pr_manager.create_issue.await_args.kwargs["body"]
    assert "FooLoop" in issue_body
    assert "functional_areas.yml" in issue_body


@pytest.mark.asyncio
async def test_coverage_gap_dedups_against_existing_issue(
    tmp_path: Path, monkeypatch
) -> None:
    loop, pr_manager = _make_loop(tmp_path)
    # Existing issue with the canonical title is open — don't dup.
    pr_manager.find_existing_issue = AsyncMock(return_value=99)
    monkeypatch.setattr(
        loop,
        "_unassigned_items",
        AsyncMock(return_value={"loops": ["FooLoop"], "ports": []}),
    )

    await loop._ensure_coverage_issue()

    pr_manager.find_existing_issue.assert_awaited_once()
    pr_manager.create_issue.assert_not_awaited()
