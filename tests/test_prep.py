"""Tests for prep.py — HydraFlow lifecycle label preparation and repo audit."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from cli import _run_scaffold, _seed_context_assets
from models import AuditCheckStatus
from prep import HYDRAFLOW_LABELS, PrepResult, _list_existing_labels, ensure_labels
from tests.conftest import SubprocessMockBuilder
from tests.helpers import AuditCheckFactory, AuditResultFactory, ConfigFactory

# ---------------------------------------------------------------------------
# PrepResult.summary()
# ---------------------------------------------------------------------------


class TestPrepResultSummary:
    """Tests for PrepResult.summary() formatting."""

    def test_all_created(self) -> None:
        result = PrepResult(created=["a", "b", "c"], existed=[], failed=[])
        assert result.summary() == "Created 3 labels, 0 already existed"

    def test_all_existed(self) -> None:
        result = PrepResult(created=[], existed=["a", "b"], failed=[])
        assert result.summary() == "Created 0 labels, 2 already existed"

    def test_summary_reports_created_and_existed_counts(self) -> None:
        result = PrepResult(
            created=["a", "b", "c", "d", "e"],
            existed=["f", "g"],
            failed=[],
        )
        assert result.summary() == "Created 5 labels, 2 already existed"

    def test_with_failures(self) -> None:
        result = PrepResult(
            created=["a"],
            existed=["b"],
            failed=["c", "d"],
        )
        assert result.summary() == "Created 1 label, 1 already existed, 2 failed"

    def test_summary_reports_zero_when_no_labels(self) -> None:
        result = PrepResult()
        assert result.summary() == "Created 0 labels, 0 already existed"


# ---------------------------------------------------------------------------
# _list_existing_labels
# ---------------------------------------------------------------------------


class TestListExistingLabels:
    """Tests for _list_existing_labels()."""

    @pytest.mark.asyncio
    async def test_parses_json(self) -> None:
        config = ConfigFactory.create()
        labels_json = json.dumps([{"name": "bug"}, {"name": "hydraflow-plan"}])
        mock = SubprocessMockBuilder().with_stdout(labels_json).build()

        with patch("asyncio.create_subprocess_exec", mock):
            result = await _list_existing_labels(config)

        assert result == {"bug", "hydraflow-plan"}

    @pytest.mark.asyncio
    async def test_empty_repo_returns_empty_label_set(self) -> None:
        config = ConfigFactory.create()
        mock = SubprocessMockBuilder().with_stdout("[]").build()

        with patch("asyncio.create_subprocess_exec", mock):
            result = await _list_existing_labels(config)

        assert result == set()

    @pytest.mark.asyncio
    async def test_error_returns_empty(self) -> None:
        config = ConfigFactory.create()
        mock = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("not found").build()
        )

        with patch("asyncio.create_subprocess_exec", mock):
            result = await _list_existing_labels(config)

        assert result == set()


# ---------------------------------------------------------------------------
# ensure_labels
# ---------------------------------------------------------------------------


class TestEnsureLabels:
    """Tests for ensure_labels()."""

    @pytest.mark.asyncio
    async def test_creates_all_labels(self) -> None:
        """When no labels exist, all are created."""
        config = ConfigFactory.create()
        # First call: gh label list (returns empty)
        # Subsequent calls: gh label create (returns success)
        call_count = 0

        async def side_effect(*args, **_kwargs):
            nonlocal call_count
            call_count += 1
            proc = AsyncMock()
            proc.returncode = 0
            proc.wait = AsyncMock(return_value=0)
            # First call is label list
            if args[1] == "label" and args[2] == "list":
                proc.communicate = AsyncMock(return_value=(b"[]", b""))
            else:
                proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            result = await ensure_labels(config)

        # All labels should be created (none existed)
        assert len(result.created) == len(HYDRAFLOW_LABELS)
        assert len(result.existed) == 0
        assert len(result.failed) == 0

    @pytest.mark.asyncio
    async def test_reports_already_existing_labels_in_existed_list(self) -> None:
        """Labels already in the repo are classified as 'existed'."""
        config = ConfigFactory.create()
        # Use actual label names from config (ConfigFactory uses "test-label"
        # for ready_label, not "hydraflow-ready")
        existing = (
            list(config.find_label)
            + list(config.planner_label)
            + list(config.ready_label)
        )
        existing_json = json.dumps([{"name": n} for n in existing])

        async def side_effect(*args, **_kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            proc.wait = AsyncMock(return_value=0)
            if args[1] == "label" and args[2] == "list":
                proc.communicate = AsyncMock(return_value=(existing_json.encode(), b""))
            else:
                proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            result = await ensure_labels(config)

        assert set(result.existed) == set(existing)
        assert len(result.created) + len(result.existed) == len(HYDRAFLOW_LABELS)
        assert len(result.failed) == 0

    @pytest.mark.asyncio
    async def test_uses_config_label_names(self) -> None:
        """Custom label names from config are used for creation."""
        config = ConfigFactory.create(
            find_label=["my-find"],
            planner_label=["my-plan"],
            ready_label=["my-ready"],
        )

        created_labels: list[str] = []

        async def side_effect(*args, **_kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            proc.wait = AsyncMock(return_value=0)
            if args[1] == "label" and args[2] == "list":
                proc.communicate = AsyncMock(return_value=(b"[]", b""))
            else:
                # Capture the label name (arg after "create")
                arg_list = list(args)
                create_idx = arg_list.index("create")
                created_labels.append(arg_list[create_idx + 1])
                proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            result = await ensure_labels(config)

        assert "my-find" in created_labels
        assert "my-plan" in created_labels
        assert "my-ready" in created_labels
        assert "my-find" in result.created

    @pytest.mark.asyncio
    async def test_dry_run_skips_creation(self) -> None:
        """In dry-run mode, no gh commands should be called."""
        config = ConfigFactory.create(dry_run=True)
        mock = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock):
            result = await ensure_labels(config)

        # No subprocess calls at all
        mock.assert_not_called()
        # But result should list what would be created
        assert len(result.created) == len(HYDRAFLOW_LABELS)
        assert len(result.existed) == 0

    @pytest.mark.asyncio
    async def test_handles_individual_failures(self) -> None:
        """One label failure doesn't prevent others from being created."""
        config = ConfigFactory.create()
        fail_label = "hydraflow-find"

        async def side_effect(*args, **_kwargs):
            proc = AsyncMock()
            proc.wait = AsyncMock(return_value=0)
            if args[1] == "label" and args[2] == "list":
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"[]", b""))
            elif args[1] == "label" and args[2] == "create":
                label_name = args[3]
                if label_name == fail_label:
                    proc.returncode = 1
                    proc.communicate = AsyncMock(
                        return_value=(b"", b"error creating label")
                    )
                    proc.wait = AsyncMock(return_value=1)
                else:
                    proc.returncode = 0
                    proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            result = await ensure_labels(config)

        assert fail_label in result.failed
        assert len(result.created) == len(HYDRAFLOW_LABELS) - 1
        assert len(result.failed) == 1

    @pytest.mark.asyncio
    async def test_handles_list_failure(self) -> None:
        """If gh label list fails, all labels are treated as new."""
        config = ConfigFactory.create()

        async def side_effect(*args, **_kwargs):
            proc = AsyncMock()
            proc.wait = AsyncMock(return_value=0)
            if args[1] == "label" and args[2] == "list":
                proc.returncode = 1
                proc.communicate = AsyncMock(return_value=(b"", b"not found"))
                proc.wait = AsyncMock(return_value=1)
            else:
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            result = await ensure_labels(config)

        # All should be "created" since list failed (empty existing set)
        assert len(result.created) == len(HYDRAFLOW_LABELS)
        assert len(result.existed) == 0

    @pytest.mark.asyncio
    async def test_all_already_exist(self) -> None:
        """All labels already present are classified as 'existed'."""
        config = ConfigFactory.create()
        # Build the list of all default label names
        all_names = []
        for cfg_field, _, _ in HYDRAFLOW_LABELS:
            all_names.extend(getattr(config, cfg_field))
        existing_json = json.dumps([{"name": n} for n in all_names])

        async def side_effect(*args, **_kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            proc.wait = AsyncMock(return_value=0)
            if args[1] == "label" and args[2] == "list":
                proc.communicate = AsyncMock(return_value=(existing_json.encode(), b""))
            else:
                proc.communicate = AsyncMock(return_value=(b"", b""))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=side_effect):
            result = await ensure_labels(config)

        assert len(result.created) == 0
        assert len(result.existed) == len(HYDRAFLOW_LABELS)
        assert len(result.failed) == 0


