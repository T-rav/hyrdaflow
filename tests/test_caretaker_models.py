"""Tests for caretaker worker models and state persistence."""

from __future__ import annotations

import pytest

from config import HydraFlowConfig
from models import CIMonitorSettings, SecurityPatchSettings, StaleIssueSettings
from state import StateTracker


class TestStaleIssueSettings:
    def test_defaults(self) -> None:
        s = StaleIssueSettings()
        assert s.staleness_days == 30
        assert s.excluded_labels == []
        assert s.dry_run is False

    def test_validates_min_days(self) -> None:
        with pytest.raises(ValueError):
            StaleIssueSettings(staleness_days=1)

    def test_state_roundtrip(self, tmp_path: object) -> None:
        config = HydraFlowConfig(repo_root=str(tmp_path), gh_token="fake")
        state = StateTracker(config.state_file)
        state.set_stale_issue_settings(
            StaleIssueSettings(staleness_days=60, excluded_labels=["keep"])
        )
        loaded = state.get_stale_issue_settings()
        assert loaded.staleness_days == 60
        assert loaded.excluded_labels == ["keep"]

    def test_closed_tracking(self, tmp_path: object) -> None:
        config = HydraFlowConfig(repo_root=str(tmp_path), gh_token="fake")
        state = StateTracker(config.state_file)
        state.add_stale_issue_closed(42)
        state.add_stale_issue_closed(99)
        assert state.get_stale_issue_closed() == {42, 99}


class TestSecurityPatchSettings:
    def test_defaults(self) -> None:
        s = SecurityPatchSettings()
        assert s.severity_levels == ["critical", "high"]

    def test_custom_severity(self) -> None:
        s = SecurityPatchSettings(severity_levels=["critical"])
        assert s.severity_levels == ["critical"]

    def test_state_roundtrip(self, tmp_path: object) -> None:
        config = HydraFlowConfig(repo_root=str(tmp_path), gh_token="fake")
        state = StateTracker(config.state_file)
        state.set_security_patch_settings(
            SecurityPatchSettings(severity_levels=["critical", "high", "medium"])
        )
        loaded = state.get_security_patch_settings()
        assert "medium" in loaded.severity_levels

    def test_processed_tracking(self, tmp_path: object) -> None:
        config = HydraFlowConfig(repo_root=str(tmp_path), gh_token="fake")
        state = StateTracker(config.state_file)
        state.add_security_patch_processed("alert-123")
        assert "alert-123" in state.get_security_patch_processed()


class TestCIMonitorSettings:
    def test_defaults(self) -> None:
        s = CIMonitorSettings()
        assert s.branch == "main"
        assert s.workflows == []
        assert s.create_issue is True

    def test_custom(self) -> None:
        s = CIMonitorSettings(
            branch="develop", workflows=["CI", "Deploy"], create_issue=False
        )
        assert s.branch == "develop"

    def test_state_roundtrip(self, tmp_path: object) -> None:
        config = HydraFlowConfig(repo_root=str(tmp_path), gh_token="fake")
        state = StateTracker(config.state_file)
        state.set_ci_monitor_settings(CIMonitorSettings(branch="develop"))
        loaded = state.get_ci_monitor_settings()
        assert loaded.branch == "develop"

    def test_tracked_failures(self, tmp_path: object) -> None:
        config = HydraFlowConfig(repo_root=str(tmp_path), gh_token="fake")
        state = StateTracker(config.state_file)
        state.set_ci_monitor_tracked_failures({"CI": "run-123"})
        assert state.get_ci_monitor_tracked_failures() == {"CI": "run-123"}
        state.clear_ci_monitor_failure("CI")
        assert state.get_ci_monitor_tracked_failures() == {}
