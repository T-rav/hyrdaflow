"""Unit tests for ShapeRunner evaluator dispatch + retry + escalation (§4.10)."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from events import EventBus
from models import ShapeConversation
from shape_runner import ShapeRunner


def _make_task(issue_id: int = 42):
    from models import Task as _Task

    return _Task(
        id=issue_id,
        title="Shape something",
        body="Please propose directions.",
        tags=[],
        comments=[],
        source_url="",
        links=[],
        complexity_score=0,
        created_at="",
        metadata={},
    )


_S_FINAL = (
    "SHAPE_FINALIZE\n"
    "## Final\n"
    "- Option A — trade-off X\n"
    "- Option B — trade-off Y\n"
    "- Defer — cost Z\n"
    "SHAPE_FINALIZE_END\n"
)
_S_CONTINUE = "SHAPE_CONTINUE\nlet's discuss\nSHAPE_CONTINUE_END\n"
_OK = "SHAPE_COHERENCE_RESULT: OK\nSUMMARY: fine\n"


def _retry(kw: str) -> str:
    return f"SHAPE_COHERENCE_RESULT: RETRY\nSUMMARY: {kw}\n"


def _make_runner(
    max_attempts: int,
    config,
    transcripts: list[str],
    eval_transcripts: list[str],
):
    """Build a ShapeRunner with ``_execute`` scripted [turn, eval, ...]."""
    config.max_shape_attempts = max_attempts
    config.repo_root = Path("/tmp")
    config.dry_run = False
    runner = ShapeRunner(config=config, event_bus=MagicMock(spec=EventBus))
    call_log: list[str] = []
    queue: list[tuple[str, str]] = []
    for idx, t in enumerate(transcripts):
        queue.append(("turn", t))
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
    runner._build_turn_prompt = lambda *a, **k: "turn prompt"  # type: ignore[assignment]
    runner._save_transcript = lambda *a, **k: None  # type: ignore[assignment]
    runner._inject_memory = AsyncMock(return_value="")  # type: ignore[assignment]
    return runner, call_log


class TestShapeRunnerEvaluator:
    async def test_non_final_turn_bypasses_evaluator(self, config) -> None:
        runner, calls = _make_runner(
            max_attempts=3,
            config=config,
            transcripts=[_S_CONTINUE],
            eval_transcripts=[],
        )
        result = await runner.run_turn(_make_task(), ShapeConversation(issue_number=42))
        assert result.is_final is False
        assert all("evaluator" not in c for c in calls)

    async def test_ok_on_first_attempt(self, config) -> None:
        runner, calls = _make_runner(3, config, [_S_FINAL], [_OK])
        result = await runner.run_turn(_make_task(), ShapeConversation(issue_number=42))
        assert result.is_final is True
        assert len([c for c in calls if "evaluator" in c]) == 1
        assert len([c for c in calls if "evaluator" not in c]) == 1

    async def test_retry_then_ok(self, config) -> None:
        runner, calls = _make_runner(
            3,
            config,
            [_S_FINAL, _S_FINAL],
            [_retry("too-few-options"), _OK],
        )
        result = await runner.run_turn(_make_task(), ShapeConversation(issue_number=42))
        assert result.is_final is True
        assert len([c for c in calls if "evaluator" not in c]) == 2
        assert len([c for c in calls if "evaluator" in c]) == 2

    async def test_retry_exhaustion_escalates(self, config) -> None:
        runner, _ = _make_runner(
            2,
            config,
            [_S_FINAL, _S_FINAL],
            [_retry("missing-defer"), _retry("options-overlap")],
        )
        prs = MagicMock()
        prs.create_issue = AsyncMock(return_value=101)
        dedup = MagicMock()
        dedup.get = MagicMock(return_value=set())
        dedup.add = MagicMock()
        runner.bind_escalation_deps(prs, dedup)
        await runner.run_turn(_make_task(42), ShapeConversation(issue_number=42))
        prs.create_issue.assert_awaited_once()
        kwargs = prs.create_issue.call_args.kwargs
        assert {"hitl-escalation", "shape-stuck"} <= set(kwargs["labels"])
        assert "#42" in kwargs["title"]
        dedup.add.assert_called_once_with("shape_runner:42")

    async def test_dedup_hit_skips_escalation(self, config) -> None:
        runner, _ = _make_runner(1, config, [_S_FINAL], [_retry("missing-tradeoffs")])
        prs = MagicMock()
        prs.create_issue = AsyncMock()
        dedup = MagicMock()
        dedup.get = MagicMock(return_value={"shape_runner:42"})
        runner.bind_escalation_deps(prs, dedup)
        await runner.run_turn(_make_task(42), ShapeConversation(issue_number=42))
        prs.create_issue.assert_not_awaited()

    async def test_max_attempts_zero_disables_evaluator(self, config) -> None:
        runner, calls = _make_runner(0, config, [_S_FINAL], [])
        result = await runner.run_turn(_make_task(), ShapeConversation(issue_number=42))
        assert result.is_final is True
        assert all("evaluator" not in c for c in calls)

    async def test_unbound_escalation_logs_only(self, config, caplog) -> None:
        runner, _ = _make_runner(
            1, config, [_S_FINAL], [_retry("dropped-discover-question")]
        )
        with caplog.at_level(logging.WARNING, logger="hydraflow.shape"):
            await runner.run_turn(_make_task(99), ShapeConversation(issue_number=42))
        assert any("PRManager not bound" in r.message for r in caplog.records)
