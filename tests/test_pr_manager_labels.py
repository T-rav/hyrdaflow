"""Tests for pr_manager.py — label and comment helpers."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from pr_manager import PRManager
from tests.conftest import SubprocessMockBuilder
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(config, event_bus):
    return PRManager(config=config, event_bus=event_bus)


# ---------------------------------------------------------------------------
# add_labels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_labels_calls_issue_labels_api_for_each_label(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.add_labels(42, ["bug", "enhancement"])

    assert mock_create.call_count == 2

    first_args = mock_create.call_args_list[0][0]
    assert first_args[0] == "gh"
    assert "api" in first_args
    assert "repos/test-org/test-repo/issues/42/labels" in first_args
    assert "POST" in first_args
    assert "labels[]=bug" in first_args

    second_args = mock_create.call_args_list[1][0]
    assert "labels[]=enhancement" in second_args


@pytest.mark.asyncio
async def test_add_labels_dry_run_skips_command(dry_config, event_bus):
    manager = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.add_labels(42, ["bug"])

    mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_add_labels_empty_list_skips_command(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.add_labels(42, [])

    mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# remove_label
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_label_calls_issue_labels_api(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.remove_label(42, "ready")

    assert mock_create.call_count == 1
    args = mock_create.call_args[0]
    assert args[0] == "gh"
    assert "api" in args
    assert "repos/test-org/test-repo/issues/42/labels/ready" in args
    assert "DELETE" in args


@pytest.mark.asyncio
async def test_remove_label_dry_run_skips_command(dry_config, event_bus):
    manager = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.remove_label(42, "ready")

    mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# add_pr_labels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_pr_labels_calls_issue_labels_api_for_each_label(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.add_pr_labels(101, ["bug", "enhancement"])

    assert mock_create.call_count == 2

    first_args = mock_create.call_args_list[0][0]
    assert first_args[0] == "gh"
    assert "api" in first_args
    assert "repos/test-org/test-repo/issues/101/labels" in first_args
    assert "POST" in first_args
    assert "labels[]=bug" in first_args

    second_args = mock_create.call_args_list[1][0]
    assert "labels[]=enhancement" in second_args


@pytest.mark.asyncio
async def test_add_pr_labels_dry_run_skips_command(dry_config, event_bus):
    manager = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.add_pr_labels(101, ["bug"])

    mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_add_pr_labels_empty_list_skips_command(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.add_pr_labels(101, [])

    mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_add_pr_labels_subprocess_error_does_not_raise(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = (
        SubprocessMockBuilder().with_returncode(1).with_stderr("label error").build()
    )

    with patch("asyncio.create_subprocess_exec", mock_create):
        # Should not raise
        await manager.add_pr_labels(101, ["bug"])


# ---------------------------------------------------------------------------
# remove_pr_label
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_pr_label_calls_issue_labels_api(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = SubprocessMockBuilder().with_stdout("").build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.remove_pr_label(101, "hydraflow-review")

    args = mock_create.call_args[0]
    assert "api" in args
    assert "repos/test-org/test-repo/issues/101/labels/hydraflow-review" in args
    assert "DELETE" in args


@pytest.mark.asyncio
async def test_remove_pr_label_dry_run_skips_command(dry_config, event_bus):
    manager = _make_manager(dry_config, event_bus)
    mock_create = SubprocessMockBuilder().build()

    with patch("asyncio.create_subprocess_exec", mock_create):
        await manager.remove_pr_label(101, "hydraflow-review")

    mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_remove_pr_label_subprocess_error_does_not_raise(config, event_bus):
    manager = _make_manager(config, event_bus)
    mock_create = (
        SubprocessMockBuilder().with_returncode(1).with_stderr("label error").build()
    )

    with patch("asyncio.create_subprocess_exec", mock_create):
        # Should not raise
        await manager.remove_pr_label(101, "hydraflow-review")


# ---------------------------------------------------------------------------
# Private helper: _comment
# ---------------------------------------------------------------------------


class TestCommentHelper:
    """Tests for the unified _comment() helper."""

    @pytest.mark.asyncio
    async def test_comment_issue_target(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._comment("issue", 42, "test body")

        cmd = mock_create.call_args[0]
        assert "issue" in cmd
        assert "comment" in cmd
        assert "42" in cmd

    @pytest.mark.asyncio
    async def test_comment_pr_target(self, event_bus, tmp_path):
        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._comment("pr", 101, "test body")

        cmd = mock_create.call_args[0]
        assert "pr" in cmd
        assert "comment" in cmd
        assert "101" in cmd

    @pytest.mark.asyncio
    async def test_comment_dry_run(self, dry_config, event_bus):
        mgr = _make_manager(dry_config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._comment("issue", 42, "body")

        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_comment_error_does_not_raise(self, event_bus, tmp_path):
        """_comment should log a warning on failure without propagating the error."""

        cfg = ConfigFactory.create(
            repo_root=tmp_path,
            worktree_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        mgr = _make_manager(cfg, event_bus)
        mock_create = (
            SubprocessMockBuilder()
            .with_returncode(1)
            .with_stderr("permission denied")
            .build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            # Should not raise even on subprocess failure
            await mgr._comment("pr", 99, "body")


# ---------------------------------------------------------------------------
# Private helper: _add_labels
# ---------------------------------------------------------------------------


class TestAddLabelsHelper:
    """Tests for the unified _add_labels() helper."""

    @pytest.mark.asyncio
    async def test_add_labels_issue_target(self, config, event_bus):
        mgr = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._add_labels("issue", 42, ["bug"])

        cmd = mock_create.call_args[0]
        assert "api" in cmd
        assert "repos/test-org/test-repo/issues/42/labels" in cmd
        assert "POST" in cmd
        assert "labels[]=bug" in cmd

    @pytest.mark.asyncio
    async def test_add_labels_pr_target(self, config, event_bus):
        mgr = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._add_labels("pr", 101, ["enhancement"])

        cmd = mock_create.call_args[0]
        assert "api" in cmd
        assert "repos/test-org/test-repo/issues/101/labels" in cmd
        assert "POST" in cmd
        assert "labels[]=enhancement" in cmd

    @pytest.mark.asyncio
    async def test_add_labels_dry_run(self, dry_config, event_bus):
        mgr = _make_manager(dry_config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._add_labels("issue", 42, ["bug"])

        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_labels_empty_list(self, config, event_bus):
        mgr = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._add_labels("pr", 101, [])

        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_labels_error_does_not_raise(self, config, event_bus):
        """_add_labels should log a warning on failure without propagating the error."""
        mgr = _make_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder()
            .with_returncode(1)
            .with_stderr("label not found")
            .build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            # Should not raise even on subprocess failure
            await mgr._add_labels("issue", 42, ["missing-label"])


# ---------------------------------------------------------------------------
# Private helper: _remove_label
# ---------------------------------------------------------------------------


class TestRemoveLabelHelper:
    """Tests for the unified _remove_label() helper."""

    @pytest.mark.asyncio
    async def test_remove_label_issue_target(self, config, event_bus):
        mgr = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._remove_label("issue", 42, "ready")

        cmd = mock_create.call_args[0]
        assert "api" in cmd
        assert "repos/test-org/test-repo/issues/42/labels/ready" in cmd
        assert "DELETE" in cmd

    @pytest.mark.asyncio
    async def test_remove_label_pr_target(self, config, event_bus):
        mgr = _make_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._remove_label("pr", 101, "hydraflow-review")

        cmd = mock_create.call_args[0]
        assert "api" in cmd
        assert "repos/test-org/test-repo/issues/101/labels/hydraflow-review" in cmd
        assert "DELETE" in cmd

    @pytest.mark.asyncio
    async def test_remove_label_dry_run(self, dry_config, event_bus):
        mgr = _make_manager(dry_config, event_bus)
        mock_create = SubprocessMockBuilder().build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            await mgr._remove_label("pr", 101, "label")

        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_label_error_does_not_raise(self, config, event_bus):
        """_remove_label should log a warning on failure without propagating the error."""
        mgr = _make_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder()
            .with_returncode(1)
            .with_stderr("label not found")
            .build()
        )

        with patch("asyncio.create_subprocess_exec", mock_create):
            # Should not raise even on subprocess failure
            await mgr._remove_label("issue", 42, "missing-label")

    @pytest.mark.asyncio
    async def test_remove_label_missing_label_404_is_noop(
        self, config, event_bus, caplog
    ):
        """Missing-label 404 should be treated as expected no-op (not warning)."""
        mgr = _make_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder()
            .with_returncode(1)
            .with_stderr("gh: Label does not exist (HTTP 404)")
            .build()
        )

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            caplog.at_level(logging.DEBUG, logger="hydraflow.pr_manager"),
        ):
            await mgr._remove_label("issue", 42, "missing-label")

        assert "Could not remove label" not in caplog.text
        assert "skipping remove" in caplog.text


# ---------------------------------------------------------------------------
# swap_pipeline_labels
# ---------------------------------------------------------------------------


class TestSwapPipelineLabels:
    """Tests for PRManager.swap_pipeline_labels."""

    @pytest.mark.asyncio
    async def test_removes_all_other_pipeline_labels_from_issue(
        self, config, event_bus
    ) -> None:
        mgr = _make_manager(config, event_bus)
        mgr._remove_label = AsyncMock()
        mgr._add_labels = AsyncMock()

        await mgr.swap_pipeline_labels(42, config.ready_label[0])

        # All pipeline labels except the target should be removed
        removed = [call.args[2] for call in mgr._remove_label.call_args_list]
        assert config.ready_label[0] not in removed
        # At least some labels should be removed
        assert len(removed) > 0

    @pytest.mark.asyncio
    async def test_adds_new_label_to_issue(self, config, event_bus) -> None:
        mgr = _make_manager(config, event_bus)
        mgr._remove_label = AsyncMock()
        mgr._add_labels = AsyncMock()

        await mgr.swap_pipeline_labels(42, "hydraflow-review")

        mgr._add_labels.assert_any_call("issue", 42, ["hydraflow-review"])

    @pytest.mark.asyncio
    async def test_also_removes_from_pr_when_pr_number_given(
        self, config, event_bus
    ) -> None:
        mgr = _make_manager(config, event_bus)
        mgr._remove_label = AsyncMock()
        mgr._add_labels = AsyncMock()

        await mgr.swap_pipeline_labels(42, "hydraflow-review", pr_number=101)

        # Should have remove calls for both issue and pr
        targets = [call.args[0] for call in mgr._remove_label.call_args_list]
        assert "issue" in targets
        assert "pr" in targets
        # Should add to both issue and pr
        mgr._add_labels.assert_any_call("issue", 42, ["hydraflow-review"])
        mgr._add_labels.assert_any_call("pr", 101, ["hydraflow-review"])

    @pytest.mark.asyncio
    async def test_no_pr_label_ops_when_pr_number_none(self, config, event_bus) -> None:
        mgr = _make_manager(config, event_bus)
        mgr._remove_label = AsyncMock()
        mgr._add_labels = AsyncMock()

        await mgr.swap_pipeline_labels(42, "hydraflow-review")

        targets = [call.args[0] for call in mgr._remove_label.call_args_list]
        assert "pr" not in targets
        # Only one add_labels call (for issue)
        assert mgr._add_labels.call_count == 1


# ---------------------------------------------------------------------------
# TaskTransitioner protocol compliance
# ---------------------------------------------------------------------------


class TestTaskTransitionerProtocol:
    """PRManager satisfies the TaskTransitioner protocol."""

    def _make_mgr(self):
        from unittest.mock import MagicMock

        from pr_manager import PRManager
        from tests.helpers import ConfigFactory

        return PRManager(ConfigFactory.create(), event_bus=MagicMock())

    def test_pr_manager_is_task_transitioner(self) -> None:
        """PRManager should be recognised as TaskTransitioner at runtime."""
        from task_source import TaskTransitioner

        assert isinstance(self._make_mgr(), TaskTransitioner)

    def test_pr_manager_has_transition_method(self) -> None:
        mgr = self._make_mgr()
        assert hasattr(mgr, "transition")
        assert callable(mgr.transition)

    def test_pr_manager_has_close_task_method(self) -> None:
        mgr = self._make_mgr()
        assert hasattr(mgr, "close_task")
        assert callable(mgr.close_task)

    def test_pr_manager_has_create_task_method(self) -> None:
        mgr = self._make_mgr()
        assert hasattr(mgr, "create_task")
        assert callable(mgr.create_task)
