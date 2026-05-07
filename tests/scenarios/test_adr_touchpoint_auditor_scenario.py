"""MockWorld scenario for AdrTouchpointAuditorLoop (ADR-0056).

Drives the loop end-to-end with a stubbed `gh pr list` and a real
``ADRIndex`` over an on-disk fixture, asserts that drift in a single
merged PR produces exactly one `hydraflow-find` issue with the right
labels.

External surface stubbed via the scenario port-seeding pattern (mirrors
the F7 FlakeTracker / S6 SkillPromptEval / fake-coverage scenarios):

* ``adr_touchpoint_list_merged_prs`` → replaces ``gh pr list``.
* ``adr_touchpoint_reconcile_closed`` → no-op for closed-issue reconcile.
* ``adr_touchpoint_index`` → real ``ADRIndex`` over the seeded ADR dir.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


def _write_adr(adr_dir, *, number: int, title: str, related: list[str]) -> None:
    related_block = ", ".join(f"`{f}`" for f in related)
    body = (
        f"# ADR-{number:04d}: {title}\n\n"
        f"- **Status:** Accepted\n"
        f"- **Date:** 2026-01-01\n"
        f"- **Related:** {related_block}\n\n"
        f"## Context\n\nFixture body.\n"
    )
    (adr_dir / f"{number:04d}-{title.lower()}.md").write_text(body)


class TestAdrTouchpointAuditor:
    """ADR-0056 — drift detection MockWorld scenarios."""

    async def test_drift_files_one_finding(self, tmp_path) -> None:
        """Merged PR touches an ADR-cited src/ file → one drift issue filed."""
        from adr_index import ADRIndex  # noqa: PLC0415

        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=2001)

        repo = tmp_path / "repo"
        adr_dir = repo / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        _write_adr(adr_dir, number=24, title="alpha", related=["src/agent.py"])
        adr_index = ADRIndex(adr_dir)

        async def list_merged_prs(_cursor):
            return [
                {
                    "number": 8473,
                    "mergedAt": "2026-05-06T20:00:00Z",
                    "title": "feat: tweak agent",
                    "files": [{"path": "src/agent.py"}, {"path": "tests/x.py"}],
                }
            ]

        # Seed cursor so the loop scans (empty cursor would seed-and-return).
        from unittest.mock import MagicMock  # noqa: PLC0415

        state = MagicMock()
        state.get_adr_audit_cursor.return_value = "2026-05-01T00:00:00Z"
        state.get_adr_audit_attempts.return_value = 0
        state.inc_adr_audit_attempts.return_value = 1

        _seed_ports(
            world,
            pr_manager=fake_pr,
            adr_touchpoint_state=state,
            adr_touchpoint_index=adr_index,
            adr_touchpoint_list_merged_prs=list_merged_prs,
            adr_touchpoint_reconcile_closed=AsyncMock(return_value=None),
        )

        await world.run_with_loops(["adr_touchpoint_auditor"], cycles=1)

        assert fake_pr.create_issue.await_count == 1
        title, _body, labels = fake_pr.create_issue.await_args.args
        assert "ADR-0024" in title
        assert "PR #8473" in title
        assert "hydraflow-find" in labels
        assert "hydraflow-adr-drift" in labels

    async def test_no_drift_when_adr_in_diff(self, tmp_path) -> None:
        """ADR file in the diff → no issue filed."""
        from adr_index import ADRIndex  # noqa: PLC0415

        world = MockWorld(tmp_path)
        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=2002)

        repo = tmp_path / "repo"
        adr_dir = repo / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        _write_adr(adr_dir, number=24, title="alpha", related=["src/agent.py"])
        adr_index = ADRIndex(adr_dir)

        async def list_merged_prs(_cursor):
            return [
                {
                    "number": 8474,
                    "mergedAt": "2026-05-06T21:00:00Z",
                    "files": [
                        {"path": "src/agent.py"},
                        {"path": "docs/adr/0024-alpha.md"},
                    ],
                }
            ]

        from unittest.mock import MagicMock  # noqa: PLC0415

        state = MagicMock()
        state.get_adr_audit_cursor.return_value = "2026-05-01T00:00:00Z"
        state.get_adr_audit_attempts.return_value = 0
        state.inc_adr_audit_attempts.return_value = 1

        _seed_ports(
            world,
            pr_manager=fake_pr,
            adr_touchpoint_state=state,
            adr_touchpoint_index=adr_index,
            adr_touchpoint_list_merged_prs=list_merged_prs,
            adr_touchpoint_reconcile_closed=AsyncMock(return_value=None),
        )

        await world.run_with_loops(["adr_touchpoint_auditor"], cycles=1)

        fake_pr.create_issue.assert_not_awaited()
