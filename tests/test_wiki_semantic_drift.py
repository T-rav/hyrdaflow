"""E2 — LLM semantic-drift layer on top of the deterministic detector.

B3 caught missing files + missing symbols. E2 closes the gap where
the file and symbol still exist but the entry's CLAIM about them is
no longer true (renamed defaults, swapped model tiers, changed
control flow). The LLM judges freshness given the current source.

Uses an injected async callable so unit tests don't need real LLM
creds; the callable is substituted with WikiCompiler._call_model in
production.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from wiki_drift_detector import (
    SemanticDriftFinding,
    detect_semantic_drift_for_entry,
    scan_semantic_drift,
)


def _write_entry(
    tracked_root: Path,
    repo_slug: str,
    topic: str,
    *,
    body: str,
    entry_id: str,
    source_issue: int,
    created_at: datetime | None = None,
    status: str = "active",
) -> Path:
    topic_dir = tracked_root / repo_slug / topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    created = (created_at or datetime.now(UTC)).isoformat()
    path = topic_dir / f"{source_issue:04d}-{entry_id[-6:]}.md"
    path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        f"topic: {topic}\n"
        f"source_issue: {source_issue}\n"
        "source_phase: implement\n"
        f"created_at: {created}\n"
        f"status: {status}\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.asyncio
async def test_contradicted_verdict_produces_finding(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "config.py").write_text(
        'triage_model = "gemini-3.1-pro-preview"\n'
    )
    entry_path = _write_entry(
        tmp_path / "repo_wiki",
        "o/r",
        "patterns",
        body="Triage uses `src/config.py:triage_model` set to haiku.",
        entry_id="01JF000000000000000001",
        source_issue=1,
    )

    async def fake_llm(prompt: str) -> str:
        return (
            "VERDICT: contradicted\n"
            "REASON: wiki says haiku, code sets gemini-3.1-pro-preview"
        )

    finding = await detect_semantic_drift_for_entry(
        entry_path=entry_path,
        repo_root=repo_root,
        ask_llm=fake_llm,
    )

    assert finding is not None
    assert finding.verdict == "contradicted"
    assert "gemini" in finding.reason


@pytest.mark.asyncio
async def test_valid_verdict_returns_none(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "config.py").write_text('triage_model = "sonnet"\n')
    entry_path = _write_entry(
        tmp_path / "repo_wiki",
        "o/r",
        "patterns",
        body="Triage uses `src/config.py:triage_model` set to sonnet.",
        entry_id="01JF000000000000000002",
        source_issue=2,
    )

    async def fake_llm(prompt: str) -> str:
        return "VERDICT: valid\nREASON: claim still matches"

    finding = await detect_semantic_drift_for_entry(
        entry_path=entry_path,
        repo_root=repo_root,
        ask_llm=fake_llm,
    )

    assert finding is None


@pytest.mark.asyncio
async def test_malformed_llm_output_is_treated_as_unknown(tmp_path: Path) -> None:
    """Never crash on garbage — unknown verdict = no finding, no stale-mark."""
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "config.py").write_text("stuff\n")
    entry_path = _write_entry(
        tmp_path / "repo_wiki",
        "o/r",
        "patterns",
        body="Cites `src/config.py:stuff`.",
        entry_id="01JF000000000000000003",
        source_issue=3,
    )

    async def fake_llm(prompt: str) -> str:
        return "sure the wiki looks fine I guess"

    finding = await detect_semantic_drift_for_entry(
        entry_path=entry_path,
        repo_root=repo_root,
        ask_llm=fake_llm,
    )

    assert finding is None


@pytest.mark.asyncio
async def test_entry_without_src_citations_is_skipped(tmp_path: Path) -> None:
    entry_path = _write_entry(
        tmp_path / "repo_wiki",
        "o/r",
        "patterns",
        body="General advice with no src/ pointer.",
        entry_id="01JF000000000000000004",
        source_issue=4,
    )

    called = False

    async def fake_llm(prompt: str) -> str:  # noqa: ARG001
        nonlocal called
        called = True
        return ""

    finding = await detect_semantic_drift_for_entry(
        entry_path=entry_path,
        repo_root=tmp_path / "repo",
        ask_llm=fake_llm,
    )

    assert finding is None
    assert not called, "no LLM call should be made when the entry has no citations"


@pytest.mark.asyncio
async def test_scan_respects_min_age(tmp_path: Path) -> None:
    """scan_semantic_drift only re-checks entries older than min_age_days."""
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "a.py").write_text("def thing(): pass\n")

    young = datetime.now(UTC) - timedelta(days=1)
    old = datetime.now(UTC) - timedelta(days=40)

    _write_entry(
        tmp_path / "repo_wiki",
        "o/r",
        "patterns",
        body="cites `src/a.py:thing`",
        entry_id="01JFYOUNG000000000000",
        source_issue=1,
        created_at=young,
    )
    _write_entry(
        tmp_path / "repo_wiki",
        "o/r",
        "patterns",
        body="cites `src/a.py:thing`",
        entry_id="01JFOLD00000000000000",
        source_issue=2,
        created_at=old,
    )

    calls: list[Path] = []

    async def fake_llm(prompt: str) -> str:  # noqa: ARG001
        calls.append(Path("called"))
        return "VERDICT: valid\nREASON: ok"

    findings = await scan_semantic_drift(
        tracked_root=tmp_path / "repo_wiki",
        repo_root=repo_root,
        repo_slug="o/r",
        ask_llm=fake_llm,
        min_age_days=30,
    )

    # Only the old entry gets re-checked; young skipped
    assert len(calls) == 1
    assert findings == []


@pytest.mark.asyncio
async def test_scan_respects_max_entries_per_tick(tmp_path: Path) -> None:
    """Cost bound: cap how many LLM calls we make per loop tick."""
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "src" / "a.py").write_text("def thing(): pass\n")

    old = datetime.now(UTC) - timedelta(days=40)
    for i in range(5):
        _write_entry(
            tmp_path / "repo_wiki",
            "o/r",
            "patterns",
            body=f"entry {i} cites `src/a.py:thing`",
            entry_id=f"01JF00000000000000000{i}",
            source_issue=100 + i,
            created_at=old,
        )

    call_count = 0

    async def fake_llm(prompt: str) -> str:  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        return "VERDICT: valid"

    await scan_semantic_drift(
        tracked_root=tmp_path / "repo_wiki",
        repo_root=repo_root,
        repo_slug="o/r",
        ask_llm=fake_llm,
        min_age_days=30,
        max_entries_per_tick=2,
    )

    assert call_count == 2


@pytest.mark.asyncio
async def test_semantic_finding_is_separate_from_deterministic_one(
    tmp_path: Path,
) -> None:
    """SemanticDriftFinding is a distinct type — doesn't override DriftFinding."""
    f = SemanticDriftFinding(
        entry_path=tmp_path / "x.md",
        entry_id="y",
        topic="patterns",
        verdict="contradicted",
        reason="test reason",
    )
    assert f.verdict == "contradicted"
    assert f.reason == "test reason"
