"""Per-issue cost alert hook fires on successful PR merge (spec §4.11 Task 10).

When :meth:`PRManager.merge_pr` successfully squash-merges a PR, the hook
must:

* Aggregate the issue's priced inferences via
  ``iter_priced_inferences_for_issue`` (lazy wrapper in ``pr_manager``).
* Call ``check_issue_cost`` (also lazy wrapper) with the correct
  ``issue_number`` + ``cost_usd``.
* Use its own ``DedupStore`` keyed on ``cost_issue_alerts`` so it cannot
  collide with the daily-budget dedup.
* Swallow any exception in the rollup/hook path — a broken cost aggregation
  must never turn a real merge success into a failure.
* Never fire when the merge itself fails.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from pr_manager import PRManager


def _stub_pricing() -> object:
    """Return a sentinel pricing object for monkeypatching ``load_pricing``."""
    return object()


@pytest.fixture
def merge_cfg(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = tmp_path.joinpath
    cfg.dry_run = False
    cfg.repo = "owner/repo"
    cfg.repo_root = tmp_path
    cfg.find_label = ["hydraflow-find"]
    cfg.issue_cost_alert_usd = 1.0
    cfg.daily_cost_budget_usd = None
    cfg.gh_max_retries = 0
    return cfg


def _make_manager(cfg: MagicMock) -> tuple[PRManager, MagicMock]:
    bus = MagicMock()
    bus.publish = AsyncMock()
    pm = PRManager(config=cfg, event_bus=bus)
    return pm, bus


async def test_merge_success_invokes_issue_cost_hook_with_aggregated_cost(
    merge_cfg: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful merge aggregates priced inferences and fires the alert."""
    pm, _ = _make_manager(merge_cfg)

    # Stub title fetch -> title containing the issue reference.
    monkeypatch.setattr(
        pm,
        "get_pr_title_and_body",
        AsyncMock(return_value=("Fixes #42: tidy budgets", "body")),
    )
    # Stub the actual gh merge subprocess to succeed.
    monkeypatch.setattr("pr_manager.run_subprocess", AsyncMock())

    # Stub the two lazy wrappers the hook relies on.
    def fake_inferences_for_issue(_cfg, *, issue, pricing):
        assert issue == 42
        assert pricing is _sentinel_pricing
        return iter(
            [
                {"issue_number": 42, "cost_usd": 0.40},
                {"issue_number": 42, "cost_usd": 0.85},
                {"issue_number": 42, "cost_usd": 0.25},
            ]
        )

    _sentinel_pricing = object()
    monkeypatch.setattr("pr_manager.load_pricing", lambda: _sentinel_pricing)
    monkeypatch.setattr(
        "pr_manager.iter_priced_inferences_for_issue", fake_inferences_for_issue
    )

    calls: list[dict[str, object]] = []

    async def fake_check_issue_cost(
        cfg,
        *,
        pr_manager,
        dedup,
        event_bus,
        issue_number,
        cost_usd,
    ):
        calls.append(
            {
                "cfg": cfg,
                "pr_manager": pr_manager,
                "dedup": dedup,
                "event_bus": event_bus,
                "issue_number": issue_number,
                "cost_usd": cost_usd,
            }
        )

    monkeypatch.setattr("pr_manager.check_issue_cost", fake_check_issue_cost)

    result = await pm.merge_pr(9999)

    assert result is True
    assert len(calls) == 1
    call = calls[0]
    assert call["issue_number"] == 42
    assert call["cost_usd"] == pytest.approx(1.50)
    assert call["cfg"] is merge_cfg
    assert call["pr_manager"] is pm
    # Hook writes its dedup under cost_issue_alerts to keep it distinct
    # from the daily-budget store (cost_budget_alerts).
    dedup = call["dedup"]
    assert dedup._file_path == (  # type: ignore[attr-defined]
        merge_cfg.data_root / "dedup" / "cost_issue_alerts.json"
    )
    assert dedup._set_name == "cost_issue_alerts"  # type: ignore[attr-defined]


