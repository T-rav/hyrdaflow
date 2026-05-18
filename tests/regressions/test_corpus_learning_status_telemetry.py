"""Regression test for bead advisor-uyzu (slice #5.1, PR #8793).

Bug: ``CorpusLearningLoop._do_work`` always returned ``status="noop"``
regardless of how many cases were filed. The hardcoded return misled
``TrustFleetSanityLoop`` telemetry into treating every productive tick
as idle work.

Expected behaviour after fix:
  - When ``cases_filed > 0``, ``status`` is ``"ok"``.
  - When ``cases_filed == 0`` (no signals, or all deduped), ``status``
    is ``"noop"``.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from base_background_loop import LoopDeps  # noqa: E402
from config import HydraFlowConfig  # noqa: E402
from corpus_learning_loop import (  # noqa: E402
    CorpusLearningLoop,
    SynthesizedCase,
    ValidationResult,
)
from events import EventBus  # noqa: E402


def _iso_offset(days: int) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _deps(stop: asyncio.Event, *, enabled: bool = True) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )


def _loop(
    tmp_path: Path,
    *,
    enabled: bool = True,
    prs: object | None = None,
    dedup: object | None = None,
    **config_overrides: object,
) -> CorpusLearningLoop:
    config_overrides.setdefault("repo_root", tmp_path)
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        **config_overrides,
    )
    return CorpusLearningLoop(
        config=cfg,
        prs=prs if prs is not None else AsyncMock(),
        dedup=dedup if dedup is not None else MagicMock(),
        deps=_deps(asyncio.Event(), enabled=enabled),
    )


class _InMemoryDedup:
    def __init__(self) -> None:
        self._values: set[str] = set()

    def get(self) -> set[str]:
        return set(self._values)

    def add(self, value: str) -> None:
        self._values.add(value)


class _AutoPrResultStub:
    def __init__(self, *, status: str, pr_url: str | None = None) -> None:
        self.status = status
        self.pr_url = pr_url
        self.branch = "test-branch"
        self.error = None


def test_do_work_returns_ok_status_when_cases_are_filed(
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """_do_work must return status='ok' when at least one case is filed.

    Before the fix this always returned status='noop', producing misleading
    telemetry in TrustFleetSanityLoop's event log.
    """
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 501,
                "title": "escape signal one",
                "body": "",
                "updated_at": _iso_offset(-1),
            },
        ]
    )

    dedup = _InMemoryDedup()
    loop = _loop(tmp_path, prs=prs, dedup=dedup)

    # Shortcut synthesis and validation so the test exercises only the
    # status-return path, not the full pipeline.
    loop._synthesize_case = lambda sig: SynthesizedCase(  # type: ignore[method-assign]
        issue_number=sig.issue_number,
        slug=f"case-{sig.issue_number}",
        expected_catcher="diff-sanity",
        keyword="renamed",
        before_files={"src/x.py": "before\n"},
        after_files={"src/x.py": "after\n"},
        readme="Repro.",
    )
    loop._validate_case = lambda c: ValidationResult(ok=True)  # type: ignore[method-assign]
    loop._materialize_case_on_disk = lambda c, r: []  # type: ignore[method-assign]

    async def fake_open(**kwargs: object) -> object:  # noqa: ARG001
        return _AutoPrResultStub(
            status="opened",
            pr_url="https://github.com/hydra/hydraflow/pull/999",
        )

    import corpus_learning_loop as mod

    monkeypatch.setattr(mod, "open_automated_pr_async", fake_open)  # type: ignore[attr-defined]

    result = asyncio.run(loop._do_work())

    assert result is not None
    assert result["cases_filed"] == 1
    # Before the fix this would be "noop" even with cases_filed=1.
    assert result["status"] == "ok", (
        f"Expected status='ok' when cases_filed=1, got {result['status']!r}"
    )


def test_do_work_returns_noop_status_when_no_cases_filed(tmp_path: Path) -> None:
    """_do_work must return status='noop' when no signals produce filed cases.

    Verifies the zero-work path still correctly reports 'noop' so the
    fix did not break the no-op signal.
    """
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    loop = _loop(tmp_path, prs=prs)

    result = asyncio.run(loop._do_work())

    assert result is not None
    assert result["cases_filed"] == 0
    assert result["status"] == "noop"
