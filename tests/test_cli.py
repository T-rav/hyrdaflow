"""Tests for cli.py — parse_args, build_config, and signal handling."""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cli import (
    _build_prep_agent_prompt,
    _build_prep_failure_error_message,
    _coverage_validation_roots,
    _evaluate_coverage_validation,
    _evaluate_coverage_validation_projects,
    _extract_coverage_percent,
    _parse_label_arg,
    _parse_prep_result,
    _project_has_test_signal,
    _run_main,
    build_config,
    parse_args,
)

# ---------------------------------------------------------------------------
# _parse_label_arg
# ---------------------------------------------------------------------------


class TestParseLabelArg:
    """Tests for the _parse_label_arg helper."""

    def test_single_label(self) -> None:
        assert _parse_label_arg("hydraflow-ready") == ["hydraflow-ready"]

    def test_comma_separated_labels(self) -> None:
        assert _parse_label_arg("foo,bar") == ["foo", "bar"]

    def test_strips_whitespace(self) -> None:
        assert _parse_label_arg(" foo , bar ") == ["foo", "bar"]

    def test_empty_string_returns_empty_list(self) -> None:
        assert _parse_label_arg("") == []


class TestPrepFailureErrorMessage:
    """Tests for prep failure message classification."""

    def test_classifies_edit_before_read_tool_error(self) -> None:
        transcript = (
            "some output\n"
            "<tool_use_error>File has not been read yet. Read it first before writing to it.</tool_use_error>"
        )
        msg = _build_prep_failure_error_message(
            transcript, ".hydraflow/prep/runs/20260224/a.log"
        )
        assert "tool precondition failure" in msg
        assert "Transcript path: .hydraflow/prep/runs/20260224/a.log" in msg

    def test_classifies_turn_limit_error(self) -> None:
        transcript = "agent stopped due to max turns reached"
        msg = _build_prep_failure_error_message(
            transcript, ".hydraflow/prep/runs/20260224/b.log"
        )
        assert "turn limit" in msg


class TestPrepResultParsing:
    """Tests for structured prep result parsing."""

    def test_prefers_json_success(self) -> None:
        success, mode = _parse_prep_result(
            '... PREP_RESULT_JSON: {"prep_status":"SUCCESS","summary":"ok"}'
        )
        assert success is True
        assert mode == "json"

    def test_json_failed_returns_false(self) -> None:
        success, mode = _parse_prep_result(
            '... PREP_RESULT_JSON: {"prep_status":"FAILED","summary":"broken"}'
        )
        assert success is False
        assert mode == "json"

    def test_falls_back_to_legacy_status(self) -> None:
        success, mode = _parse_prep_result("PREP_STATUS: SUCCESS")
        assert success is True
        assert mode == "legacy"


class TestPrepAgentPrompt:
    """Tests for prep prompt safety constraints."""

    def test_prompt_includes_scope_and_no_parallel_constraints(self) -> None:
        prompt = _build_prep_agent_prompt(
            stack="node",
            failures=[("prep-workflow-agent", ["claude", "opus"], "failed")],
            issue_filenames=["auto-fix-prep.md"],
        )
        assert "Do not run parallel/batch edits" in prompt
        assert "Do not refactor unrelated application source" in prompt