# ---------------------------------------------------------------------------
# AuditResult model tests
# ---------------------------------------------------------------------------


class TestAuditResult:
    """Tests for the AuditResult model and its format_report method."""

    def test_missing_checks_returns_missing_and_partial(self) -> None:
        """Should include both MISSING and PARTIAL checks."""
        result = AuditResultFactory.create(
            checks=[
                AuditCheckFactory.create(name="A", status="present"),
                AuditCheckFactory.create(name="B", status="missing"),
                AuditCheckFactory.create(name="C", status="partial"),
            ]
        )
        names = [c.name for c in result.missing_checks]
        assert names == ["B", "C"]

    def test_missing_checks_empty_when_all_present(self) -> None:
        """Should return empty list when all checks pass."""
        result = AuditResultFactory.create(
            checks=[
                AuditCheckFactory.create(name="A", status="present"),
                AuditCheckFactory.create(name="B", status="present"),
            ]
        )
        assert result.missing_checks == []

    def test_has_critical_gaps_true(self) -> None:
        """Should return True when a critical check is MISSING."""
        result = AuditResultFactory.create(
            checks=[
                AuditCheckFactory.create(name="CI", status="missing", critical=True),
                AuditCheckFactory.create(name="Linting", status="present"),
            ]
        )
        assert result.has_critical_gaps is True

    def test_has_critical_gaps_false_when_critical_present(self) -> None:
        """Should return False when all critical checks pass."""
        result = AuditResultFactory.create(
            checks=[
                AuditCheckFactory.create(name="CI", status="present", critical=True),
                AuditCheckFactory.create(name="Linting", status="missing"),
            ]
        )
        assert result.has_critical_gaps is False

    def test_has_critical_gaps_false_when_critical_partial(self) -> None:
        """Should return False when critical check is PARTIAL (not MISSING)."""
        result = AuditResultFactory.create(
            checks=[
                AuditCheckFactory.create(
                    name="Makefile", status="partial", critical=True
                ),
            ]
        )
        assert result.has_critical_gaps is False

    def test_format_report_all_passing(self) -> None:
        """Should show checkmarks and 'No gaps found' message."""
        result = AuditResultFactory.create(
            repo="owner/repo",
            checks=[
                AuditCheckFactory.create(
                    name="Language", status="present", detail="Python 3.11"
                ),
                AuditCheckFactory.create(
                    name="Makefile", status="present", detail="all targets"
                ),
            ],
        )
        report = result.format_report()
        assert "owner/repo" in report
        assert "\u2713" in report
        assert "No gaps found" in report

    def test_format_report_with_gaps(self) -> None:
        """Should show X markers and missing count."""
        result = AuditResultFactory.create(
            repo="owner/repo",
            checks=[
                AuditCheckFactory.create(name="CI", status="missing", critical=True),
                AuditCheckFactory.create(name="Linting", status="present"),
                AuditCheckFactory.create(name="Git hooks", status="missing"),
            ],
        )
        report = result.format_report()
        assert "\u2717" in report
        assert "Missing (2)" in report
        assert "CI" in report
        assert "Git hooks" in report
        assert "hydraflow prep" in report


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


