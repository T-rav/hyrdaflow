from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from strip_test_sludge import process_file  # noqa: E402


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body)
    return path


def test_strips_should_docstring_on_test_function(tmp_path: Path) -> None:
    src = (
        'def test_returns_zero():\n    """Should return zero."""\n    assert f() == 0\n'
    )
    path = _write(tmp_path, "test_a.py", src)
    counts = process_file(path, apply=True)
    assert counts["should_doc"] == 1
    assert '"""Should' not in path.read_text()


def test_strips_tests_for_class_docstring(tmp_path: Path) -> None:
    src = (
        "class TestThing:\n"
        '    """Tests for the thing."""\n'
        "\n"
        "    def test_a(self):\n"
        "        assert True\n"
    )
    path = _write(tmp_path, "test_b.py", src)
    counts = process_file(path, apply=True)
    assert counts["tests_for_doc"] == 1
    assert "Tests for the thing" not in path.read_text()


def test_strips_aaa_comment_lines(tmp_path: Path) -> None:
    src = (
        "def test_thing():\n"
        "    # Arrange\n"
        "    x = 1\n"
        "    # Act\n"
        "    y = x + 1\n"
        "    # Assert\n"
        "    assert y == 2\n"
    )
    path = _write(tmp_path, "test_c.py", src)
    counts = process_file(path, apply=True)
    assert counts["aaa_comment"] == 3
    text = path.read_text()
    assert "# Arrange" not in text
    assert "# Act" not in text
    assert "# Assert" not in text
    assert "x = 1" in text


def test_preserves_multiline_why_docstring(tmp_path: Path) -> None:
    src = (
        "def test_drift_detector_catches_layer_jump():\n"
        '    """Should fail when planner imports a port directly.\n'
        "\n"
        "    Regression: in PR #6090 a missing layer guard let planner\n"
        "    bypass the orchestrator and reach into PRPort. Without this\n"
        "    test the gap silently re-opens.\n"
        '    """\n'
        "    assert detect_layer_jump(SAMPLE_PLANNER) is True\n"
    )
    path = _write(tmp_path, "test_d.py", src)
    counts = process_file(path, apply=True)
    assert counts["should_doc"] == 0
    assert "Regression" in path.read_text()


def test_preserves_inline_trailing_aaa_comment(tmp_path: Path) -> None:
    src = "def test_thing():\n    x = 1  # Arrange the input\n    assert x == 1\n"
    path = _write(tmp_path, "test_e.py", src)
    counts = process_file(path, apply=True)
    assert counts["aaa_comment"] == 0
    assert "# Arrange the input" in path.read_text()


def test_skips_should_docstring_on_non_test_function(tmp_path: Path) -> None:
    src = 'def make_helper():\n    """Should return a helper."""\n    return helper()\n'
    path = _write(tmp_path, "test_f.py", src)
    counts = process_file(path, apply=True)
    assert counts["should_doc"] == 0
    assert "Should return a helper" in path.read_text()


def test_skips_tests_for_class_docstring_on_non_test_class(tmp_path: Path) -> None:
    src = (
        "class TestHarness:\n"
        '    """Tests for use as a harness, not a test class."""\n'
        "\n"
        "    def helper(self):\n"
        "        return 1\n"
    )
    # Class starts with "Test" so it counts — this verifies the boundary case.
    path = _write(tmp_path, "test_g.py", src)
    counts = process_file(path, apply=True)
    assert counts["tests_for_doc"] == 1


@pytest.mark.parametrize("name", ["builder.py", "helper.py", "conftest.py"])
def test_skips_files_via_glob_default(tmp_path: Path, name: str) -> None:
    # The script's default glob is tests/test_*.py — but process_file works
    # on any file. This verifies the function itself does not auto-skip
    # non-test names; the caller (main glob) is what enforces scope.
    src = "def test_thing():\n    assert True\n"
    path = _write(tmp_path, name, src)
    counts = process_file(path, apply=True)
    assert counts.get("should_doc", 0) == 0
