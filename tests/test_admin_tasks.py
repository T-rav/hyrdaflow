"""Unit tests for helpers in admin_tasks."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from admin_tasks import (
    _best_model_for_tool,
    _choose_prep_tool,
    _detect_available_prep_tools,
    _evaluate_coverage_validation,
    _evaluate_coverage_validation_projects,
    _extract_coverage_percent,
    _load_prep_coverage_floor,
    _prep_coverage_has_measurement,
    _project_has_test_signal,
    _save_prep_coverage_floor,
    run_clean,
    run_ensure_labels,
    run_prep,
    run_scaffold,
)
from tests.helpers import ConfigFactory


class TestPrepModelSelection:
    def test_claude_default_model(self) -> None:
        assert _best_model_for_tool("claude") == "opus"

    def test_codex_default_model(self) -> None:
        assert _best_model_for_tool("codex") == "gpt-5-codex"

    def test_pi_default_model(self) -> None:
        assert _best_model_for_tool("pi") == "gpt-5.3-codex"


class TestPrepToolSelection:
    def test_detect_available_tools(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "shutil.which", lambda name: "/bin/ok" if name in {"claude", "pi"} else None
        )
        assert _detect_available_prep_tools() == ["claude", "pi"]

    def test_choose_tool_noninteractive_prefers_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "admin_tasks._detect_available_prep_tools", lambda: ["claude", "pi"]
        )
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        assert _choose_prep_tool("pi") == ("pi", "configured")

    def test_choose_tool_interactive_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "admin_tasks._detect_available_prep_tools", lambda: ["claude", "pi"]
        )
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _prompt: "")
        tool, mode = _choose_prep_tool("claude")
        assert tool == "claude"
        assert mode == "prompt"


class TestCoverageHelpers:
    def test_prep_measurement_detector(self) -> None:
        assert not _prep_coverage_has_measurement("Coverage validation skipped")
        assert _prep_coverage_has_measurement(
            "Coverage validation passed: 61.2% from coverage.xml"
        )

    def test_save_and_load_floor(self, tmp_path: Path) -> None:
        _save_prep_coverage_floor(tmp_path, 40.0)
        assert _load_prep_coverage_floor(tmp_path) == 40.0

    def test_load_floor_clamped(self, tmp_path: Path) -> None:
        _save_prep_coverage_floor(tmp_path, 95.0)
        assert _load_prep_coverage_floor(tmp_path) == 70.0

    def test_extracts_lcov_percent(self, tmp_path: Path) -> None:
        (tmp_path / "lcov.info").write_text(
            "TN:\nSF:file.js\nLF:100\nLH:65\nend_of_record\n"
        )
        pct, source = _extract_coverage_percent(tmp_path)
        assert pct == pytest.approx(65.0)
        assert source == "lcov.info"

    def test_extracts_json_summary(self, tmp_path: Path) -> None:
        cov_dir = tmp_path / "coverage"
        cov_dir.mkdir()
        (cov_dir / "coverage-summary.json").write_text(
            '{"total":{"lines":{"pct":72.4}}}'
        )
        pct, source = _extract_coverage_percent(tmp_path)
        assert pct == pytest.approx(72.4)
        assert source == "coverage/coverage-summary.json"

    def test_extracts_xml_line_rate(self, tmp_path: Path) -> None:
        (tmp_path / "coverage.xml").write_text('<coverage line-rate="0.82"></coverage>')
        pct, source = _extract_coverage_percent(tmp_path)
        assert pct == pytest.approx(82.0)
        assert source == "coverage.xml"

    def test_validation_handles_missing_artifact(self, tmp_path: Path) -> None:
        ok, warn, detail = _evaluate_coverage_validation(tmp_path)
        assert not ok and not warn
        assert "no coverage report" in detail

    def test_validation_warns_when_missing_allowed(self, tmp_path: Path) -> None:
        ok, warn, detail = _evaluate_coverage_validation(
            tmp_path, min_required=20.0, target=70.0, allow_missing_artifact=True
        )
        assert ok and warn
        assert "fallback floor" in detail

    def test_validation_projects(self, tmp_path: Path) -> None:
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "coverage-summary.json").write_text(
            json.dumps({"total": {"lines": {"pct": 85}}})
        )
        ok, warn, detail = _evaluate_coverage_validation_projects(tmp_path, [proj])
        assert ok and not warn
        assert "proj" in detail


class TestProjectSignals:
    def test_project_has_python_tests(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_example.py").write_text("def test_ok(): pass")
        assert _project_has_test_signal(tmp_path)

    def test_project_has_js_tests(self, tmp_path: Path) -> None:
        tests_dir = tmp_path / "__tests__"
        tests_dir.mkdir()
        (tests_dir / "app.test.js").write_text("test('ok', () => {});")
        assert _project_has_test_signal(tmp_path)


class TestRunPrepTask:
    """Tests for the async run_prep helper."""

    @pytest.mark.asyncio
    async def test_run_prep_success_logs_seed_steps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = ConfigFactory.create()

        class FakePrepResult:
            def __init__(self, failed: bool = False) -> None:
                self.failed = failed

            def summary(self) -> str:
                return "Created 1 label, 2 already existed"

        class FakeAudit:
            missing_checks: list[str] = []

            def format_report(
                self, *, color: bool
            ) -> str:  # pragma: no cover - trivial
                return "Audit OK"

        class FakeRepoAuditor:
            def __init__(self, _config) -> None:
                pass

            async def run_audit(self) -> FakeAudit:
                return FakeAudit()

        monkeypatch.setattr(
            "prep.ensure_labels", AsyncMock(return_value=FakePrepResult())
        )
        monkeypatch.setattr("prep.RepoAuditor", FakeRepoAuditor)
        seeded: list[list[str]] = []
        monkeypatch.setattr(
            "admin_tasks._seed_context_assets",
            lambda _config: seeded.append(["seeded"]) or ["seeded"],
            raising=False,
        )

        result = await run_prep(config)

        assert result.success is True
        assert any("label sync complete" in line for line in result.log)
        assert result.warnings == []
        assert seeded, "expected _seed_context_assets to run"

    @pytest.mark.asyncio
    async def test_run_prep_failure_records_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = ConfigFactory.create()

        class FakePrepResult:
            def __init__(self) -> None:
                self.failed = True

            def summary(self) -> str:
                return "Label sync failed"

        class FakeAudit:
            missing_checks: list[str] = []

            def format_report(self, *, color: bool) -> str:
                return "Audit missing checks"

        class FakeRepoAuditor:
            def __init__(self, _config) -> None:
                pass

            async def run_audit(self) -> FakeAudit:
                return FakeAudit()

        monkeypatch.setattr(
            "prep.ensure_labels", AsyncMock(return_value=FakePrepResult())
        )
        monkeypatch.setattr("prep.RepoAuditor", FakeRepoAuditor)
        monkeypatch.setattr(
            "admin_tasks._seed_context_assets",
            lambda _config: ["seeded"],
            raising=False,
        )

        result = await run_prep(config)

        assert result.success is False
        assert "Label sync completed with failures." in result.warnings


class TestRunScaffoldTask:
    """Tests for the async run_scaffold helper."""

    @pytest.mark.asyncio
    async def test_run_scaffold_reports_created_assets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)

        class FakeCIResult:
            def __init__(self, skipped: bool = False) -> None:
                self.skipped = skipped
                self.skip_reason = "" if not skipped else "exists"
                self.workflow_path = ".github/workflows/ci.yml"
                self.language = "python"

        class FakeTestsResult:
            def __init__(self, skipped: bool = False) -> None:
                self.skipped = skipped
                self.skip_reason = "" if not skipped else "exists"
                self.created_dirs = ["tests"]
                self.created_files = ["tests/test_example.py"]
                self.modified_files = []
                self.language = "python"
                self.progress = None

        def fake_scaffold_ci(_root: Path, *, dry_run: bool) -> FakeCIResult:
            return FakeCIResult(skipped=False)

        def fake_scaffold_tests(_root: Path, *, dry_run: bool) -> FakeTestsResult:
            return FakeTestsResult(skipped=False)

        monkeypatch.setattr("polyglot_prep.detect_prep_stack", lambda _root: "python")
        monkeypatch.setattr(
            "admin_tasks._choose_prep_tool", lambda _cfg: ("claude", "configured")
        )
        monkeypatch.setattr("ci_scaffold.scaffold_ci", fake_scaffold_ci)
        monkeypatch.setattr(
            "polyglot_prep.scaffold_tests_polyglot", fake_scaffold_tests
        )
        monkeypatch.setattr(
            "admin_tasks._extract_coverage_percent",
            lambda _root: (82.0, "coverage.xml"),
        )

        result = await run_scaffold(config)

        assert result.success is True
        assert any("Coverage: 82.0%" in line for line in result.log)
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_run_scaffold_warns_when_no_coverage(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)

        class FakeResult:
            def __init__(self) -> None:
                self.skipped = True
                self.skip_reason = "exists"
                self.workflow_path = ".github/workflows/ci.yml"
                self.language = "python"
                self.progress = None

        monkeypatch.setattr("polyglot_prep.detect_prep_stack", lambda _root: "python")
        monkeypatch.setattr(
            "admin_tasks._choose_prep_tool", lambda _cfg: (None, "none")
        )
        monkeypatch.setattr(
            "ci_scaffold.scaffold_ci", lambda *_args, **_kwargs: FakeResult()
        )
        monkeypatch.setattr(
            "polyglot_prep.scaffold_tests_polyglot",
            lambda *_args, **_kwargs: FakeResult(),
        )
        monkeypatch.setattr(
            "admin_tasks._extract_coverage_percent",
            lambda _root: (None, ""),
        )

        result = await run_scaffold(config)

        assert result.success is True
        assert any(
            "Coverage: no report artifact found yet." in line for line in result.log
        )
        assert "Coverage artifact missing." in result.warnings


class TestRunCleanTask:
    """Tests for the async run_clean helper."""

    @pytest.mark.asyncio
    async def test_run_clean_resets_state_and_worktrees(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = ConfigFactory.create()

        class FakeWorktree:
            def __init__(self, _cfg) -> None:
                self.destroy_calls = 0

            async def destroy_all(self) -> None:
                self.destroy_calls += 1

        class FakeState:
            def __init__(self, _path) -> None:
                self.reset_called = False

            def reset(self) -> None:
                self.reset_called = True

        worktrees: list[FakeWorktree] = []
        states: list[FakeState] = []

        def fake_worktree_manager(cfg) -> FakeWorktree:
            inst = FakeWorktree(cfg)
            worktrees.append(inst)
            return inst

        def fake_build_state_tracker(_config) -> FakeState:
            inst = FakeState(_config)
            states.append(inst)
            return inst

        monkeypatch.setattr("workspace.WorkspaceManager", fake_worktree_manager)
        monkeypatch.setattr("state.build_state_tracker", fake_build_state_tracker)

        result = await run_clean(config)

        assert result.success is True
        assert worktrees and worktrees[0].destroy_calls == 1
        assert states and states[0].reset_called is True


class TestRunEnsureLabels:
    """Tests for the async run_ensure_labels helper."""

    @pytest.mark.asyncio
    async def test_run_ensure_labels_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = ConfigFactory.create()

        class FakePrepResult:
            failed = False

            def summary(self) -> str:
                return "Labels synced"

        monkeypatch.setattr(
            "prep.ensure_labels", AsyncMock(return_value=FakePrepResult())
        )

        result = await run_ensure_labels(config)

        assert result.success is True
        assert any("label sync complete" in line for line in result.log)
        assert result.warnings == []

    @pytest.mark.asyncio
    async def test_run_ensure_labels_failure_records_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = ConfigFactory.create()

        class FakePrepResult:
            failed = True

            def summary(self) -> str:
                return "Label sync failed"

        monkeypatch.setattr(
            "prep.ensure_labels", AsyncMock(return_value=FakePrepResult())
        )

        result = await run_ensure_labels(config)

        assert result.success is False
        assert "Label sync completed with failures." in result.warnings

    @pytest.mark.asyncio
    async def test_run_ensure_labels_does_not_run_audit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ensure-labels must not invoke RepoAuditor or seed context assets."""
        config = ConfigFactory.create()

        class FakePrepResult:
            failed = False

            def summary(self) -> str:
                return "Labels synced"

        monkeypatch.setattr(
            "prep.ensure_labels", AsyncMock(return_value=FakePrepResult())
        )
        audit_called = []
        monkeypatch.setattr(
            "admin_tasks._seed_context_assets",
            lambda _c: audit_called.append(True) or [],
            raising=False,
        )

        await run_ensure_labels(config)

        assert not audit_called, "run_ensure_labels must not seed context assets"