class TestCheckLanguage:
    """Tests for RepoAuditor._check_language."""

    def test_python_repo_with_pyproject_toml(self, tmp_path: Path) -> None:
        """Should detect Python with version from pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nrequires-python = ">=3.11"\n'
        )
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_language()
        assert check.status == AuditCheckStatus.PRESENT
        assert "Python" in check.detail
        assert "3.11" in check.detail

    def test_python_with_setup_py(self, tmp_path: Path) -> None:
        """Should detect Python via setup.py fallback."""
        (tmp_path / "setup.py").write_text("from setuptools import setup\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_language()
        assert check.status == AuditCheckStatus.PRESENT
        assert "Python" in check.detail

    def test_python_with_requirements_txt(self, tmp_path: Path) -> None:
        """Should detect Python via requirements.txt fallback."""
        (tmp_path / "requirements.txt").write_text("requests\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_language()
        assert check.status == AuditCheckStatus.PRESENT
        assert "Python" in check.detail

    def test_js_repo_with_package_json(self, tmp_path: Path) -> None:
        """Should detect JS/TS via package.json."""
        (tmp_path / "package.json").write_text('{"name": "test"}\n')
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_language()
        assert check.status == AuditCheckStatus.PRESENT
        assert "JS/TS" in check.detail

    def test_mixed_repo(self, tmp_path: Path) -> None:
        """Should detect both Python and JS/TS."""
        (tmp_path / "pyproject.toml").write_text("[project]\n")
        (tmp_path / "package.json").write_text('{"name": "test"}\n')
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_language()
        assert check.status == AuditCheckStatus.PRESENT
        assert "Python" in check.detail
        assert "JS/TS" in check.detail

    def test_no_language_markers(self, tmp_path: Path) -> None:
        """Should report MISSING when no language markers found."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_language()
        assert check.status == AuditCheckStatus.MISSING


# ---------------------------------------------------------------------------
# Makefile detection
# ---------------------------------------------------------------------------


class TestCheckMakefile:
    """Tests for RepoAuditor._check_makefile."""

    def test_makefile_with_all_targets(self, tmp_path: Path) -> None:
        """Should report PRESENT when all required targets exist."""
        (tmp_path / "Makefile").write_text(
            "lint:\n\t@echo lint\n\n"
            "lint-check:\n\t@echo lint-check\n\n"
            "lint-fix:\n\t@echo lint-fix\n\n"
            "typecheck:\n\t@echo typecheck\n\n"
            "security:\n\t@echo security\n\n"
            "test:\n\t@echo test\n\n"
            "coverage-check:\n\t@echo coverage\n\n"
            "quality-lite:\n\t@echo quality-lite\n\n"
            "quality:\n\t@echo quality\n"
        )
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_makefile()
        assert check.status == AuditCheckStatus.PRESENT
        assert check.critical is True

    def test_makefile_missing_quality_target(self, tmp_path: Path) -> None:
        """Should report PARTIAL when some targets are missing."""
        (tmp_path / "Makefile").write_text(
            "lint:\n\t@echo lint\n\ntest:\n\t@echo test\n"
        )
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_makefile()
        assert check.status == AuditCheckStatus.PARTIAL
        assert "quality" in check.detail

    def test_no_makefile(self, tmp_path: Path) -> None:
        """Should report MISSING when no Makefile exists."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_makefile()
        assert check.status == AuditCheckStatus.MISSING

    def test_makefile_with_dependencies_on_targets(self, tmp_path: Path) -> None:
        """Should detect targets that have dependencies."""
        (tmp_path / "Makefile").write_text(
            "lint:\n\t@echo lint\n\n"
            "lint-check:\n\t@echo lint-check\n\n"
            "lint-fix: lint\n\t@echo lint-fix\n\n"
            "typecheck:\n\t@echo typecheck\n\n"
            "security:\n\t@echo security\n\n"
            "test:\n\t@echo test\n\n"
            "coverage-check:\n\t@echo coverage\n\n"
            "quality-lite: lint-check typecheck security\n\t@echo quality-lite\n\n"
            "quality: quality-lite test coverage-check\n\t@echo quality\n"
        )
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_makefile()
        assert check.status == AuditCheckStatus.PRESENT


# ---------------------------------------------------------------------------
# CI detection
# ---------------------------------------------------------------------------


class TestCheckCI:
    """Tests for RepoAuditor._check_ci."""

    def test_workflow_with_push_trigger(self, tmp_path: Path) -> None:
        """Should report PRESENT when a workflow triggers on push."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("on:\n  push:\n    branches: [main]\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_ci()
        assert check.status == AuditCheckStatus.PRESENT
        assert check.critical is True

    def test_workflow_with_pull_request_trigger(self, tmp_path: Path) -> None:
        """Should report PRESENT when a workflow triggers on pull_request."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yaml").write_text("on:\n  pull_request:\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_ci()
        assert check.status == AuditCheckStatus.PRESENT

    def test_workflow_without_push_trigger(self, tmp_path: Path) -> None:
        """Should report PARTIAL when workflows exist but none trigger on push/PR."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "release.yml").write_text("on:\n  workflow_dispatch:\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_ci()
        assert check.status == AuditCheckStatus.PARTIAL

    def test_workflow_with_push_in_step_name_not_falsely_detected(
        self, tmp_path: Path
    ) -> None:
        """Should not falsely detect 'push' appearing only in step names or run commands."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "deploy.yml").write_text(
            "on:\n  workflow_dispatch:\nsteps:\n  - name: Push Docker image\n    run: docker push myimage\n"
        )
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_ci()
        assert check.status == AuditCheckStatus.PARTIAL

    def test_no_workflows_dir(self, tmp_path: Path) -> None:
        """Should report MISSING when .github/workflows/ doesn't exist."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_ci()
        assert check.status == AuditCheckStatus.MISSING

    def test_workflow_dir_empty(self, tmp_path: Path) -> None:
        """Should report MISSING when workflows dir is empty."""
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_ci()
        assert check.status == AuditCheckStatus.MISSING


