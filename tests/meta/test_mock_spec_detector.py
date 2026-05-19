"""Meta-tests for `src/_mock_spec_detector.py`.

Synthetic fixtures under `tests/meta/_mock_spec_fixtures/` exercise both
detection rules. The detector is a pure AST walker — these tests do not
hit the real test suite.
"""

from __future__ import annotations

from pathlib import Path

from _mock_spec_detector import detect_violations

FIXTURES = Path(__file__).parent / "_mock_spec_fixtures"


def test_detects_positional_port_substitution() -> None:
    violations = detect_violations(FIXTURES / "violation_positional.py")
    lines = sorted(v.lineno for v in violations)
    assert lines == [12, 16], violations


def test_detects_bare_mock_on_port_annotated_target() -> None:
    violations = detect_violations(FIXTURES / "violation_annotated.py")
    lines = sorted(v.lineno for v in violations)
    assert lines == [9], violations


def test_compliant_file_yields_no_violations() -> None:
    violations = detect_violations(FIXTURES / "compliant.py")
    assert violations == []


def test_violation_includes_path_lineno_and_reason() -> None:
    [v] = detect_violations(FIXTURES / "violation_annotated.py")
    assert v.path.name == "violation_annotated.py"
    assert v.lineno == 9
    assert "spec=" in v.reason
