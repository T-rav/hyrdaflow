"""Regression test for issue #6739.

Bug: sentry_loop.py and report_issue_loop.py contain hardcoded "hydraflow-plan"
fallback strings that bypass the config's planner_label setting.  When
planner_label is empty (e.g. misconfiguration), these sites silently revert to
the hardcoded default rather than using the config-provided value or raising.

Expected behaviour after fix:
  - No inline "hydraflow-plan" string literals in sentry_loop.py or
    report_issue_loop.py — all label access goes through the config object.
  - If planner_label is unexpectedly empty the code should fail loudly rather
    than silently falling back to a hardcoded constant.

These tests intentionally assert the *correct* behaviour, so they are RED
against the current (buggy) code.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

SRC_DIR = Path(__file__).resolve().parent.parent.parent / "src"

_SENTRY_ISSUE = {
    "id": "99999",
    "title": "RuntimeError: boom",
    "culprit": "src/app.py in run",
    "count": "7",
    "firstSeen": "2026-04-01T00:00:00Z",
    "lastSeen": "2026-04-10T00:00:00Z",
    "level": "error",
    "permalink": "https://sentry.io/issues/99999/",
    "shortId": "HYDRA-99999",
}


def _make_deps():
    from base_background_loop import LoopDeps

    deps = MagicMock(spec=LoopDeps)
    deps.event_bus = AsyncMock()
    deps.stop_event = MagicMock()
    deps.status_cb = MagicMock()
    deps.enabled_cb = MagicMock(return_value=True)
    deps.sleep_fn = AsyncMock()
    deps.interval_cb = None
    return deps


def _make_sentry_loop(config):
    from config import Credentials
    from sentry_loop import SentryLoop

    object.__setattr__(config, "sentry_org", "test-org")
    object.__setattr__(config, "sentry_project_filter", "")
    creds = Credentials(sentry_auth_token="sntryu_test")
    return SentryLoop(
        config=config,
        prs=MagicMock(),
        deps=_make_deps(),
        credentials=creds,
    )


# ---------------------------------------------------------------------------
# Source-level: no hardcoded "hydraflow-plan" string literals
# ---------------------------------------------------------------------------


def _collect_string_literals(filepath: Path) -> list[str]:
    """Return all string-literal values in *filepath* via AST walking."""
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append(node.value)
    return literals


class TestNoHardcodedPlanLabel:
    """Issue #6739 — no inline 'hydraflow-plan' string constant in loop files."""

    def test_sentry_loop_has_no_hardcoded_plan_label(self) -> None:
        """sentry_loop.py must not contain a 'hydraflow-plan' string literal."""
        literals = _collect_string_literals(SRC_DIR / "sentry_loop.py")
        assert "hydraflow-plan" not in literals, (
            "sentry_loop.py still contains a hardcoded 'hydraflow-plan' "
            "string literal — the fallback should come from config, not "
            "an inline constant"
        )

    def test_report_issue_loop_has_no_hardcoded_plan_label(self) -> None:
        """report_issue_loop.py must not contain a 'hydraflow-plan' string literal."""
        literals = _collect_string_literals(SRC_DIR / "report_issue_loop.py")
        assert "hydraflow-plan" not in literals, (
            "report_issue_loop.py still contains a hardcoded 'hydraflow-plan' "
            "string literal — the fallback should come from config, not "
            "an inline constant"
        )


# ---------------------------------------------------------------------------
# Behavioural: empty planner_label must not silently produce "hydraflow-plan"
# ---------------------------------------------------------------------------


class TestSentryLoopPlanLabelFallback:
    """Issue #6739 — SentryLoop._build_issue_description must not silently
    fall back to 'hydraflow-plan' when planner_label is empty."""

    def test_empty_planner_label_does_not_produce_hardcoded_fallback(
        self, tmp_path: Path
    ) -> None:
        """When planner_label is somehow empty, the description must NOT
        contain the hardcoded 'hydraflow-plan' — it should either raise
        or use the config default."""
        config = ConfigFactory.create(
            repo_root=tmp_path,
            planner_label=["my-custom-label"],
        )
        loop = _make_sentry_loop(config)

        # Bypass the Pydantic validator to simulate a misconfiguration
        # where planner_label ends up as an empty list.
        object.__setattr__(config, "planner_label", [])

        desc = loop._build_issue_description(_SENTRY_ISSUE, "my-project", "")

        # The buggy code falls back to the hardcoded "hydraflow-plan".
        # Correct behaviour: raise an error or use the validated default.
        assert "hydraflow-plan" not in desc, (
            "SentryLoop._build_issue_description silently fell back to the "
            "hardcoded 'hydraflow-plan' instead of raising or using the "
            "config-provided planner label"
        )