async def test_daily_dedup_does_not_block_issue_alert(
    merge_cfg: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Daily-budget dedup key does not suppress the per-issue alert (separate stores)."""
    pm, _ = _make_manager(merge_cfg)

    # Pre-seed the daily-budget dedup file with today's key — proves the
    # merge hook does NOT read from the daily store.
    daily = tmp_path / "dedup" / "cost_budget_alerts.json"
    daily.parent.mkdir(parents=True, exist_ok=True)
    daily.write_text('["cost_budget:2026-04-23"]')

    monkeypatch.setattr(
        pm,
        "get_pr_title_and_body",
        AsyncMock(return_value=("Fixes #7: x", "")),
    )
    monkeypatch.setattr("pr_manager.run_subprocess", AsyncMock())
    monkeypatch.setattr("pr_manager.load_pricing", _stub_pricing)
    monkeypatch.setattr(
        "pr_manager.iter_priced_inferences_for_issue",
        lambda _cfg, *, issue, pricing: iter(
            [{"issue_number": issue, "cost_usd": 5.0}]
        ),
    )

    called = {}

    async def fake_check_issue_cost(cfg, **kwargs):
        called.update(kwargs)

    monkeypatch.setattr("pr_manager.check_issue_cost", fake_check_issue_cost)

    assert await pm.merge_pr(777) is True
    assert called["issue_number"] == 7
    assert called["cost_usd"] == pytest.approx(5.0)
    # And the dedup file the hook constructed is a DIFFERENT path.
    assert called["dedup"]._file_path != daily  # type: ignore[attr-defined]


async def test_merge_failure_skips_issue_cost_hook(
    merge_cfg: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the gh merge subprocess fails, the hook must NOT run."""
    pm, _ = _make_manager(merge_cfg)
    monkeypatch.setattr(
        pm,
        "get_pr_title_and_body",
        AsyncMock(return_value=("Fixes #42: tidy", "")),
    )

    async def boom(*_a, **_kw):
        raise RuntimeError("gh merge denied")

    monkeypatch.setattr("pr_manager.run_subprocess", boom)

    hook_called = False

    async def fake_check_issue_cost(*_a, **_kw):
        nonlocal hook_called
        hook_called = True

    monkeypatch.setattr("pr_manager.check_issue_cost", fake_check_issue_cost)
    # Stub these so that if the hook *were* invoked we'd still have valid
    # wrappers — the assertion is on `hook_called`.
    monkeypatch.setattr("pr_manager.load_pricing", _stub_pricing)
    monkeypatch.setattr(
        "pr_manager.iter_priced_inferences_for_issue",
        lambda *_a, **_kw: iter([]),
    )

    assert await pm.merge_pr(9999) is False
    assert hook_called is False


async def test_rollup_exception_is_swallowed_and_merge_still_succeeds(
    merge_cfg: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken rollup read must not turn a merge success into a failure."""
    pm, _ = _make_manager(merge_cfg)
    monkeypatch.setattr(
        pm,
        "get_pr_title_and_body",
        AsyncMock(return_value=("Fixes #42: tidy", "")),
    )
    monkeypatch.setattr("pr_manager.run_subprocess", AsyncMock())

    def explode(*_a, **_kw):
        raise RuntimeError("inference log corrupt")

    monkeypatch.setattr("pr_manager.load_pricing", _stub_pricing)
    monkeypatch.setattr("pr_manager.iter_priced_inferences_for_issue", explode)

    check_called = False

    async def fake_check_issue_cost(*_a, **_kw):
        nonlocal check_called
        check_called = True

    monkeypatch.setattr("pr_manager.check_issue_cost", fake_check_issue_cost)

    # Must not raise and must still return True (merge itself succeeded).
    assert await pm.merge_pr(9999) is True
    assert check_called is False


async def test_no_issue_ref_in_title_skips_hook(
    merge_cfg: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the PR title has no ``#N`` reference the hook is skipped silently."""
    pm, _ = _make_manager(merge_cfg)
    monkeypatch.setattr(
        pm,
        "get_pr_title_and_body",
        AsyncMock(return_value=("docs: tidy README", "")),
    )
    monkeypatch.setattr("pr_manager.run_subprocess", AsyncMock())
    monkeypatch.setattr("pr_manager.load_pricing", _stub_pricing)
    monkeypatch.setattr(
        "pr_manager.iter_priced_inferences_for_issue",
        lambda *_a, **_kw: iter([]),
    )

    hook_called = False

    async def fake_check_issue_cost(*_a, **_kw):
        nonlocal hook_called
        hook_called = True

    monkeypatch.setattr("pr_manager.check_issue_cost", fake_check_issue_cost)

    assert await pm.merge_pr(1) is True
    assert hook_called is False


async def test_title_variants_are_all_parsed(
    merge_cfg: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue numbers are pulled from the first ``#N`` in the title regardless of shape."""
    captured: list[int] = []

    async def fake_check_issue_cost(_cfg, *, issue_number, **_kw):
        captured.append(issue_number)

    async def run(title: str) -> None:
        pm, _ = _make_manager(merge_cfg)
        monkeypatch.setattr(
            pm, "get_pr_title_and_body", AsyncMock(return_value=(title, ""))
        )
        monkeypatch.setattr("pr_manager.run_subprocess", AsyncMock())
        monkeypatch.setattr("pr_manager.load_pricing", _stub_pricing)
        monkeypatch.setattr(
            "pr_manager.iter_priced_inferences_for_issue",
            lambda *_a, **_kw: iter([]),
        )
        monkeypatch.setattr("pr_manager.check_issue_cost", fake_check_issue_cost)
        assert await pm.merge_pr(0) is True

    await run("feat(x): do thing (#123)")
    await run("Fixes #42: tidy budgets")
    await run("refactor: tidy (closes #7)")
    assert captured == [123, 42, 7]
