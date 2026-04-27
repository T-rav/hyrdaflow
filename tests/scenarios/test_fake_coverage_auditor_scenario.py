"""MockWorld scenario for FakeCoverageAuditorLoop (spec §4.7).

Two scenarios covering the two gap subtypes the loop detects:

* ``test_uncassetted_surface_files_adapter_gap`` — a fake's public
  adapter method has no matching cassette. The loop files exactly one
  ``fake-coverage-gap`` + ``adapter-surface`` issue.
* ``test_unused_test_helper_files_helper_gap`` — a fake exposes a
  ``script_*`` helper that no scenario invokes (grep returns False).
  The loop files exactly one ``fake-coverage-gap`` + ``test-helper``
  issue.

The loop's external surface — ``_reconcile_closed_escalations``
(``gh issue list``) and ``_grep_scenario_for_helper`` (``rg`` over
``tests/scenarios/``) — is stubbed via scenario-seeded ports
``fake_coverage_reconcile_closed`` / ``fake_coverage_grep`` which the
catalog builder in ``loop_registrations.py`` reads and monkey-patches
onto the instantiated loop — mirroring the F7 FlakeTracker
(``eac5fc72``) and S6 SkillPromptEval (``93ebf387``) patterns.

On-disk layout is seeded under ``config.repo_root`` (which
``make_bg_loop_deps`` sets to ``<tmp_path>/repo``), so the loop's
``repo / "src" / "mockworld" / "fakes"`` (post-Task-1.1 relocation;
see ADR-0052 landing in PR B) and
``repo / "tests" / "trust" / "contracts" / "cassettes"`` paths resolve
to real seeded files.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import yaml

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class TestFakeCoverageAuditor:
    """§4.7 — fake-coverage drift MockWorld scenarios."""

    async def test_uncassetted_surface_files_adapter_gap(self, tmp_path) -> None:
        """Public fake method w/o cassette → one adapter-surface gap filed."""
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=501)

        # Seed under config.repo_root (= tmp_path / "repo" per make_bg_loop_deps).
        repo = tmp_path / "repo"
        # Seed at the new canonical Fake location (post-Task-1.1 of the
        # sandbox-tier scenario testing track; see ADR-0052 landing in PR B).
        fake_dir = repo / "src" / "mockworld" / "fakes"
        fake_dir.mkdir(parents=True)
        (fake_dir / "fake_github.py").write_text(
            "class FakeGitHub:\n"
            "    async def create_issue(self, title, body, labels): ...\n"
            "    async def close_issue(self, num): ...\n"
        )
        cassettes = repo / "tests" / "trust" / "contracts" / "cassettes" / "github"
        cassettes.mkdir(parents=True)
        # Only create_issue is cassetted → close_issue surfaces as the gap.
        (cassettes / "create_issue.yaml").write_text(
            yaml.safe_dump({"input": {"command": "create_issue"}, "output": {}})
        )

        _seed_ports(
            world,
            pr_manager=fake_pr,
            fake_coverage_reconcile_closed=AsyncMock(return_value=None),
            # Helpers (none present in this fake) — trivially True to short-circuit.
            fake_coverage_grep=AsyncMock(return_value=True),
        )

        await world.run_with_loops(["fake_coverage_auditor"], cycles=1)

        assert fake_pr.create_issue.await_count == 1
        args = fake_pr.create_issue.await_args.args
        title, _body, labels = args[0], args[1], args[2]
        assert "close_issue" in title
        assert "FakeGitHub" in title
        assert "adapter-surface" in labels
        assert "fake-coverage-gap" in labels
        assert "hydraflow-find" in labels

    async def test_unused_test_helper_files_helper_gap(self, tmp_path) -> None:
        """Fake ``script_*`` helper with no scenario caller → one test-helper gap."""
        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=502)

        repo = tmp_path / "repo"
        # Seed at the new canonical Fake location (post-Task-1.1 of the
        # sandbox-tier scenario testing track; see ADR-0052 landing in PR B).
        fake_dir = repo / "src" / "mockworld" / "fakes"
        fake_dir.mkdir(parents=True)
        (fake_dir / "fake_docker.py").write_text(
            "class FakeDocker:\n    def script_run(self, events): ...\n"
        )
        # Empty docker cassette dir so no spurious surface filings fire
        # (script_run is a helper, not adapter surface, so it wouldn't anyway).
        (repo / "tests" / "trust" / "contracts" / "cassettes" / "docker").mkdir(
            parents=True
        )

        _seed_ports(
            world,
            pr_manager=fake_pr,
            fake_coverage_reconcile_closed=AsyncMock(return_value=None),
            fake_coverage_grep=AsyncMock(return_value=False),  # helper uncalled
        )

        await world.run_with_loops(["fake_coverage_auditor"], cycles=1)

        assert fake_pr.create_issue.await_count == 1
        args = fake_pr.create_issue.await_args.args
        title, _body, labels = args[0], args[1], args[2]
        assert "script_run" in title
        assert "FakeDocker" in title
        assert "test-helper" in labels
        assert "fake-coverage-gap" in labels
        assert "hydraflow-find" in labels
