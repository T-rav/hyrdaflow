"""Unit tests for DiscoverRunner ↔ discover-expander wiring (ADR-0063 W3a).

Asserts on the runner-level orchestration: the expander is dispatched
between attempts after the FIRST coherence failure, the bounded
``max_discover_expansions`` cap is respected (default 1), and the
queries the expander returned are threaded into the next discovery
prompt so the next attempt sees them.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from discover_runner import DiscoverRunner
from events import EventBus
from models import DiscoverResult


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
_OK_EVAL = "DISCOVER_COMPLETENESS_RESULT: OK\nSUMMARY: pass\n"
_EXPANDER_OUT = (
    "EXPANSION_QUERIES_START\n"
    "- Concrete query 1 grounded in failure reason.\n"
    "- Concrete query 2 about an unexplored persona.\n"
    "- Concrete query 3 about a measurable target.\n"
    "EXPANSION_QUERIES_END"
)


def _retry_eval(keyword: str = "paraphrase-only") -> str:
    return (
        f"DISCOVER_COMPLETENESS_RESULT: RETRY\n"
        f"SUMMARY: {keyword} — brief restates body\n"
        f"FINDINGS:\n- {keyword} — no new info present\n"
    )


def _make_runner(
    config,
    *,
    max_attempts: int,
    max_expansions: int,
    queue: list[tuple[str, str]],
) -> tuple[DiscoverRunner, list[str], list[str]]:
    """Build a runner whose ``_execute`` returns scripted transcripts.

    ``queue`` is consumed in order; each entry is ``(expected_kind,
    transcript)`` where ``expected_kind`` is one of ``"discover"``,
    ``"evaluator"``, ``"expander"``. The stub asserts each call matches
    the next expected kind so the test fails loudly on order drift.

    Returns the runner, the source-tag call log, and the list of
    prompts the discovery agent saw (for asserting that expanded
    queries were threaded in).
    """
    config.max_discover_attempts = max_attempts
    config.max_discover_expansions = max_expansions
    config.repo_root = Path("/tmp")
    config.dry_run = False
    runner = DiscoverRunner(config=config, event_bus=MagicMock(spec=EventBus))
    call_log: list[str] = []
    discover_prompts: list[str] = []
    _queue = list(queue)

    async def _fake_execute(_cmd, prompt, _cwd, event_data, **_kw):
        source = str(event_data.get("source", ""))
        call_log.append(source)
        expected_kind, content = _queue.pop(0)
        if expected_kind == "discover":
            assert source.startswith("discover:attempt"), source
            discover_prompts.append(prompt)
        elif expected_kind == "evaluator":
            assert source == "discover:evaluator", source
        elif expected_kind == "expander":
            assert source == "discover:expander", source
        else:
            raise AssertionError(f"unknown expected_kind={expected_kind!r}")
        return content

    runner._execute = AsyncMock(side_effect=_fake_execute)  # type: ignore[assignment]
    runner._build_command = lambda _w=None: ["claude"]  # type: ignore[assignment]
    runner._build_prompt = lambda t: f"BASE PROMPT for #{t.id}"  # type: ignore[assignment]
    runner._save_transcript = lambda *a, **k: None  # type: ignore[assignment]
    runner._inject_memory = AsyncMock(return_value="")  # type: ignore[assignment]
    runner._extract_result = lambda tx, n: DiscoverResult(  # type: ignore[assignment]
        issue_number=n, research_brief=tx
    )
    runner._extract_raw_brief = lambda tx: tx  # type: ignore[assignment]
    return runner, call_log, discover_prompts


class TestDiscoverRunnerExpander:
    """ADR-0063 W3a — the expander is the autonomous step inserted
    between coherence failure and HITL escalation."""

    async def test_first_coherence_failure_triggers_expander(self, config) -> None:
        """RETRY on attempt 1 → expander dispatches → OK on attempt 2."""
        runner, calls, prompts = _make_runner(
            config,
            max_attempts=3,
            max_expansions=1,
            queue=[
                ("discover", _D_START),
                ("evaluator", _retry_eval("paraphrase-only")),
                ("expander", _EXPANDER_OUT),
                ("discover", _D_START),
                ("evaluator", _OK_EVAL),
            ],
        )
        await runner.discover(_make_task(101))
        # Expander invoked exactly once.
        assert calls.count("discover:expander") == 1
        # Both discover attempts ran (initial + post-expansion).
        assert sum(1 for c in calls if c.startswith("discover:attempt")) == 2
        # The post-expansion prompt MUST carry the expanded queries.
        assert "Expanded Research Queries" in prompts[1]
        assert "Concrete query 1 grounded in failure reason." in prompts[1]
        # The first prompt did NOT carry expanded queries (nothing to inject yet).
        assert "Expanded Research Queries" not in prompts[0]

    async def test_max_expansions_cap_respected(self, config) -> None:
        """With max_expansions=1, a second coherence failure does NOT
        dispatch the expander again — the runner falls through to its
        normal retry → escalation path."""
        runner, calls, _ = _make_runner(
            config,
            max_attempts=3,
            max_expansions=1,
            queue=[
                ("discover", _D_START),
                ("evaluator", _retry_eval("paraphrase-only")),
                ("expander", _EXPANDER_OUT),
                ("discover", _D_START),
                ("evaluator", _retry_eval("hid-ambiguity")),
                # No expander here — cap exhausted; goes straight to next attempt.
                ("discover", _D_START),
                ("evaluator", _retry_eval("vague-criterion")),
            ],
        )
        prs = MagicMock()
        prs.create_issue = AsyncMock(return_value=999)
        dedup = MagicMock()
        dedup.get = MagicMock(return_value=set())
        dedup.add = MagicMock()
        runner.bind_escalation_deps(prs, dedup)

        await runner.discover(_make_task(202))
        # Exactly one expansion across the whole retry budget.
        assert calls.count("discover:expander") == 1
        # All three discover attempts consumed → escalation filed.
        assert sum(1 for c in calls if c.startswith("discover:attempt")) == 3
        prs.create_issue.assert_awaited_once()

    async def test_max_expansions_zero_disables_expander(self, config) -> None:
        """With max_expansions=0, the expander never dispatches — the
        runner reverts to the pre-W3a behavior (retry → escalate)."""
        runner, calls, prompts = _make_runner(
            config,
            max_attempts=2,
            max_expansions=0,
            queue=[
                ("discover", _D_START),
                ("evaluator", _retry_eval("paraphrase-only")),
                ("discover", _D_START),
                ("evaluator", _retry_eval("hid-ambiguity")),
            ],
        )
        prs = MagicMock()
        prs.create_issue = AsyncMock(return_value=1)
        dedup = MagicMock()
        dedup.get = MagicMock(return_value=set())
        dedup.add = MagicMock()
        runner.bind_escalation_deps(prs, dedup)

        await runner.discover(_make_task(303))
        assert "discover:expander" not in calls
        assert all("Expanded Research Queries" not in p for p in prompts)
        prs.create_issue.assert_awaited_once()

    async def test_expander_empty_output_does_not_consume_slot(self, config) -> None:
        """When the expander returns no queries, the slot is preserved —
        the next coherence failure may try expansion again."""
        empty_expander = "agent rambled but produced no marker block"
        runner, calls, prompts = _make_runner(
            config,
            max_attempts=3,
            max_expansions=1,
            queue=[
                ("discover", _D_START),
                ("evaluator", _retry_eval("paraphrase-only")),
                ("expander", empty_expander),  # produces no queries
                ("discover", _D_START),
                ("evaluator", _retry_eval("vague-criterion")),
                ("expander", _EXPANDER_OUT),  # second attempt succeeds
                ("discover", _D_START),
                ("evaluator", _OK_EVAL),
            ],
        )
        await runner.discover(_make_task(404))
        # Two expander dispatches — first produced nothing (slot
        # preserved), second produced queries (slot consumed).
        assert calls.count("discover:expander") == 2
        # The final discover prompt carries the second expander's queries.
        assert "Concrete query 1 grounded in failure reason." in prompts[-1]

    async def test_no_expansion_when_attempt_is_last(self, config) -> None:
        """The runner does not waste a dispatch when no further attempt
        will use it — expansion runs only between attempts, not after
        the final one."""
        runner, calls, _ = _make_runner(
            config,
            max_attempts=1,
            max_expansions=1,
            queue=[
                ("discover", _D_START),
                ("evaluator", _retry_eval("paraphrase-only")),
                # No expander here — attempt 1 was the last; runner
                # escalates instead.
            ],
        )
        prs = MagicMock()
        prs.create_issue = AsyncMock(return_value=1)
        dedup = MagicMock()
        dedup.get = MagicMock(return_value=set())
        dedup.add = MagicMock()
        runner.bind_escalation_deps(prs, dedup)

        await runner.discover(_make_task(505))
        assert "discover:expander" not in calls
        prs.create_issue.assert_awaited_once()
