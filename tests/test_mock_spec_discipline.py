"""Mock-spec discipline ratchet.

Ensures `unittest.mock.{AsyncMock,MagicMock,Mock}(SomePort)` calls in
`tests/` use `spec=SomePort` so attribute typos surface as
`AttributeError` at test time instead of silently passing.

The grandfather list at `tests/_mock_spec_grandfathered.yaml` lets the
existing fleet stay green. CI fails if the violation set grows beyond
the grandfather list. The grandfather list MAY shrink as people clean up.

See `docs/superpowers/specs/2026-05-07-tier2-enforcement-batch-design.md` §3.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from _mock_spec_detector import Violation, detect_violations  # noqa: E402

TESTS_ROOT = REPO_ROOT / "tests"
GRANDFATHER = REPO_ROOT / "tests" / "_mock_spec_grandfathered.yaml"


def _load_grandfather() -> set[tuple[str, int]]:
    if not GRANDFATHER.exists():
        return set()
    raw = yaml.safe_load(GRANDFATHER.read_text()) or {}
    return {(e["path"], e["line"]) for e in raw.get("entries", [])}


def _scan_all_violations() -> list[Violation]:
    findings: list[Violation] = []
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        if "_mock_spec_fixtures" in path.parts:
            continue  # synthetic fixtures by design contain violations
        findings.extend(detect_violations(path))
    return findings


def test_no_new_mock_spec_violations() -> None:
    grandfathered = _load_grandfather()
    current = {
        (str(v.path.relative_to(REPO_ROOT)), v.lineno) for v in _scan_all_violations()
    }
    new_violations = current - grandfathered
    if new_violations:
        msg = (
            "New Mock-spec discipline violations detected:\n"
            + "\n".join(f"  {p}:{ln}" for p, ln in sorted(new_violations))
            + "\n\nFix by passing `spec=<PortType>` to AsyncMock/MagicMock/Mock."
            + "\nSee docs/wiki/dark-factory.md §4.2 for context."
        )
        pytest.fail(msg)


def test_grandfather_list_does_not_contain_false_positives() -> None:
    """Grandfather entries must currently be real violations."""
    grandfathered = _load_grandfather()
    current = {
        (str(v.path.relative_to(REPO_ROOT)), v.lineno) for v in _scan_all_violations()
    }
    stale = grandfathered - current
    if stale:
        msg = (
            "Stale grandfather entries (call sites no longer violate the rule "
            "— please remove from tests/_mock_spec_grandfathered.yaml):\n"
            + "\n".join(f"  {p}:{ln}" for p, ln in sorted(stale))
        )
        pytest.fail(msg)