# ---------------------------------------------------------------------------
# Git hooks detection
# ---------------------------------------------------------------------------


class TestCheckGitHooks:
    """Tests for RepoAuditor._check_git_hooks."""

    def test_githooks_dir_with_precommit(self, tmp_path: Path) -> None:
        """Should report PRESENT when .githooks/pre-commit exists."""
        hooks_dir = tmp_path / ".githooks"
        hooks_dir.mkdir()
        (hooks_dir / "pre-commit").write_text("#!/bin/sh\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_git_hooks()
        assert check.status == AuditCheckStatus.PRESENT

    def test_husky_dir_with_precommit(self, tmp_path: Path) -> None:
        """Should report PRESENT when .husky/pre-commit exists."""
        hooks_dir = tmp_path / ".husky"
        hooks_dir.mkdir()
        (hooks_dir / "pre-commit").write_text("#!/bin/sh\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_git_hooks()
        assert check.status == AuditCheckStatus.PRESENT

    def test_no_hooks_dir(self, tmp_path: Path) -> None:
        """Should report MISSING when no hooks directories exist."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_git_hooks()
        assert check.status == AuditCheckStatus.MISSING

    def test_git_hooks_precommit_file(self, tmp_path: Path) -> None:
        """Should report PRESENT when .git/hooks/pre-commit exists."""
        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "pre-commit").write_text("#!/bin/sh\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_git_hooks()
        assert check.status == AuditCheckStatus.PRESENT
        assert ".git/hooks/pre-commit" in check.detail


# ---------------------------------------------------------------------------
# Linting detection
# ---------------------------------------------------------------------------


class TestCheckLinting:
    """Tests for RepoAuditor._check_linting."""

    def test_ruff_toml(self, tmp_path: Path) -> None:
        """Should detect standalone ruff.toml."""
        (tmp_path / "ruff.toml").write_text("[lint]\nselect = ['E']\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_linting()
        assert check.status == AuditCheckStatus.PRESENT
        assert "ruff" in check.detail

    def test_ruff_in_pyproject_toml(self, tmp_path: Path) -> None:
        """Should detect [tool.ruff] in pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_linting()
        assert check.status == AuditCheckStatus.PRESENT
        assert "ruff" in check.detail

    def test_check_linting_detects_eslintrc_file(self, tmp_path: Path) -> None:
        """Should detect .eslintrc.json."""
        (tmp_path / ".eslintrc.json").write_text("{}\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_linting()
        assert check.status == AuditCheckStatus.PRESENT
        assert "eslint" in check.detail

    def test_check_linting_detects_flat_eslint_config(self, tmp_path: Path) -> None:
        """Should detect eslint.config.js."""
        (tmp_path / "eslint.config.js").write_text("export default [];\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_linting()
        assert check.status == AuditCheckStatus.PRESENT
        assert "eslint" in check.detail

    def test_biome_json(self, tmp_path: Path) -> None:
        """Should detect biome.json."""
        (tmp_path / "biome.json").write_text("{}\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_linting()
        assert check.status == AuditCheckStatus.PRESENT
        assert "biome" in check.detail

    def test_check_linting_detects_make_lint_target(self, tmp_path: Path) -> None:
        """Should detect Makefile lint target as linting capability."""
        (tmp_path / "Makefile").write_text("lint-check:\n\t@echo ok\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_linting()
        assert check.status == AuditCheckStatus.PRESENT
        assert "make lint target" in check.detail

    def test_check_linting_detects_package_json_lint_script(
        self, tmp_path: Path
    ) -> None:
        """Should detect package.json lint script as linting capability."""
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"lint": "eslint ."}})
        )
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_linting()
        assert check.status == AuditCheckStatus.PRESENT
        assert "npm lint script" in check.detail

    def test_no_linting_config(self, tmp_path: Path) -> None:
        """Should report MISSING when no linting config found."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_linting()
        assert check.status == AuditCheckStatus.MISSING


# ---------------------------------------------------------------------------
# Type checking detection
# ---------------------------------------------------------------------------


class TestCheckTypeChecking:
    """Tests for RepoAuditor._check_type_checking."""

    def test_pyrightconfig_json(self, tmp_path: Path) -> None:
        """Should detect pyrightconfig.json."""
        (tmp_path / "pyrightconfig.json").write_text("{}\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_type_checking()
        assert check.status == AuditCheckStatus.PRESENT
        assert "pyright" in check.detail

    def test_pyright_in_pyproject_toml(self, tmp_path: Path) -> None:
        """Should detect [tool.pyright] in pyproject.toml."""
        (tmp_path / "pyproject.toml").write_text("[tool.pyright]\nvenvPath = '.'\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_type_checking()
        assert check.status == AuditCheckStatus.PRESENT
        assert "pyright" in check.detail

    def test_tsconfig_json(self, tmp_path: Path) -> None:
        """Should detect tsconfig.json."""
        (tmp_path / "tsconfig.json").write_text("{}\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_type_checking()
        assert check.status == AuditCheckStatus.PRESENT
        assert "tsconfig" in check.detail

    def test_no_type_checking_config(self, tmp_path: Path) -> None:
        """Should report MISSING when no type checking config found."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_type_checking()
        assert check.status == AuditCheckStatus.MISSING


# ---------------------------------------------------------------------------
# Test framework detection
# ---------------------------------------------------------------------------


class TestCheckTestFramework:
    """Tests for RepoAuditor._check_test_framework."""

    def test_pytest_with_tests_dir(self, tmp_path: Path) -> None:
        """Should detect pytest with tests/ dir and count test files."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.py").write_text("def test_x(): pass\n")
        (tests_dir / "test_bar.py").write_text("def test_y(): pass\n")
        (tests_dir / "conftest.py").write_text("import pytest\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_test_framework()
        assert check.status == AuditCheckStatus.PRESENT
        assert "pytest" in check.detail
        assert "2" in check.detail  # 2 test files

    def test_jest_with_tests_dir(self, tmp_path: Path) -> None:
        """Should detect jest-style __tests__/ directory."""
        tests_dir = tmp_path / "__tests__"
        tests_dir.mkdir()
        (tests_dir / "foo.test.js").write_text("test('x', () => {})\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_test_framework()
        assert check.status == AuditCheckStatus.PRESENT

    def test_vitest_config(self, tmp_path: Path) -> None:
        """Should detect vitest.config.ts."""
        (tmp_path / "vitest.config.ts").write_text("export default {}\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_test_framework()
        assert check.status == AuditCheckStatus.PRESENT
        assert "vitest" in check.detail

    def test_jest_config_file(self, tmp_path: Path) -> None:
        """Should detect jest from jest.config.ts without requiring __tests__/ dir."""
        (tmp_path / "jest.config.ts").write_text("export default {}\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_test_framework()
        assert check.status == AuditCheckStatus.PRESENT
        assert "jest" in check.detail

    def test_no_test_framework(self, tmp_path: Path) -> None:
        """Should report MISSING when no test framework detected."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_test_framework()
        assert check.status == AuditCheckStatus.MISSING


# ---------------------------------------------------------------------------
# Coverage policy detection
# ---------------------------------------------------------------------------


class TestCheckCoveragePolicy:
    """Tests for RepoAuditor._check_coverage_policy."""

    def test_missing_threshold_reports_partial(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_coverage_policy()
        assert check.status == AuditCheckStatus.PARTIAL
        assert "no enforced coverage threshold" in check.detail

    def test_threshold_below_minimum_reports_partial(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text("COVERAGE_MIN ?= 35\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_coverage_policy()
        assert check.status == AuditCheckStatus.PARTIAL
        assert "below minimum 70%" in check.detail

    def test_threshold_between_minimum_and_target_warns(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text(
            "COVERAGE_MIN ?= 60\nCOVERAGE_TARGET ?= 70\n"
        )
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_coverage_policy()
        assert check.status == AuditCheckStatus.PARTIAL
        assert "below minimum 70%" in check.detail

    def test_threshold_at_target_reports_present(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text(
            "COVERAGE_MIN ?= 70\nCOVERAGE_TARGET ?= 70\n"
        )
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_coverage_policy()
        assert check.status == AuditCheckStatus.PRESENT
        assert "70%" in check.detail


# ---------------------------------------------------------------------------
# Package manager detection
# ---------------------------------------------------------------------------


class TestCheckPackageManager:
    """Tests for RepoAuditor._check_package_manager."""

    def test_uv_lock(self, tmp_path: Path) -> None:
        """Should detect uv.lock."""
        (tmp_path / "uv.lock").write_text("[[package]]\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_package_manager()
        assert check.status == AuditCheckStatus.PRESENT
        assert "uv" in check.detail

    def test_pnpm_lock(self, tmp_path: Path) -> None:
        """Should detect pnpm-lock.yaml."""
        (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 6\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_package_manager()
        assert check.status == AuditCheckStatus.PRESENT
        assert "pnpm" in check.detail

    def test_package_lock_json(self, tmp_path: Path) -> None:
        """Should detect package-lock.json."""
        (tmp_path / "package-lock.json").write_text("{}\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_package_manager()
        assert check.status == AuditCheckStatus.PRESENT
        assert "npm" in check.detail

    def test_yarn_lock(self, tmp_path: Path) -> None:
        """Should detect yarn.lock."""
        (tmp_path / "yarn.lock").write_text("# yarn lockfile v1\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_package_manager()
        assert check.status == AuditCheckStatus.PRESENT
        assert "yarn" in check.detail

    def test_poetry_lock(self, tmp_path: Path) -> None:
        """Should detect poetry.lock."""
        (tmp_path / "poetry.lock").write_text("[[package]]\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_package_manager()
        assert check.status == AuditCheckStatus.PRESENT
        assert "poetry" in check.detail

    def test_no_lock_file(self, tmp_path: Path) -> None:
        """Should report MISSING when no lock file found."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_package_manager()
        assert check.status == AuditCheckStatus.MISSING


# ---------------------------------------------------------------------------
# GH CLI detection
# ---------------------------------------------------------------------------


class TestCheckGhCli:
    """Tests for RepoAuditor._check_gh_cli."""

    @pytest.mark.asyncio
    async def test_authenticated_with_push_access(self, tmp_path: Path) -> None:
        """Should report PRESENT when gh is authed with push access."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)

        with patch("prep.run_subprocess", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = [
                "github.com\n  Logged in",  # gh auth status
                "WRITE",  # gh repo view
            ]
            check = await auditor._check_gh_cli()

        assert check.status == AuditCheckStatus.PRESENT
        assert "authenticated" in check.detail
        assert "push access" in check.detail

    @pytest.mark.asyncio
    async def test_authenticated_with_admin_access(self, tmp_path: Path) -> None:
        """Should report PRESENT for ADMIN permission."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)

        with patch("prep.run_subprocess", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = [
                "Logged in",  # gh auth status
                "ADMIN",  # gh repo view
            ]
            check = await auditor._check_gh_cli()

        assert check.status == AuditCheckStatus.PRESENT

    @pytest.mark.asyncio
    async def test_not_authenticated(self, tmp_path: Path) -> None:
        """Should report MISSING when gh auth fails."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)

        with patch("prep.run_subprocess", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = RuntimeError("not logged in")
            check = await auditor._check_gh_cli()

        assert check.status == AuditCheckStatus.MISSING
        assert check.critical is True

    @pytest.mark.asyncio
    async def test_read_only_access(self, tmp_path: Path) -> None:
        """Should report PARTIAL when access is read-only."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)

        with patch("prep.run_subprocess", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = [
                "Logged in",  # gh auth status
                "READ",  # gh repo view
            ]
            check = await auditor._check_gh_cli()

        assert check.status == AuditCheckStatus.PARTIAL
        assert "read-only" in check.detail


# ---------------------------------------------------------------------------
# Label detection
# ---------------------------------------------------------------------------


class TestCheckLabels:
    """Tests for RepoAuditor._check_labels."""

    @pytest.mark.asyncio
    async def test_all_labels_present(self, tmp_path: Path) -> None:
        """Should report PRESENT when all HydraFlow labels exist."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        # Build the full label list from config
        all_labels = auditor._get_hydra_labels()

        with patch("prep.run_subprocess", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "\n".join(all_labels)
            check = await auditor._check_labels()

        assert check.status == AuditCheckStatus.PRESENT

    @pytest.mark.asyncio
    async def test_partial_labels_returns_partial_status(self, tmp_path: Path) -> None:
        """Should report PARTIAL when some labels are missing."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        all_labels = auditor._get_hydra_labels()

        with patch("prep.run_subprocess", new_callable=AsyncMock) as mock_run:
            # Return only first half of labels
            mock_run.return_value = "\n".join(all_labels[: len(all_labels) // 2])
            check = await auditor._check_labels()

        assert check.status == AuditCheckStatus.PARTIAL

    @pytest.mark.asyncio
    async def test_no_labels_returns_missing_status(self, tmp_path: Path) -> None:
        """Should report MISSING when no HydraFlow labels exist."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)

        with patch("prep.run_subprocess", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "bug\nenhancement\ndocumentation"
            check = await auditor._check_labels()

        assert check.status == AuditCheckStatus.MISSING

    @pytest.mark.asyncio
    async def test_label_check_handles_gh_error(self, tmp_path: Path) -> None:
        """Should report MISSING when gh label list fails."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)

        with patch("prep.run_subprocess", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = RuntimeError("gh failed")
            check = await auditor._check_labels()

        assert check.status == AuditCheckStatus.MISSING


# ---------------------------------------------------------------------------
# Full audit run
# ---------------------------------------------------------------------------


class TestRunAudit:
    """Tests for the full audit workflow."""

    @pytest.mark.asyncio
    async def test_run_audit_produces_all_checks(self, tmp_path: Path) -> None:
        """Should produce checks for all categories."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)

        with patch("prep.run_subprocess", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = RuntimeError("not available")
            result = await auditor.run_audit()

        check_names = [c.name for c in result.checks]
        assert "Language" in check_names
        assert "Makefile" in check_names
        assert "CI" in check_names
        assert "Git hooks" in check_names
        assert "Linting" in check_names
        assert "Type check" in check_names
        assert "Tests" in check_names
        assert "Coverage" in check_names
        assert "Pkg manager" in check_names
        assert "gh CLI" in check_names
        assert "Labels" in check_names


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCliPrep:
    """Tests for the --prep CLI flag integration."""

    def test_prep_flag_parsed(self) -> None:
        """Should parse --prep flag."""
        from cli import parse_args

        args = parse_args(["--prep"])
        assert args.prep is True

    def test_prep_flag_default_false(self) -> None:
        """Should default to False."""
        from cli import parse_args

        args = parse_args([])
        assert args.prep is False

    def test_main_prep_exits_zero_on_success(self) -> None:
        """main() should exit 0 when scaffold run succeeds."""
        from cli import main

        with (
            patch(
                "cli._run_scaffold", new_callable=AsyncMock, return_value=True
            ) as mock_run,
            pytest.raises(SystemExit) as exc_info,
        ):
            main(["--prep"])

        mock_run.assert_called_once()
        assert exc_info.value.code == 0

    def test_main_prep_exits_one_on_failure(self) -> None:
        """main() should exit 1 when scaffold run fails."""
        from cli import main

        with (
            patch("cli._run_scaffold", new_callable=AsyncMock, return_value=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            main(["--prep"])

        assert exc_info.value.code == 1


class TestCliAudit:
    """Tests for the --audit CLI flag."""

    def test_audit_flag_parsed(self) -> None:
        """Should parse --audit flag."""
        from cli import parse_args

        args = parse_args(["--audit"])
        assert args.audit is True

    def test_audit_flag_default_false(self) -> None:
        """Should default to False."""
        from cli import parse_args

        args = parse_args([])
        assert args.audit is False


class TestCliScaffold:
    """Tests for the --scaffold CLI flag."""

    def test_scaffold_flag_parsed(self) -> None:
        """Should parse --scaffold flag."""
        from cli import parse_args

        args = parse_args(["--scaffold"])
        assert args.scaffold is True

    def test_scaffold_flag_default_false(self) -> None:
        """Should default to False."""
        from cli import parse_args

        args = parse_args([])
        assert args.scaffold is False

    def test_main_scaffold_exits_zero_on_success(self) -> None:
        """main() should exit 0 when scaffold alias run succeeds."""
        from cli import main

        with (
            patch(
                "cli._run_scaffold", new_callable=AsyncMock, return_value=True
            ) as mock_run,
            pytest.raises(SystemExit) as exc_info,
        ):
            main(["--scaffold"])

        mock_run.assert_called_once()
        assert exc_info.value.code == 0

    def test_main_scaffold_exits_one_on_failure(self) -> None:
        """main() should exit 1 when scaffold alias run fails."""
        from cli import main

        with (
            patch("cli._run_scaffold", new_callable=AsyncMock, return_value=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            main(["--scaffold"])

        assert exc_info.value.code == 1


class TestCliEnsureLabels:
    """Tests for the --ensure-labels CLI flag integration."""

    def test_ensure_labels_flag_parsed(self) -> None:
        from cli import parse_args

        args = parse_args(["--ensure-labels"])
        assert args.ensure_labels is True

    def test_main_ensure_labels_exits_zero_on_success(self) -> None:
        from cli import main

        with (
            patch(
                "cli._run_prep", new_callable=AsyncMock, return_value=True
            ) as mock_run,
            pytest.raises(SystemExit) as exc_info,
        ):
            main(["--ensure-labels"])

        mock_run.assert_called_once()
        assert exc_info.value.code == 0


def test_run_scaffold_focuses_on_ci_and_test_scaffolds() -> None:
    """_run_scaffold should only scaffold CI + tests for quick prep."""
    from pathlib import Path

    cli_file = Path(__file__).resolve().parent.parent / "src" / "cli.py"
    content = cli_file.read_text()
    assert "scaffold_ci(" in content
    assert "scaffold_tests_polyglot(" in content
    assert "scaffold_makefiles(" not in content


def test_run_scaffold_prints_summary_block() -> None:
    """_run_scaffold should print a final prep summary section."""
    from pathlib import Path

    cli_file = Path(__file__).resolve().parent.parent / "src" / "cli.py"
    content = cli_file.read_text()
    assert "Prep summary:" in content


def test_run_scaffold_has_quick_success_and_coverage_guidance() -> None:
    """_run_scaffold should support early success and coverage follow-up guidance."""
    from pathlib import Path

    cli_file = Path(__file__).resolve().parent.parent / "src" / "cli.py"
    content = cli_file.read_text()
    assert "Well done: CI and baseline tests already exist" in content
    assert "make cover" in content
    assert "make smoke" in content


def test_run_scaffold_coverage_guidance_uses_scaffold_stage_label() -> None:
    """Coverage and cover/smoke guidance should emit scaffold stage labels."""
    from pathlib import Path

    cli_file = Path(__file__).resolve().parent.parent / "src" / "cli.py"
    content = cli_file.read_text()
    assert "_prep_stage_line(" in content
    assert '"scaffold"' in content
    assert "Next: run `make cover` (70% unit coverage) and `make smoke`." in content
    assert (
        "Coverage: {coverage_pct:.1f}% from {coverage_source} (below 70%)." in content
    )


def test_run_scaffold_messages_do_not_use_hardening_term() -> None:
    """Scaffold path messaging should use prep/scaffold wording, not hardening."""
    from pathlib import Path

    cli_file = Path(__file__).resolve().parent.parent / "src" / "cli.py"
    content = cli_file.read_text()
    start = content.index("async def _run_scaffold")
    end = content.index("async def _run_clean")
    scaffold_body = content[start:end].lower()
    assert "hardening" not in scaffold_body


@pytest.mark.asyncio
async def test_run_scaffold_reports_prompt_selection_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Interactive selection mode should be reflected in prep stage output."""
    config = ConfigFactory.create(repo_root=tmp_path, dry_run=True)

    monkeypatch.setattr("cli._choose_prep_tool", lambda _configured: ("pi", "prompt"))
    monkeypatch.setattr("polyglot_prep.detect_prep_stack", lambda _repo_root: "python")
    monkeypatch.setattr(
        "ci_scaffold.scaffold_ci",
        lambda _repo_root, dry_run=False: SimpleNamespace(skipped=True),
    )
    monkeypatch.setattr(
        "polyglot_prep.scaffold_tests_polyglot",
        lambda _repo_root, dry_run=False: SimpleNamespace(skipped=True),
    )
    monkeypatch.setattr(
        "cli._extract_coverage_percent", lambda _repo_root: (75.0, "coverage.xml")
    )

    ok = await _run_scaffold(config)
    out = capsys.readouterr().out
    assert ok is True
    assert "prep driver selected: pi" in out
    assert "mode=prompt" in out


@pytest.mark.asyncio
async def test_run_scaffold_warns_when_no_prep_driver_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No detected prep tools should surface a clear warning."""
    config = ConfigFactory.create(repo_root=tmp_path, dry_run=True)

    monkeypatch.setattr("cli._choose_prep_tool", lambda _configured: (None, "none"))
    monkeypatch.setattr("polyglot_prep.detect_prep_stack", lambda _repo_root: "python")
    monkeypatch.setattr(
        "ci_scaffold.scaffold_ci",
        lambda _repo_root, dry_run=False: SimpleNamespace(skipped=True),
    )
    monkeypatch.setattr(
        "polyglot_prep.scaffold_tests_polyglot",
        lambda _repo_root, dry_run=False: SimpleNamespace(skipped=True),
    )
    monkeypatch.setattr(
        "cli._extract_coverage_percent", lambda _repo_root: (75.0, "coverage.xml")
    )

    ok = await _run_scaffold(config)
    out = capsys.readouterr().out
    assert ok is True
    assert "no prep driver detected" in out


class TestContextSeed:
    """Tests for seeding local manifest/memory assets during prep."""

    def test_seed_creates_manifest_digest_and_metrics_cache(
        self, tmp_path: Path
    ) -> None:
        state_file = tmp_path / ".hydraflow" / "state.json"
        config = ConfigFactory.create(repo_root=tmp_path, state_file=state_file)

        log_lines = _seed_context_assets(config)

        manifest_path = tmp_path / ".hydraflow" / "manifest" / "manifest.md"
        digest_path = tmp_path / ".hydraflow" / "memory" / "digest.md"
        repo_slug = config.repo.replace("/", "-") if config.repo else "unknown"
        metrics_file = state_file.parent / "metrics" / repo_slug / "snapshots.jsonl"

        assert manifest_path.is_file()
        assert digest_path.is_file()
        assert metrics_file.is_file()
        assert any("Manifest seed" in line for line in log_lines)
        assert "Seeded during prep" in digest_path.read_text()

    def test_seed_skipped_in_dry_run(self, tmp_path: Path) -> None:
        state_file = tmp_path / ".hydraflow" / "state.json"
        config = ConfigFactory.create(
            repo_root=tmp_path, dry_run=True, state_file=state_file
        )

        log_lines = _seed_context_assets(config)

        assert not (tmp_path / ".hydraflow").exists()
        assert "- Context seed skipped" in log_lines[0]

    def test_seed_does_not_overwrite_existing_files(self, tmp_path: Path) -> None:
        state_file = tmp_path / ".hydraflow" / "state.json"
        config = ConfigFactory.create(repo_root=tmp_path, state_file=state_file)
        _seed_context_assets(config)

        digest_path = tmp_path / ".hydraflow" / "memory" / "digest.md"
        metrics_file = (
            state_file.parent
            / "metrics"
            / config.repo.replace("/", "-")
            / "snapshots.jsonl"
        )
        digest_path.write_text("custom digest")
        metrics_file.write_text("existing metrics line\n")

        _seed_context_assets(config)

        assert digest_path.read_text() == "custom digest"
        assert metrics_file.read_text() == "existing metrics line\n"


# ---------------------------------------------------------------------------
# RepoAuditor._check_agents_md
# ---------------------------------------------------------------------------


class TestCheckAgentsMd:
    """Tests for RepoAuditor._check_agents_md."""

    def test_present_when_agents_md_exists(self, tmp_path: Path) -> None:
        """PRESENT when AGENTS.md is in the repo root."""
        (tmp_path / "AGENTS.md").write_text("# AGENTS\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_agents_md()
        assert check.status == AuditCheckStatus.PRESENT
        assert check.name == "AGENTS.md"

    def test_missing_when_agents_md_absent(self, tmp_path: Path) -> None:
        """MISSING when AGENTS.md is not present."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_agents_md()
        assert check.status == AuditCheckStatus.MISSING
        assert check.name == "AGENTS.md"
        assert "hf init" in check.detail

    def test_missing_is_not_critical(self, tmp_path: Path) -> None:
        """Missing AGENTS.md is a warning, not a blocking error."""
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_agents_md()
        assert not check.critical

    def test_included_in_audit_result(self, tmp_path: Path) -> None:
        """AGENTS.md check appears in the full audit result."""
        (tmp_path / "AGENTS.md").write_text("# AGENTS\n")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_agents_md()
        # Verify the check name matches what run_audit() would include
        assert check.name == "AGENTS.md"
        assert check.status == AuditCheckStatus.PRESENT

    def test_empty_file_is_still_present(self, tmp_path: Path) -> None:
        """An empty AGENTS.md is reported as PRESENT — audit checks existence, not content."""
        (tmp_path / "AGENTS.md").write_text("")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_agents_md()
        assert check.status == AuditCheckStatus.PRESENT

    def test_directory_named_agents_md_is_partial(self, tmp_path: Path) -> None:
        """A directory named AGENTS.md returns PARTIAL, not PRESENT."""
        (tmp_path / "AGENTS.md").mkdir()
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_agents_md()
        assert check.status == AuditCheckStatus.PARTIAL
        assert "directory" in check.detail

    def test_symlink_to_valid_file_is_present(self, tmp_path: Path) -> None:
        """A symlink pointing to a valid AGENTS.md file is reported as PRESENT."""
        target = tmp_path / "AGENTS-template.md"
        target.write_text("# AGENTS\n")
        (tmp_path / "AGENTS.md").symlink_to(target)
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_agents_md()
        assert check.status == AuditCheckStatus.PRESENT

    def test_broken_symlink_is_missing(self, tmp_path: Path) -> None:
        """A symlink pointing to a non-existent file is reported as MISSING."""
        (tmp_path / "AGENTS.md").symlink_to(tmp_path / "nonexistent.md")
        config = ConfigFactory.create(repo_root=tmp_path)
        from prep import RepoAuditor

        auditor = RepoAuditor(config)
        check = auditor._check_agents_md()
        assert check.status == AuditCheckStatus.MISSING
