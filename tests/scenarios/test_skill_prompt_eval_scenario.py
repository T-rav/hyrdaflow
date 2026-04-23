"""MockWorld scenario for SkillPromptEvalLoop (spec §4.6).

Two scenarios covering the dual role of the loop:

* ``test_drift_regression_files_issue`` — backstop role. One hand-crafted
  case regressed PASS→FAIL; the loop files exactly one
  ``skill-prompt-drift`` issue with the expected title fragments.
* ``test_weak_case_sampling_files_issue`` — weak-case role. 10
  ``provenance: learning-loop`` cases all PASS while the expected catcher
  is the same skill that passed them. The sampled 10% surface at least
  one ``corpus-case-weak`` issue.

The loop's external surface (``_run_corpus``, ``_reconcile_closed_escalations``)
is stubbed via scenario-seeded ports ``skill_corpus_runner`` /
``skill_reconcile_closed`` which the catalog builder in
``loop_registrations.py`` reads and monkey-patches onto the instantiated
loop — mirroring the F7 FlakeTracker pattern (`eac5fc72`).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class TestSkillPromptEval:
    """§4.6 — skill-prompt drift + weak-case audit MockWorld scenarios."""

    async def test_drift_regression_files_issue(self, tmp_path) -> None:
        """One hand-crafted case regressed PASS→FAIL → one drift issue filed."""
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=301)

        # Seed a state mock whose last-green snapshot pre-declares both
        # cases as PASS; the corpus below flips case_shrink_001 to FAIL.
        fake_state = MagicMock()
        fake_state.get_skill_prompt_last_green.return_value = {
            "case_shrink_001": "PASS",
            "case_scope_002": "PASS",
        }
        fake_state.get_skill_prompt_attempts.return_value = 0
        fake_state.inc_skill_prompt_attempts.return_value = 1

        corpus_result: list[dict] = [
            {
                "case_id": "case_shrink_001",
                "skill": "diff_sanity",
                "status": "FAIL",
                "provenance": "hand-crafted",
                "expected_catcher": "diff_sanity",
            },
            {
                "case_id": "case_scope_002",
                "skill": "scope_check",
                "status": "PASS",
                "provenance": "hand-crafted",
                "expected_catcher": "scope_check",
            },
        ]

        _seed_ports(
            world,
            pr_manager=fake_pr,
            skill_prompt_state=fake_state,
            skill_corpus_runner=AsyncMock(return_value=corpus_result),
            skill_reconcile_closed=AsyncMock(return_value=None),
        )

        await world.run_with_loops(["skill_prompt_eval"], cycles=1)

        assert fake_pr.create_issue.await_count == 1
        args = fake_pr.create_issue.await_args.args
        title, _body, labels = args[0], args[1], args[2]
        assert "diff_sanity" in title
        assert "case_shrink_001" in title
        assert "skill-prompt-drift" in labels
        assert "hydraflow-find" in labels

    async def test_weak_case_sampling_files_issue(self, tmp_path) -> None:
        """10 learning-loop cases all PASS — sampled 10% surface a weak-case issue."""
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=302)

        fake_state = MagicMock()
        fake_state.get_skill_prompt_last_green.return_value = {}
        fake_state.get_skill_prompt_attempts.return_value = 0
        fake_state.inc_skill_prompt_attempts.return_value = 1

        corpus_result: list[dict] = [
            {
                "case_id": f"case_learn_{i:03d}",
                "skill": "diff_sanity",
                "status": "PASS",
                "provenance": "learning-loop",
                "expected_catcher": "diff_sanity",
            }
            for i in range(10)
        ]

        _seed_ports(
            world,
            pr_manager=fake_pr,
            skill_prompt_state=fake_state,
            skill_corpus_runner=AsyncMock(return_value=corpus_result),
            skill_reconcile_closed=AsyncMock(return_value=None),
        )

        await world.run_with_loops(["skill_prompt_eval"], cycles=1)

        weak_calls = [
            c
            for c in fake_pr.create_issue.await_args_list
            if len(c.args) > 2 and "corpus-case-weak" in c.args[2]
        ]
        assert len(weak_calls) >= 1
