"""Unit tests for DiscoverRunner evaluator dispatch + retry + escalation (§4.10)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from discover_runner import DiscoverRunner
from events import EventBus
from models import DiscoverResult

if TYPE_CHECKING:
    pass


def _make_task(issue_id: int = 42):
    from models import Task as _Task

    return _Task(
        id=issue_id,
        title="Vague thing",
        body="Maybe do something?",
        tags=[],
        comments=[],
        source_url="",
        links=[],
        complexity_score=0,
        created_at="",
        metadata={},
    )


_D_START = "DISCOVER_START\nbrief\nDISCOVER_END"
_OK = "DISCOVER_COMPLETENESS_RESULT: OK\nSUMMARY: fine\n"


def _retry(kw: str) -> str:
    return f"DISCOVER_COMPLETENESS_RESULT: RETRY\nSUMMARY: {kw}\n"


def _make_runner(
    max_attempts: int,
    config,
    transcripts: list[str],
    eval_transcripts: list[str],
):
    """Build a DiscoverRunner with ``_execute`` scripted [discover, eval, ...]."""
    config.max_discover_attempts = max_attempts
    config.repo_root = Path("/tmp")
    config.dry_run = False
    runner = DiscoverRunner(config=config, event_bus=MagicMock(spec=EventBus))
    call_log: list[str] = []
    queue: list[tuple[str, str]] = []
    for idx, d in enumerate(transcripts):
        queue.append(("discover", d))
        if idx < len(eval_transcripts):
            queue.append(("evaluate", eval_transcripts[idx]))

    async def _fake_execute(cmd, prompt, cwd, event_data, **_kw):
        source = str(event_data.get("source", ""))
        call_log.append(source)
        kind, content = queue.pop(0)
        assert (kind == "evaluate") == ("evaluator" in source)
        return content

    runner._execute = AsyncMock(side_effect=_fake_execute)  # type: ignore[assignment]
    runner._build_command = lambda _w=None: ["claude"]  # type: ignore[assignment]
    runner._build_prompt = lambda t: "p"  # type: ignore[assignment]
    runner._save_transcript = lambda *a, **k: None  # type: ignore[assignment]
    runner._inject_memory = AsyncMock(return_value="")  # type: ignore[assignment]
    runner._extract_result = lambda tx, n: DiscoverResult(  # type: ignore[assignment]
        issue_number=n, research_brief=tx
    )
    runner._extract_raw_brief = lambda tx: tx  # type: ignore[assignment]
    return runner, call_log


class TestDiscoverRunnerEvaluator:
    """Tests for DiscoverRunner evaluator dispatch + retry + escalation."""

    async def test_ok_on_first_attempt(self, config) -> None:
        runner, calls = _make_runner(3, config, [_D_START], [_OK])
        result = await runner.discover(_make_task())
        assert result.research_brief.startswith("DISCOVER_START")
        # Exactly one discover call and one evaluator call
        assert len([c for c in calls if "evaluator" in c]) == 1
        assert len([c for c in calls if "evaluator" not in c]) == 1

    async def test_retry_then_ok(self, config) -> None:
        runner, calls = _make_runner(
            3,
            config,
            [_D_START, _D_START],
            [_retry("missing-section:intent"), _OK],
        )
        result = await runner.discover(_make_task())
        # Two discover attempts, two evaluator calls
        assert len([c for c in calls if "evaluator" not in c]) == 2
        assert len([c for c in calls if "evaluator" in c]) == 2
        assert result.research_brief  # second brief accepted

    async def test_retry_exhaustion_escalates(self, config) -> None:
        runner, _ = _make_runner(
            2,
            config,
            [_D_START, _D_START],
            [_retry("paraphrase-only"), _retry("hid-ambiguity")],
        )
        prs = MagicMock()
        prs.create_issue = AsyncMock(return_value=101)
        dedup = MagicMock()
        dedup.get = MagicMock(return_value=set())
        dedup.add = MagicMock()
        runner.bind_escalation_deps(prs, dedup)
        await runner.discover(_make_task(42))
        prs.create_issue.assert_awaited_once()
        kwargs = prs.create_issue.call_args.kwargs
        assert {"hitl-escalation", "discover-stuck"} <= set(kwargs["labels"])
        assert "#42" in kwargs["title"]
        dedup.add.assert_called_once_with("discover_runner:42")

    async def test_dedup_hit_skips_escalation(self, config) -> None:
        runner, _ = _make_runner(1, config, [_D_START], [_retry("vague-criterion")])
        prs = MagicMock()
        prs.create_issue = AsyncMock()
        dedup = MagicMock()
        dedup.get = MagicMock(return_value={"discover_runner:42"})
        runner.bind_escalation_deps(prs, dedup)
        await runner.discover(_make_task(42))
        prs.create_issue.assert_not_awaited()

    async def test_max_attempts_zero_disables_evaluator(self, config) -> None:
        runner, calls = _make_runner(0, config, [_D_START], [])
        await runner.discover(_make_task())
        assert all("evaluator" not in c for c in calls)

    async def test_unbound_escalation_logs_only(self, config, caplog) -> None:
        runner, _ = _make_runner(1, config, [_D_START], [_retry("vague-criterion")])
        with caplog.at_level(logging.WARNING, logger="hydraflow.discover"):
            await runner.discover(_make_task(99))
        assert any("PRManager not bound" in r.message for r in caplog.records)