class TestCoverageValidation:
    """Tests for coverage artifact extraction and validation."""

    def test_extracts_lcov_percent(self, tmp_path: Path) -> None:
        (tmp_path / "lcov.info").write_text(
            "TN:\nSF:file.js\nLF:100\nLH:65\nend_of_record\n"
        )
        pct, source = _extract_coverage_percent(tmp_path)
        assert pct == pytest.approx(65.0)
        assert source == "lcov.info"

    def test_extracts_coverage_summary_json_percent(self, tmp_path: Path) -> None:
        cov_dir = tmp_path / "coverage"
        cov_dir.mkdir()
        (cov_dir / "coverage-summary.json").write_text(
            '{"total":{"lines":{"pct":72.4}}}'
        )
        pct, source = _extract_coverage_percent(tmp_path)
        assert pct == pytest.approx(72.4)
        assert source == "coverage/coverage-summary.json"

    def test_extracts_coverage_xml_line_rate_percent(self, tmp_path: Path) -> None:
        (tmp_path / "coverage.xml").write_text('<coverage line-rate="0.82"></coverage>')
        pct, source = _extract_coverage_percent(tmp_path)
        assert pct == pytest.approx(82.0)
        assert source == "coverage.xml"

    def test_validation_fails_without_artifact(self, tmp_path: Path) -> None:
        ok, warn, detail = _evaluate_coverage_validation(tmp_path)
        assert ok is False
        assert warn is False
        assert "no coverage report artifact found" in detail

    def test_validation_fails_below_minimum(self, tmp_path: Path) -> None:
        (tmp_path / "lcov.info").write_text("LF:100\nLH:60\n")
        ok, warn, detail = _evaluate_coverage_validation(tmp_path)
        assert ok is False
        assert warn is False
        assert "below minimum 70%" in detail

    def test_validation_passes_at_minimum_floor(self, tmp_path: Path) -> None:
        (tmp_path / "lcov.info").write_text("LF:100\nLH:70\n")
        ok, warn, detail = _evaluate_coverage_validation(tmp_path)
        assert ok is True
        assert warn is False
        assert "passed" in detail

    def test_validation_passes_at_target(self, tmp_path: Path) -> None:
        (tmp_path / "lcov.info").write_text("LF:100\nLH:85\n")
        ok, warn, detail = _evaluate_coverage_validation(tmp_path)
        assert ok is True
        assert warn is False
        assert "passed" in detail

    def test_project_has_test_signal_from_makefile_target(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text("test:\n\t@echo test\n")
        assert _project_has_test_signal(tmp_path) is True

    def test_coverage_roots_include_only_projects_with_tests(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "Makefile").write_text("test:\n\t@echo test\n")
        pkg_a = tmp_path / "packages" / "a"
        pkg_a.mkdir(parents=True)
        (pkg_a / "Makefile").write_text("test:\n\t@echo test\n")
        pkg_b = tmp_path / "packages" / "b"
        pkg_b.mkdir(parents=True)
        roots = _coverage_validation_roots(tmp_path, [".", "packages/a", "packages/b"])
        rels = ["." if p == tmp_path else str(p.relative_to(tmp_path)) for p in roots]
        assert rels == [".", "packages/a"]

    def test_coverage_projects_fails_when_any_project_below_min(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "lcov.info").write_text("LF:100\nLH:80\n")
        pkg_a = tmp_path / "packages" / "a"
        pkg_a.mkdir(parents=True)
        (pkg_a / "lcov.info").write_text("LF:100\nLH:40\n")
        ok, warn, detail = _evaluate_coverage_validation_projects(
            tmp_path, [tmp_path, pkg_a]
        )
        assert ok is False
        assert warn is False
        assert "packages/a:" in detail
        assert "below minimum 70%" in detail


# ---------------------------------------------------------------------------
# parse_args — defaults
# ---------------------------------------------------------------------------


class TestParseArgs:
    """Tests for parse_args() default values."""

    def test_no_args_returns_none_for_optional_fields(self) -> None:
        """All non-boolean CLI args should default to None when no args given."""
        args = parse_args([])

        none_fields = [
            "ready_label",
            "batch_size",
            "max_workers",
            "max_planners",
            "max_reviewers",
            "max_hitl_workers",
            "model",
            "implementation_tool",
            "review_model",
            "review_tool",
            "ci_check_timeout",
            "ci_poll_interval",
            "max_ci_fix_attempts",
            "max_pre_quality_review_attempts",
            "review_label",
            "hitl_label",
            "hitl_active_label",
            "fixed_label",
            "find_label",
            "planner_label",
            "improve_label",
            "triage_tool",
            "planner_model",
            "planner_tool",
            "repo",
            "main_branch",
            "ac_tool",
            "verification_judge_tool",
            "dashboard_port",
            "gh_token",
        ]
        for field in none_fields:
            assert getattr(args, field) is None, f"{field} should be None"

    def test_store_true_flags_default_to_false(self) -> None:
        """Boolean store_true flags should default to False."""
        args = parse_args([])
        assert args.dry_run is False
        assert args.no_dashboard is False
        assert args.verbose is False
        assert args.clean is False

    def test_log_file_default(self) -> None:
        """--log-file should default to .hydraflow/logs/hydraflow.log."""
        args = parse_args([])
        assert args.log_file == ".hydraflow/logs/hydraflow.log"

    def test_log_file_explicit_value(self) -> None:
        """An explicit --log-file value should be preserved."""
        args = parse_args(["--log-file", "/tmp/custom.log"])
        assert args.log_file == "/tmp/custom.log"

    def test_explicit_int_arg_preserved(self) -> None:
        args = parse_args(["--batch-size", "10"])
        assert args.batch_size == 10

    def test_explicit_float_arg_preserved(self) -> None:
        args = parse_args(["--docker-cpu-limit", "5.5"])
        assert args.docker_cpu_limit == pytest.approx(5.5)

    def test_explicit_string_arg_preserved(self) -> None:
        args = parse_args(["--model", "haiku"])
        assert args.model == "haiku"

    def test_explicit_label_arg_preserved(self) -> None:
        args = parse_args(["--ready-label", "foo,bar"])
        assert args.ready_label == "foo,bar"


# ---------------------------------------------------------------------------
# build_config — integration with HydraFlowConfig
# ---------------------------------------------------------------------------


_CLI_DEFAULT_EXPECTATIONS: list[tuple[str, object]] = [
    ("ready_label", ["hydraflow-ready"]),
    ("batch_size", 15),
    ("max_workers", 3),
    ("max_planners", 1),
    ("max_reviewers", 5),
    ("max_hitl_workers", 1),
    ("hitl_active_label", ["hydraflow-hitl-active"]),
    ("implementation_tool", "claude"),
    ("model", "opus"),
    ("review_tool", "claude"),
    ("review_model", "sonnet"),
    ("ci_check_timeout", 600),
    ("ci_poll_interval", 30),
    ("max_ci_fix_attempts", 2),
    ("max_pre_quality_review_attempts", 1),
    ("review_label", ["hydraflow-review"]),
    ("hitl_label", ["hydraflow-hitl"]),
    ("fixed_label", ["hydraflow-fixed"]),
    ("find_label", ["hydraflow-find"]),
    ("planner_label", ["hydraflow-plan"]),
    ("improve_label", ["hydraflow-improve"]),
    ("triage_tool", "claude"),
    ("planner_tool", "claude"),
    ("planner_model", "opus"),
    ("ac_tool", "claude"),
    ("verification_judge_tool", "claude"),
    ("main_branch", "main"),
    ("dashboard_port", 5555),
    ("dashboard_enabled", True),
    ("dry_run", False),
]


class TestBuildConfig:
    """Tests for build_config() converting CLI args → HydraFlowConfig."""

    @pytest.mark.parametrize(
        ("field", "expected"),
        _CLI_DEFAULT_EXPECTATIONS,
        ids=[e[0] for e in _CLI_DEFAULT_EXPECTATIONS],
    )
    def test_no_cli_args_uses_hydraflow_config_defaults(
        self, field: str, expected: object
    ) -> None:
        """With no CLI args, build_config should produce HydraFlowConfig defaults."""
        args = parse_args([])
        cfg = build_config(args)
        assert getattr(cfg, field) == expected

    def test_explicit_cli_arg_overrides_default(self) -> None:
        """An explicit CLI arg should override the HydraFlowConfig default."""
        args = parse_args(["--batch-size", "10"])
        cfg = build_config(args)

        assert cfg.batch_size == 10
        # Other fields remain at defaults
        assert cfg.max_workers == 3
        assert cfg.model == "opus"

    def test_label_arg_parsed_to_list(self) -> None:
        """A comma-separated label CLI arg should become a list."""
        args = parse_args(["--ready-label", "foo,bar"])
        cfg = build_config(args)

        assert cfg.ready_label == ["foo", "bar"]

    def test_no_dashboard_flag_sets_dashboard_disabled(self) -> None:
        """--no-dashboard should set dashboard_enabled=False."""
        args = parse_args(["--no-dashboard"])
        cfg = build_config(args)

        assert cfg.dashboard_enabled is False

    def test_dry_run_flag(self) -> None:
        """--dry-run should set dry_run=True."""
        args = parse_args(["--dry-run"])
        cfg = build_config(args)

        assert cfg.dry_run is True

    def test_multiple_args_combined(self) -> None:
        """Multiple CLI args should all land in the config correctly."""
        args = parse_args(
            [
                "--batch-size",
                "5",
                "--model",
                "haiku",
                "--max-workers",
                "4",
                "--dry-run",
                "--review-label",
                "review-me,check-me",
            ]
        )
        cfg = build_config(args)

        assert cfg.batch_size == 5
        assert cfg.model == "haiku"
        assert cfg.max_workers == 4
        assert cfg.dry_run is True
        assert cfg.review_label == ["review-me", "check-me"]
        # Non-specified fields remain at defaults
        assert cfg.max_planners == 1
        assert cfg.main_branch == "main"

    def test_gh_token_passed_through(self) -> None:
        """--gh-token value should land in config."""
        args = parse_args(["--gh-token", "ghp_abc123"])
        cfg = build_config(args)

        assert cfg.gh_token == "ghp_abc123"

    def test_repo_passed_through(self) -> None:
        """--repo value should land in config."""
        args = parse_args(["--repo", "org/repo"])
        cfg = build_config(args)

        assert cfg.repo == "org/repo"

    def test_all_label_fields_parsed(self) -> None:
        """All label CLI args should be split into lists."""
        args = parse_args(
            [
                "--ready-label",
                "a,b",
                "--review-label",
                "c",
                "--hitl-label",
                "d,e",
                "--hitl-active-label",
                "d2,e2",
                "--fixed-label",
                "f",
                "--find-label",
                "g,h",
                "--planner-label",
                "i",
                "--improve-label",
                "j,k",
            ]
        )
        cfg = build_config(args)

        assert cfg.ready_label == ["a", "b"]
        assert cfg.review_label == ["c"]
        assert cfg.hitl_label == ["d", "e"]
        assert cfg.hitl_active_label == ["d2", "e2"]
        assert cfg.fixed_label == ["f"]
        assert cfg.find_label == ["g", "h"]
        assert cfg.planner_label == ["i"]
        assert cfg.improve_label == ["j", "k"]

    def test_planner_model_passed_through(self) -> None:
        args = parse_args(["--planner-model", "sonnet"])
        cfg = build_config(args)
        assert cfg.planner_model == "sonnet"

    def test_tool_fields_passed_through(self) -> None:
        args = parse_args(
            [
                "--implementation-tool",
                "codex",
                "--review-tool",
                "codex",
                "--triage-tool",
                "codex",
                "--planner-tool",
                "codex",
                "--ac-tool",
                "codex",
                "--verification-judge-tool",
                "codex",
            ]
        )
        cfg = build_config(args)
        assert cfg.implementation_tool == "codex"
        assert cfg.review_tool == "codex"
        assert cfg.triage_tool == "codex"
        assert cfg.planner_tool == "codex"
        assert cfg.ac_tool == "codex"
        assert cfg.verification_judge_tool == "codex"

    def test_ci_fields_passed_through(self) -> None:
        args = parse_args(
            [
                "--ci-check-timeout",
                "300",
                "--ci-poll-interval",
                "10",
                "--max-ci-fix-attempts",
                "3",
                "--max-pre-quality-review-attempts",
                "2",
            ]
        )
        cfg = build_config(args)
        assert cfg.ci_check_timeout == 300
        assert cfg.ci_poll_interval == 10
        assert cfg.max_ci_fix_attempts == 3
        assert cfg.max_pre_quality_review_attempts == 2

    def test_dashboard_port_passed_through(self) -> None:
        args = parse_args(["--dashboard-port", "8080"])
        cfg = build_config(args)
        assert cfg.dashboard_port == 8080

    def test_min_plan_words_passed_through(self) -> None:
        args = parse_args(["--min-plan-words", "300"])
        cfg = build_config(args)
        assert cfg.min_plan_words == 300

    def test_lite_plan_labels_passed_through(self) -> None:
        args = parse_args(["--lite-plan-labels", "hotfix,patch,minor"])
        cfg = build_config(args)
        assert cfg.lite_plan_labels == ["hotfix", "patch", "minor"]

    def test_git_user_name_passed_through(self) -> None:
        args = parse_args(["--git-user-name", "T-rav-HydraFlow-Ops"])
        cfg = build_config(args)
        assert cfg.git_user_name == "T-rav-HydraFlow-Ops"

    def test_git_user_email_passed_through(self) -> None:
        args = parse_args(["--git-user-email", "bot@example.com"])
        cfg = build_config(args)
        assert cfg.git_user_email == "bot@example.com"

    def test_max_hitl_workers_passed_through(self) -> None:
        args = parse_args(["--max-hitl-workers", "3"])
        cfg = build_config(args)
        assert cfg.max_hitl_workers == 3

    def test_hitl_active_label_passed_through(self) -> None:
        args = parse_args(["--hitl-active-label", "my-active"])
        cfg = build_config(args)
        assert cfg.hitl_active_label == ["my-active"]

    def test_improve_label_passed_through(self) -> None:
        args = parse_args(["--improve-label", "my-improve"])
        cfg = build_config(args)
        assert cfg.improve_label == ["my-improve"]

    def test_git_identity_defaults_to_none_in_parse_args(self) -> None:
        args = parse_args([])
        assert args.git_user_name is None
        assert args.git_user_email is None


# ---------------------------------------------------------------------------
# _run_main — signal handler registration
# ---------------------------------------------------------------------------


class TestRunMainSignalHandlers:
    """Tests for signal handler registration in _run_main()."""

    @pytest.mark.asyncio
    async def test_headless_registers_signal_handlers(self) -> None:
        """In headless mode, SIGINT and SIGTERM handlers are registered."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(dashboard_enabled=False)

        registered_signals: list[int] = []
        mock_loop = MagicMock()
        mock_loop.add_signal_handler = MagicMock(
            side_effect=lambda sig, cb: registered_signals.append(sig)
        )

        mock_orch = AsyncMock()
        mock_orch.run = AsyncMock()
        mock_orch.stop = AsyncMock()

        with (
            patch("cli.HydraFlowOrchestrator", return_value=mock_orch),
            patch("asyncio.get_running_loop", return_value=mock_loop),
        ):
            await _run_main(config)

        assert signal.SIGINT in registered_signals
        assert signal.SIGTERM in registered_signals

    @pytest.mark.asyncio
    async def test_headless_sigint_calls_orchestrator_stop(self) -> None:
        """Simulating SIGINT callback should trigger orchestrator.stop()."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(dashboard_enabled=False)

        handlers: dict[int, object] = {}

        def capture_handler(sig: int, cb: object) -> None:
            handlers[sig] = cb

        mock_loop = MagicMock()
        mock_loop.add_signal_handler = MagicMock(side_effect=capture_handler)

        mock_orch = AsyncMock()
        mock_orch.stop = AsyncMock()

        async def fake_run() -> None:
            # Simulate signal arriving during run
            cb = handlers.get(signal.SIGINT)
            if cb:
                cb()  # type: ignore[operator]
            # Give the stop task a chance to run
            await asyncio.sleep(0)

        mock_orch.run = fake_run

        with (
            patch("cli.HydraFlowOrchestrator", return_value=mock_orch),
            patch("asyncio.get_running_loop", return_value=mock_loop),
        ):
            await _run_main(config)

        mock_orch.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_dashboard_registers_signal_handlers(self) -> None:
        """In dashboard mode, SIGINT and SIGTERM handlers are registered."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(dashboard_enabled=True)

        registered_signals: list[int] = []

        real_loop = asyncio.get_running_loop()

        def tracking_add(sig: int, cb: object) -> None:
            registered_signals.append(sig)
            # Actually set the event so _run_main unblocks
            if callable(cb):
                cb()

        mock_dashboard = AsyncMock()
        mock_dashboard._orchestrator = None
        mock_dashboard.start = AsyncMock()
        mock_dashboard.stop = AsyncMock()

        with (
            patch.object(real_loop, "add_signal_handler", side_effect=tracking_add),
            patch("dashboard.HydraFlowDashboard", return_value=mock_dashboard),
        ):
            await _run_main(config)

        assert signal.SIGINT in registered_signals
        assert signal.SIGTERM in registered_signals

    @pytest.mark.asyncio
    async def test_dashboard_sigint_stops_orchestrator(self) -> None:
        """In dashboard mode, SIGINT should stop the orchestrator if running."""
        from tests.helpers import ConfigFactory

        config = ConfigFactory.create(dashboard_enabled=True)

        real_loop = asyncio.get_running_loop()

        mock_orch = AsyncMock()
        mock_orch.running = True
        mock_orch.stop = AsyncMock()

        mock_dashboard = AsyncMock()
        mock_dashboard._orchestrator = mock_orch
        mock_dashboard.start = AsyncMock()
        mock_dashboard.stop = AsyncMock()

        def trigger_stop(sig: int, cb: object) -> None:
            if sig == signal.SIGINT and callable(cb):
                cb()

        with (
            patch.object(real_loop, "add_signal_handler", side_effect=trigger_stop),
            patch("dashboard.HydraFlowDashboard", return_value=mock_dashboard),
        ):
            await _run_main(config)

        mock_orch.stop.assert_called_once()
        mock_dashboard.stop.assert_called_once()


# ---------------------------------------------------------------------------
# --max-issue-attempts CLI arg
# ---------------------------------------------------------------------------


class TestMaxIssueAttemptsCLI:
    """Tests for the --max-issue-attempts CLI argument."""

    def test_parses_max_issue_attempts(self) -> None:
        args = parse_args(["--max-issue-attempts", "5"])
        assert args.max_issue_attempts == 5

    def test_defaults_to_none(self) -> None:
        args = parse_args([])
        assert args.max_issue_attempts is None

    def test_build_config_maps_max_issue_attempts(self) -> None:
        args = parse_args(["--max-issue-attempts", "7"])
        config = build_config(args)
        assert config.max_issue_attempts == 7


# ---------------------------------------------------------------------------
# Docker CLI arguments
# ---------------------------------------------------------------------------


class TestDockerCLIArgs:
    """Tests for Docker-related CLI arguments."""

    def test_docker_flag_sets_execution_mode(self) -> None:
        args = parse_args(["--docker"])
        assert args.execution_mode == "docker"

    def test_host_flag_sets_execution_mode(self) -> None:
        args = parse_args(["--host"])
        assert args.execution_mode == "host"

    def test_no_flag_leaves_execution_mode_none(self) -> None:
        args = parse_args([])
        assert args.execution_mode is None

    def test_docker_and_host_mutually_exclusive(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["--docker", "--host"])

    def test_docker_image_arg(self) -> None:
        args = parse_args(["--docker-image", "custom/image:v1"])
        assert args.docker_image == "custom/image:v1"

    def test_docker_cpu_limit_arg(self) -> None:
        args = parse_args(["--docker-cpu-limit", "4.0"])
        assert args.docker_cpu_limit == pytest.approx(4.0)

    def test_docker_memory_limit_arg(self) -> None:
        args = parse_args(["--docker-memory-limit", "8g"])
        assert args.docker_memory_limit == "8g"

    def test_docker_network_mode_arg(self) -> None:
        args = parse_args(["--docker-network-mode", "none"])
        assert args.docker_network_mode == "none"

    def test_docker_network_mode_invalid_choice(self) -> None:
        with pytest.raises(SystemExit):
            parse_args(["--docker-network-mode", "overlay"])

    def test_docker_spawn_delay_arg(self) -> None:
        args = parse_args(["--docker-spawn-delay", "5.0"])
        assert args.docker_spawn_delay == pytest.approx(5.0)

    def test_docker_read_only_root_arg(self) -> None:
        args = parse_args(["--docker-read-only-root"])
        assert args.docker_read_only_root is True

    def test_docker_no_new_privileges_arg(self) -> None:
        args = parse_args(["--docker-no-new-privileges"])
        assert args.docker_no_new_privileges is True

    def test_docker_args_default_to_none(self) -> None:
        args = parse_args([])
        assert args.docker_image is None
        assert args.docker_cpu_limit is None
        assert args.docker_memory_limit is None
        assert args.docker_network_mode is None
        assert args.docker_spawn_delay is None
        assert args.docker_read_only_root is None
        assert args.docker_no_new_privileges is None


class TestDockerBuildConfig:
    """Tests for Docker CLI args passing through to HydraFlowConfig via build_config."""

    def test_docker_flag_builds_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        args = parse_args(["--docker"])
        cfg = build_config(args)
        assert cfg.execution_mode == "docker"

    def test_host_flag_builds_config(self) -> None:
        args = parse_args(["--host"])
        cfg = build_config(args)
        assert cfg.execution_mode == "host"

    def test_docker_image_builds_config(self) -> None:
        args = parse_args(["--docker-image", "my/image:latest"])
        cfg = build_config(args)
        assert cfg.docker_image == "my/image:latest"

    def test_docker_cpu_limit_builds_config(self) -> None:
        args = parse_args(["--docker-cpu-limit", "4.0"])
        cfg = build_config(args)
        assert cfg.docker_cpu_limit == pytest.approx(4.0)

    def test_docker_memory_limit_builds_config(self) -> None:
        args = parse_args(["--docker-memory-limit", "16g"])
        cfg = build_config(args)
        assert cfg.docker_memory_limit == "16g"

    def test_docker_network_mode_builds_config(self) -> None:
        args = parse_args(["--docker-network-mode", "host"])
        cfg = build_config(args)
        assert cfg.docker_network_mode == "host"

    def test_docker_spawn_delay_builds_config(self) -> None:
        args = parse_args(["--docker-spawn-delay", "10.0"])
        cfg = build_config(args)
        assert cfg.docker_spawn_delay == pytest.approx(10.0)

    def test_no_docker_flags_uses_defaults(self) -> None:
        args = parse_args([])
        cfg = build_config(args)
        assert cfg.execution_mode == "host"
        assert cfg.docker_image == "ghcr.io/t-rav/hydraflow-agent:latest"
        assert cfg.docker_cpu_limit == pytest.approx(2.0)
        assert cfg.docker_memory_limit == "4g"
        assert cfg.docker_network_mode == "bridge"
        assert cfg.docker_spawn_delay == pytest.approx(2.0)
        assert cfg.docker_read_only_root is True
        assert cfg.docker_no_new_privileges is True
