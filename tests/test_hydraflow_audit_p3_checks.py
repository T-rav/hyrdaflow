"""Tests for P3 (Testing / MockWorld) check functions."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.hydraflow_audit import registry  # noqa: F401
from scripts.hydraflow_audit.checks import p3_testing  # noqa: F401
from scripts.hydraflow_audit.models import CheckContext, Status


def _ctx(root: Path, *, has_ui: bool = False) -> CheckContext:
    return CheckContext(root=root, has_ui=has_ui)


def _run(check_id: str, ctx: CheckContext):
    fn = registry.get(check_id)
    assert fn is not None
    return fn(ctx)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --- Simple presence ------------------------------------------------------


@pytest.mark.parametrize(
    ("check_id", "relpath"),
    [
        ("P3.1", "tests/scenarios"),
        ("P3.16", "tests/regressions"),
    ],
)
def test_directory_presence_checks(check_id: str, relpath: str, tmp_path: Path) -> None:
    (tmp_path / relpath).mkdir(parents=True)
    assert _run(check_id, _ctx(tmp_path)).status is Status.PASS


def test_directory_presence_fails_when_absent(tmp_path: Path) -> None:
    assert _run("P3.1", _ctx(tmp_path)).status is Status.FAIL


def test_root_conftest_requires_fixtures(tmp_path: Path) -> None:
    _write(
        tmp_path / "tests" / "conftest.py",
        "import pytest\n\n\n@pytest.fixture\ndef foo(): ...",
    )
    assert _run("P3.4", _ctx(tmp_path)).status is Status.PASS


def test_root_conftest_without_fixtures_fails(tmp_path: Path) -> None:
    _write(tmp_path / "tests" / "conftest.py", "# nothing here\n")
    assert _run("P3.4", _ctx(tmp_path)).status is Status.FAIL


# --- MockWorld ------------------------------------------------------------


def test_mock_world_fixture_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / "tests" / "scenarios" / "conftest.py",
        "import pytest\n\n\n@pytest.fixture\ndef mock_world():\n    return object()\n",
    )
    assert _run("P3.2", _ctx(tmp_path)).status is Status.PASS


def test_mock_world_fixture_missing_fails(tmp_path: Path) -> None:
    _write(tmp_path / "tests" / "scenarios" / "conftest.py", "# empty\n")
    assert _run("P3.2", _ctx(tmp_path)).status is Status.FAIL


def test_scenario_fakes_count(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "mockworld" / "fakes" / "f.py",
        "class FakeVCS: ...\nclass FakeLLM: ...\nclass FakeClock: ...\n",
    )
    assert _run("P3.3", _ctx(tmp_path)).status is Status.PASS


def test_scenario_fakes_under_three_fails(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "mockworld" / "fakes" / "f.py",
        "class FakeOnly: ...\n",
    )
    assert _run("P3.3", _ctx(tmp_path)).status is Status.FAIL


def test_scenario_result_type_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / "tests" / "scenarios" / "results.py",
        "from dataclasses import dataclass\n\n@dataclass\nclass ScenarioResult:\n    ok: bool\n",
    )
    assert _run("P3.12", _ctx(tmp_path)).status is Status.PASS


def test_scenario_result_type_missing_fails(tmp_path: Path) -> None:
    (tmp_path / "tests" / "scenarios").mkdir(parents=True)
    assert _run("P3.12", _ctx(tmp_path)).status is Status.FAIL


def test_fake_clock_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / "tests" / "scenarios" / "clock.py",
        "class FakeClock: ...\n",
    )
    assert _run("P3.13", _ctx(tmp_path)).status is Status.PASS


def test_fake_clock_missing_fails(tmp_path: Path) -> None:
    (tmp_path / "tests" / "scenarios").mkdir(parents=True)
    assert _run("P3.13", _ctx(tmp_path)).status is Status.FAIL


def test_mock_inheritance_warns(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "mockworld" / "fakes" / "bad.py",
        "from unittest.mock import AsyncMock\n\nclass FakeVCS(AsyncMock): ...\n",
    )
    assert _run("P3.14", _ctx(tmp_path)).status is Status.WARN


def test_stateful_fakes_pass(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "mockworld" / "fakes" / "good.py",
        "class FakeVCS:\n    def __init__(self): self.issues = {}\n",
    )
    assert _run("P3.14", _ctx(tmp_path)).status is Status.PASS


def test_fault_injection_api_detected(tmp_path: Path) -> None:
    _write(
        tmp_path / "tests" / "scenarios" / "world.py",
        "class MockWorld:\n    def fail_service(self, name): ...\n    def heal_service(self, name): ...\n",
    )
    assert _run("P3.15", _ctx(tmp_path)).status is Status.PASS


def test_fault_injection_missing_fails(tmp_path: Path) -> None:
    _write(
        tmp_path / "tests" / "scenarios" / "world.py",
        "class MockWorld:\n    pass\n",
    )
    assert _run("P3.15", _ctx(tmp_path)).status is Status.FAIL


# --- Factories ------------------------------------------------------------


def test_factory_class_detected(tmp_path: Path) -> None:
    _write(tmp_path / "tests" / "factories.py", "class IssueFactory: ...\n")
    assert _run("P3.5", _ctx(tmp_path)).status is Status.PASS


def test_factory_missing_fails(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    assert _run("P3.5", _ctx(tmp_path)).status is Status.FAIL


# --- pyproject + Makefile -------------------------------------------------


def test_coverage_floor_passes_at_70(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        "[tool.coverage.report]\nfail_under = 70\n",
    )
    assert _run("P3.6", _ctx(tmp_path)).status is Status.PASS


def test_coverage_floor_fails_below_70(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        "[tool.coverage.report]\nfail_under = 50\n",
    )
    assert _run("P3.6", _ctx(tmp_path)).status is Status.FAIL


def test_coverage_floor_absent_fails(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", "[tool.ruff]\n")
    assert _run("P3.6", _ctx(tmp_path)).status is Status.FAIL


@pytest.mark.parametrize(
    ("check_id", "target"),
    [("P3.7", "test"), ("P3.8", "scenario"), ("P3.9", "smoke")],
)
def test_make_target_detection(check_id: str, target: str, tmp_path: Path) -> None:
    _write(tmp_path / "Makefile", f"{target}:\n\techo run\n")
    assert _run(check_id, _ctx(tmp_path)).status is Status.PASS


def test_make_target_absent_fails(tmp_path: Path) -> None:
    _write(tmp_path / "Makefile", "other:\n\techo\n")
    assert _run("P3.8", _ctx(tmp_path)).status is Status.FAIL


def test_pytest_markers_registered(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        '[tool.pytest.ini_options]\nmarkers = ["scenario: runs scenarios", "integration: wires phases"]\n',
    )
    assert _run("P3.17", _ctx(tmp_path)).status is Status.PASS


def test_pytest_markers_missing_fails(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        '[tool.pytest.ini_options]\nmarkers = ["scenario: runs scenarios"]\n',
    )
    result = _run("P3.17", _ctx(tmp_path))
    assert result.status is Status.FAIL
    assert "integration" in result.message


# --- CI + conditional -----------------------------------------------------


def test_release_gating_detected_when_workflow_mentions_scenario(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / ".github" / "workflows" / "ci.yml",
        "jobs:\n  scenario:\n    runs-on: ubuntu-latest\n",
    )
    assert _run("P3.10", _ctx(tmp_path)).status is Status.PASS


def test_release_gating_missing_fails(tmp_path: Path) -> None:
    _write(tmp_path / ".github" / "workflows" / "ci.yml", "jobs:\n  lint: ...\n")
    assert _run("P3.10", _ctx(tmp_path)).status is Status.FAIL


def test_browser_e2e_na_without_ui(tmp_path: Path) -> None:
    assert _run("P3.11", _ctx(tmp_path, has_ui=False)).status is Status.NA


def test_browser_e2e_fails_when_ui_and_no_e2e(tmp_path: Path) -> None:
    assert _run("P3.11", _ctx(tmp_path, has_ui=True)).status is Status.FAIL


def test_browser_e2e_passes_when_dir_present(tmp_path: Path) -> None:
    (tmp_path / "tests" / "scenarios" / "browser").mkdir(parents=True)
    assert _run("P3.11", _ctx(tmp_path, has_ui=True)).status is Status.PASS


def test_integration_file_detected(tmp_path: Path) -> None:
    _write(tmp_path / "tests" / "test_foo_integration.py", "def test_x(): pass\n")
    assert _run("P3.18", _ctx(tmp_path)).status is Status.PASS


def test_integration_file_missing_fails(tmp_path: Path) -> None:
    _write(tmp_path / "tests" / "test_foo.py", "def test_x(): pass\n")
    assert _run("P3.18", _ctx(tmp_path)).status is Status.FAIL


_PYPROJECT_WITH_OPTIONAL = (
    '[project]\nname = "p"\nversion = "0"\n'
    '[project.optional-dependencies]\nextras = ["httpx>=0.27"]\n'
)


def test_top_level_optional_import_warns(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _PYPROJECT_WITH_OPTIONAL)
    _write(tmp_path / "tests" / "test_http.py", "import httpx\n\ndef test_x(): pass\n")
    assert _run("P3.19", _ctx(tmp_path)).status is Status.WARN


def test_inline_optional_import_passes(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", _PYPROJECT_WITH_OPTIONAL)
    _write(
        tmp_path / "tests" / "test_http.py",
        "def test_x():\n    import httpx  # inline — fine\n    assert httpx\n",
    )
    assert _run("P3.19", _ctx(tmp_path)).status is Status.PASS


def test_no_optional_deps_makes_check_na(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", '[project]\nname = "p"\nversion = "0"\n')
    _write(tmp_path / "tests" / "test_http.py", "import httpx\n\ndef test_x(): pass\n")
    assert _run("P3.19", _ctx(tmp_path)).status is Status.NA
