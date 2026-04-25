"""End-to-end integration tests for :mod:`corpus_learning_loop` (§4.1 Task 16).

This file is intentionally separate from
``tests/test_corpus_learning_loop.py`` — that module owns an autouse
fixture that stubs :func:`auto_pr.open_automated_pr_async` to a silent
no-op returning ``status="no-diff"``. The integration tests below
deliberately exercise the PR-opening seam with scenario-specific mocks,
so they must not live beside that autouse stub.

Scope (per the plan's Task 16):

- **Happy path**: a seeded escape issue flows through the full
  ``_do_work`` pipeline (reader → synth → three-gate validation →
  materialize → PR open → dedup) and surfaces the expected counters
  plus the expected :func:`auto_pr.open_automated_pr_async` call shape.
- **Unparseable signal**: a body that misses the envelope convention is
  dropped at synthesis without crashing the tick or filing a PR.
- **Validation failure**: synthesis succeeds but gate (b) rejects the
  case (no catcher trip) — no PR is filed and the counter stays at 0.
- **Dedup hit on re-run**: ticking a second time against the same
  escape signal short-circuits at the dedup set, so no second
  :func:`auto_pr.open_automated_pr_async` call is made.

All seams (``PRManager.list_issues_by_label``,
``auto_pr.open_automated_pr_async``, and — for the gate-(b) failure
scenario — ``CorpusLearningLoop._fixture_transcript_for``) are mocked
at module boundaries; everything in between runs the real code path.
The suite stays well under 2 s on a modern laptop because there is
no real I/O to git, GitHub, or an LLM.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from corpus_learning_loop import (
    CorpusLearningLoop,
    SynthesizedCase,
)
from dedup_store import DedupStore
from events import EventBus

# ---------------------------------------------------------------------------
# Helpers — kept local so the unit-test autouse fixture from
# tests/test_corpus_learning_loop.py never leaks into this module.
# ---------------------------------------------------------------------------


def _iso_now_offset(days: int) -> str:
    """Return an ISO-8601 UTC timestamp ``days`` ago (negative => past)."""
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _well_formed_body(
    *,
    catcher: str = "diff-sanity",
    keyword: str = "renamed",
    readme: str = "Symbol rename leaves callsite stale.",
) -> str:
    """Build an escape-issue body the synthesizer can parse cleanly.

    Mirrors the envelope the plan documents on :class:`SynthesizedCase`
    and the shape ``_well_formed_signal_body`` uses in the unit-test
    file. Kept local here so the two files never drift on accident.
    """
    return "\n".join(
        [
            readme,
            "",
            f"Expected-Catcher: {catcher}",
            f"Keyword: {keyword}",
            "",
            "```before:src/foo.py",
            "def compute_total():",
            "    return 1",
            "```",
            "",
            "```after:src/foo.py",
            "def compute_sum():",
            "    return 1",
            "```",
        ]
    )


class _AutoPrResultStub:
    """Duck-typed stand-in for :class:`auto_pr.AutoPrResult`.

    The real dataclass is frozen and validates its ``status`` literal;
    for integration tests we only need the attribute surface the loop
    reads (``status``, ``pr_url``, ``error``). Keeping the stub local
    avoids coupling this file to ``auto_pr``'s construction rules.
    """

    def __init__(
        self,
        *,
        status: str,
        pr_url: str | None = None,
        error: str | None = None,
    ) -> None:
        self.status = status
        self.pr_url = pr_url
        self.branch = "corpus-learning/integration-test-branch"
        self.error = error


@pytest.fixture
def _prs() -> AsyncMock:
    """PRManager stand-in exposing :meth:`list_issues_by_label`."""
    prs = AsyncMock()
    prs.list_issues_by_label = AsyncMock(return_value=[])
    return prs


@pytest.fixture
def _dedup(tmp_path: Path) -> DedupStore:
    """Real file-backed :class:`DedupStore` rooted in the test sandbox.

    Using the real store (not a mock) means the "dedup hit on re-run"
    scenario exercises the actual JSON-file round-trip, matching the
    production code path.
    """
    return DedupStore("corpus_learning", tmp_path / "corpus_dedup.json")


def _loop(
    tmp_path: Path,
    prs: AsyncMock,
    dedup: DedupStore,
    *,
    enabled: bool = True,
) -> CorpusLearningLoop:
    """Build a :class:`CorpusLearningLoop` rooted at ``tmp_path``.

    ``repo_root`` is set to ``tmp_path`` so Task 15's materialization
    writes under the sandbox and never escapes to the real repo.
    """
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        repo="hydra/hydraflow",
        repo_root=tmp_path,
    )
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: enabled,
    )
    return CorpusLearningLoop(config=cfg, prs=prs, dedup=dedup, deps=deps)


# ---------------------------------------------------------------------------
# Scenario 1 — happy path
# ---------------------------------------------------------------------------


def test_end_to_end_happy_path_files_one_pr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _prs: AsyncMock,
    _dedup: DedupStore,
) -> None:
    """Parseable + validatable escape → one PR, dedup recorded, counters aligned.

    Asserts the full contract of a green tick: the issue is seen, the
    envelope is synthesized, the three-gate validator passes, the case
    is materialized to disk, and ``auto_pr.open_automated_pr_async`` is
    invoked with the expected title/body/labels shape. The dedup store
    is updated so a later tick won't re-file.
    """
    _prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 4242,
                "title": "diff-sanity missed renamed symbol",
                "body": _well_formed_body(),
                "updated_at": _iso_now_offset(-1),
            },
        ]
    )

    open_calls: list[dict[str, Any]] = []

    async def fake_open(**kwargs: Any) -> _AutoPrResultStub:
        open_calls.append(kwargs)
        return _AutoPrResultStub(
            status="opened",
            pr_url="https://github.com/hydra/hydraflow/pull/999",
        )

    import corpus_learning_loop as mod

    monkeypatch.setattr(mod, "open_automated_pr_async", fake_open)

    loop = _loop(tmp_path, _prs, _dedup)
    result = asyncio.run(loop._do_work())

    # Counter contract — every stage advanced.
    assert result["status"] != "disabled"
    assert result["escape_issues_seen"] == 1
    assert result["cases_synthesized"] == 1
    assert result["cases_validated"] == 1
    assert result["cases_filed"] == 1

    # Spec §4.1: reader is invoked once per escape-label family (default 3).
    awaited_labels = [
        call.args[0] for call in _prs.list_issues_by_label.await_args_list
    ]
    assert awaited_labels == ["skill-escape", "discover-escape", "shape-escape"]

    # PR-open seam was called exactly once, with the derived title/body
    # and the expected label set.
    assert len(open_calls) == 1
    kwargs = open_calls[0]
    assert kwargs["pr_title"] == "test(trust): corpus-learning case for escape #4242"
    body = kwargs["pr_body"]
    assert "#4242" in body
    assert "`diff-sanity`" in body
    assert "`renamed`" in body
    assert "Closes #4242" in body
    labels = kwargs["labels"]
    assert isinstance(labels, list)
    assert "hydraflow-agent" in labels
    assert "corpus-learning" in labels
    # Branch + files carry the slug derived from the issue title.
    slug = "diff-sanity-missed-renamed-symbol"
    assert slug in str(kwargs["branch"])
    assert "4242" in str(kwargs["branch"])
    files = kwargs["files"]
    assert isinstance(files, list)
    assert files, "expected materialized files to be passed to auto_pr"

    # Case directory actually landed on disk.
    case_dir = tmp_path / "tests" / "trust" / "adversarial" / "cases" / slug
    assert (case_dir / "README.md").exists()
    assert (case_dir / "expected_catcher.txt").read_text().strip() == "diff-sanity"
    assert (case_dir / "before" / "src" / "foo.py").exists()
    assert (case_dir / "after" / "src" / "foo.py").exists()

    # Dedup entry was persisted, keyed on issue number + slug.
    assert f"corpus_learning:4242:{slug}" in _dedup.get()


# ---------------------------------------------------------------------------
# Scenario 2 — unparseable escape issue
# ---------------------------------------------------------------------------


def test_end_to_end_unparseable_signal_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _prs: AsyncMock,
    _dedup: DedupStore,
) -> None:
    """An escape with no envelope is dropped at synth; no PR is opened.

    The loop must see the issue (so telemetry knows it arrived) but
    surface ``cases_synthesized == 0`` and never reach the PR seam.
    """
    _prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 7001,
                "title": "something went wrong",
                # No Expected-Catcher / Keyword / before / after blocks.
                "body": "Free-form prose only — nothing for the synthesizer.",
                "updated_at": _iso_now_offset(-1),
            },
        ]
    )

    open_calls: list[dict[str, Any]] = []

    async def fake_open(**kwargs: Any) -> _AutoPrResultStub:
        open_calls.append(kwargs)
        return _AutoPrResultStub(status="opened", pr_url="x/y/pull/1")

    import corpus_learning_loop as mod

    monkeypatch.setattr(mod, "open_automated_pr_async", fake_open)

    loop = _loop(tmp_path, _prs, _dedup)
    result = asyncio.run(loop._do_work())

    assert result["escape_issues_seen"] == 1
    assert result["cases_synthesized"] == 0
    assert result["cases_validated"] == 0
    assert result["cases_filed"] == 0
    assert open_calls == []
    assert _dedup.get() == set()


# ---------------------------------------------------------------------------
# Scenario 3 — validation failure (gate b: expected catcher does not trip)
# ---------------------------------------------------------------------------


def test_end_to_end_validation_failure_skips_pr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _prs: AsyncMock,
    _dedup: DedupStore,
) -> None:
    """Synthesis succeeds but gate (b) fails → no PR, no dedup entry.

    We force the failure by replacing ``_fixture_transcript_for`` with
    one that emits the right marker but strips the keyword from the
    ``SUMMARY`` line, so the gate-(b) keyword check rejects the case.
    """
    _prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 8080,
                "title": "diff-sanity missed renamed symbol",
                "body": _well_formed_body(keyword="unique-token"),
                "updated_at": _iso_now_offset(-1),
            },
        ]
    )

    open_calls: list[dict[str, Any]] = []

    async def fake_open(**kwargs: Any) -> _AutoPrResultStub:
        open_calls.append(kwargs)
        return _AutoPrResultStub(status="opened", pr_url="x/y/pull/1")

    import corpus_learning_loop as mod

    monkeypatch.setattr(mod, "open_automated_pr_async", fake_open)

    loop = _loop(tmp_path, _prs, _dedup)

    # Force gate (b) to fail: keep the RETRY marker (so the parser still
    # says passed=False) but strip the keyword from the summary so the
    # haystack check rejects the case.
    def transcript_without_keyword(case: SynthesizedCase, skill_name: str) -> str:
        return (
            "DIFF_SANITY_RESULT: RETRY\n"
            "SUMMARY: summary with no keyword\n"
            f"FINDINGS:\n- {case.slug}\n"
        )

    loop._fixture_transcript_for = transcript_without_keyword  # type: ignore[method-assign]

    result = asyncio.run(loop._do_work())

    assert result["escape_issues_seen"] == 1
    assert result["cases_synthesized"] == 1
    assert result["cases_validated"] == 0
    assert result["cases_filed"] == 0
    assert open_calls == []
    assert _dedup.get() == set()


# ---------------------------------------------------------------------------
# Scenario 4 — dedup hit on re-run
# ---------------------------------------------------------------------------


def test_end_to_end_dedup_prevents_refile_on_second_tick(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _prs: AsyncMock,
    _dedup: DedupStore,
) -> None:
    """Two ticks against the same escape issue → one PR, not two.

    Exercises the dedup-store short-circuit: the second
    :meth:`CorpusLearningLoop._do_work` invocation must not reach
    :func:`auto_pr.open_automated_pr_async` because the first tick
    already recorded the ``corpus_learning:<n>:<slug>`` key.
    """
    _prs.list_issues_by_label = AsyncMock(
        return_value=[
            {
                "number": 5151,
                "title": "diff-sanity missed renamed symbol",
                "body": _well_formed_body(),
                "updated_at": _iso_now_offset(-1),
            },
        ]
    )

    open_calls: list[dict[str, Any]] = []

    async def fake_open(**kwargs: Any) -> _AutoPrResultStub:
        open_calls.append(kwargs)
        return _AutoPrResultStub(
            status="opened",
            pr_url="https://github.com/hydra/hydraflow/pull/999",
        )

    import corpus_learning_loop as mod

    monkeypatch.setattr(mod, "open_automated_pr_async", fake_open)

    loop = _loop(tmp_path, _prs, _dedup)

    # First tick — files one PR, writes the dedup entry.
    first = asyncio.run(loop._do_work())
    assert first["cases_filed"] == 1
    assert len(open_calls) == 1

    # Second tick — same signal, must short-circuit at dedup.
    second = asyncio.run(loop._do_work())
    assert second["escape_issues_seen"] == 1
    assert second["cases_synthesized"] == 1
    assert second["cases_validated"] == 1
    assert second["cases_filed"] == 0, (
        "dedup should prevent a second auto_pr.open_automated_pr_async call"
    )
    assert len(open_calls) == 1, (
        "expected exactly one PR across both ticks; dedup failed"
    )
