"""MockWorld scenario for CorpusLearningLoop (spec §4.1 v2).

Two scenarios cover the loop's ends-of-the-world:

* ``test_no_escape_signals_no_file`` — no open issues carrying the
  ``skill-escape`` label. The loop ticks, sees zero signals, and files
  nothing. ``cases_filed == 0``.
* ``test_escape_signal_produces_case`` — one parseable escape issue is
  seeded via FakeGitHub. The loop reads it, synthesizes a
  :class:`SynthesizedCase`, runs the three-gate validator, materializes
  the case on disk, and files one PR via the stubbed ``auto_pr`` seam.
  ``cases_filed >= 1``.

The loop's external surfaces are handled as follows:

* :meth:`PRManager.list_issues_by_label` is served by ``FakeGitHub``
  directly (no monkey-patching needed — the fake already returns the
  correct row shape).
* :func:`auto_pr.open_automated_pr_async` is stubbed via the
  ``corpus_learning_auto_pr`` port seeded through
  :func:`tests.scenarios.helpers.loop_port_seeding.seed_ports` so no
  ``git`` or ``gh`` subprocess actually runs.

Materialization writes under ``config.repo_root / tests / trust /
adversarial / cases / <slug>`` — by default that is the temporary
``tmp_path`` MockWorld hands out, so the sandbox never leaks onto the
real repo.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


def _iso_now_offset(days: int) -> str:
    """ISO-8601 UTC timestamp ``days`` ago (negative → past)."""
    return (_dt.datetime.now(_dt.UTC) + _dt.timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _well_formed_body() -> str:
    """Escape-issue body the synthesizer can parse cleanly.

    Envelope mirrors the one in ``tests/test_corpus_learning_integration``
    — kept inline here so the scenario doesn't import from a sibling
    suite that already owns a per-module autouse fixture.
    """
    return "\n".join(
        [
            "Symbol rename leaves callsite stale.",
            "",
            "Expected-Catcher: diff-sanity",
            "Keyword: renamed",
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

    The loop only reads ``status``/``pr_url``/``error``, and the real
    dataclass is frozen with a validated status literal. Keeping the
    stub local avoids coupling this scenario to ``auto_pr``'s
    construction rules.
    """

    def __init__(
        self, *, status: str, pr_url: str | None = None, error: str | None = None
    ) -> None:
        self.status = status
        self.pr_url = pr_url
        self.branch = "corpus-learning/scenario-branch"
        self.error = error


class TestCorpusLearningScenario:
    """§4.1 v2 — adversarial corpus learning MockWorld scenarios."""

    async def test_no_escape_signals_no_file(self, tmp_path) -> None:
        """Empty FakeGitHub → loop ticks, synthesizes nothing, files nothing."""
        world = MockWorld(tmp_path)

        open_calls: list[dict[str, Any]] = []

        async def fake_open(**kwargs: Any) -> _AutoPrResultStub:
            open_calls.append(kwargs)
            return _AutoPrResultStub(status="opened", pr_url="x/y/pull/1")

        _seed_ports(world, corpus_learning_auto_pr=fake_open)

        stats = await world.run_with_loops(["corpus_learning"], cycles=1)

        assert stats["corpus_learning"]["escape_issues_seen"] == 0, stats
        assert stats["corpus_learning"]["cases_synthesized"] == 0, stats
        assert stats["corpus_learning"]["cases_validated"] == 0, stats
        assert stats["corpus_learning"]["cases_filed"] == 0, stats
        assert open_calls == [], (
            "PR opener must not be called when there are no escape signals"
        )

    async def test_escape_signal_produces_case(self, tmp_path) -> None:
        """Parseable escape issue → synthesize → validate → materialize → file PR."""
        world = MockWorld(tmp_path)

        # Seed a recent, well-formed escape issue via FakeGitHub. The
        # default updated_at is 2026-01-01 which is outside the loop's
        # 30-day lookback window on today's clock, so we explicitly
        # bump it into the window.
        issue_number = 4242
        world.github.add_issue(
            number=issue_number,
            title="diff-sanity missed renamed symbol",
            body=_well_formed_body(),
            labels=["skill-escape"],
        )
        world.github.set_issue_updated_at(issue_number, _iso_now_offset(-1))

        open_calls: list[dict[str, Any]] = []

        async def fake_open(**kwargs: Any) -> _AutoPrResultStub:
            open_calls.append(kwargs)
            return _AutoPrResultStub(
                status="opened",
                pr_url="https://github.com/hydra/hydraflow/pull/999",
            )

        _seed_ports(world, corpus_learning_auto_pr=fake_open)

        stats = await world.run_with_loops(["corpus_learning"], cycles=1)

        # Counters prove the full ladder ran.
        assert stats["corpus_learning"]["escape_issues_seen"] == 1, stats
        assert stats["corpus_learning"]["cases_synthesized"] == 1, stats
        assert stats["corpus_learning"]["cases_validated"] == 1, stats
        assert stats["corpus_learning"]["cases_filed"] >= 1, stats

        # The stubbed PR opener saw exactly one call with the expected
        # title + label shape.
        assert len(open_calls) == 1
        kwargs = open_calls[0]
        assert kwargs["pr_title"] == (
            f"test(trust): corpus-learning case for escape #{issue_number}"
        )
        labels = kwargs["labels"]
        assert "hydraflow-agent" in labels
        assert "corpus-learning" in labels

        # The case directory actually landed on disk under the tmp sandbox.
        # ``make_bg_loop_deps`` roots the loop's ``config.repo_root`` at
        # ``tmp_path / "repo"``, so the materializer writes under there —
        # not under tmp_path itself.
        slug = "diff-sanity-missed-renamed-symbol"
        case_dir = (
            tmp_path / "repo" / "tests" / "trust" / "adversarial" / "cases" / slug
        )
        assert (case_dir / "README.md").exists()
