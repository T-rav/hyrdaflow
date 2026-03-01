"""Tests for run_recorder.py — per-issue run recording for replay/debugging."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from run_recorder import RunContext, RunManifest, RunRecorder
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# RunContext
# ---------------------------------------------------------------------------


class TestRunContext:
    """Tests for the RunContext active recording session."""

    def test_save_plan_writes_file(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run1"
        run_dir.mkdir()
        ctx = RunContext(run_dir, issue_number=42, timestamp="20260101T000000Z")
        ctx.save_plan("## Plan\n\n1. Do the thing")
        assert (run_dir / "plan.md").read_text() == "## Plan\n\n1. Do the thing"

    def test_save_config_writes_json(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run1"
        run_dir.mkdir()
        ctx = RunContext(run_dir, issue_number=42, timestamp="20260101T000000Z")
        ctx.save_config({"model": "opus", "max_workers": 3})
        data = json.loads((run_dir / "config.json").read_text())
        assert data["model"] == "opus"
        assert data["max_workers"] == 3

    def test_append_transcript_buffers_lines(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run1"
        run_dir.mkdir()
        ctx = RunContext(run_dir, issue_number=42, timestamp="20260101T000000Z")
        ctx.append_transcript("line 1")
        ctx.append_transcript("line 2")
        ctx.finalize("success")
        transcript = (run_dir / "transcript.log").read_text()
        assert transcript == "line 1\nline 2"

    def test_save_diff_writes_patch(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run1"
        run_dir.mkdir()
        ctx = RunContext(run_dir, issue_number=42, timestamp="20260101T000000Z")
        ctx.save_diff("--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new")
        assert (run_dir / "diff.patch").exists()

    def test_finalize_writes_manifest(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run1"
        run_dir.mkdir()
        ctx = RunContext(run_dir, issue_number=42, timestamp="20260101T000000Z")
        ctx.save_plan("plan text")
        ctx.append_transcript("log line")
        manifest = ctx.finalize("success")

        assert manifest.issue_number == 42
        assert manifest.timestamp == "20260101T000000Z"
        assert manifest.outcome == "success"
        assert manifest.error is None
        assert manifest.duration_seconds >= 0
        assert "manifest.json" in manifest.files
        assert "plan.md" in manifest.files
        assert "transcript.log" in manifest.files

    def test_finalize_records_error(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run1"
        run_dir.mkdir()
        ctx = RunContext(run_dir, issue_number=42, timestamp="20260101T000000Z")
        manifest = ctx.finalize("failed", error="Agent crashed")
        assert manifest.outcome == "failed"
        assert manifest.error == "Agent crashed"

    def test_finalize_tracks_duration(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run1"
        run_dir.mkdir()
        ctx = RunContext(run_dir, issue_number=42, timestamp="20260101T000000Z")
        # Duration should be >= 0 (it's measured from construction to finalize)
        manifest = ctx.finalize("success")
        assert manifest.duration_seconds >= 0.0

    def test_run_dir_property(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run1"
        run_dir.mkdir()
        ctx = RunContext(run_dir, issue_number=42, timestamp="20260101T000000Z")
        assert ctx.run_dir == run_dir


# ---------------------------------------------------------------------------
# RunRecorder
# ---------------------------------------------------------------------------


class TestRunRecorder:
    """Tests for the RunRecorder lifecycle management."""

    def _make_recorder(self, tmp_path: Path) -> RunRecorder:
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
        return RunRecorder(config)

    def test_start_creates_timestamped_dir(self, tmp_path: Path) -> None:
        recorder = self._make_recorder(tmp_path)
        ctx = recorder.start(42)
        assert ctx.run_dir.exists()
        assert ctx.run_dir.parent.name == "42"

    def test_list_runs_empty(self, tmp_path: Path) -> None:
        recorder = self._make_recorder(tmp_path)
        assert recorder.list_runs(42) == []

    def test_list_runs_returns_manifests(self, tmp_path: Path) -> None:
        recorder = self._make_recorder(tmp_path)
        ctx = recorder.start(42)
        ctx.append_transcript("hello")
        ctx.finalize("success")

        runs = recorder.list_runs(42)
        assert len(runs) == 1
        assert runs[0].issue_number == 42
        assert runs[0].outcome == "success"

    def test_list_runs_orders_by_timestamp(self, tmp_path: Path) -> None:
        recorder = self._make_recorder(tmp_path)

        # Create two runs manually with known timestamps
        runs_dir = tmp_path / "repo" / ".hydraflow" / "runs" / "42"
        for ts in ("20260101T100000Z", "20260101T200000Z"):
            run_dir = runs_dir / ts
            run_dir.mkdir(parents=True)
            manifest = RunManifest(issue_number=42, timestamp=ts, outcome="success")
            (run_dir / "manifest.json").write_text(manifest.model_dump_json())

        runs = recorder.list_runs(42)
        assert len(runs) == 2
        assert runs[0].timestamp == "20260101T100000Z"
        assert runs[1].timestamp == "20260101T200000Z"

    def test_get_latest_returns_most_recent(self, tmp_path: Path) -> None:
        recorder = self._make_recorder(tmp_path)

        runs_dir = tmp_path / "repo" / ".hydraflow" / "runs" / "42"
        for ts in ("20260101T100000Z", "20260101T200000Z"):
            run_dir = runs_dir / ts
            run_dir.mkdir(parents=True)
            manifest = RunManifest(issue_number=42, timestamp=ts, outcome="success")
            (run_dir / "manifest.json").write_text(manifest.model_dump_json())

        latest = recorder.get_latest(42)
        assert latest is not None
        assert latest.timestamp == "20260101T200000Z"

    def test_get_latest_returns_none_when_empty(self, tmp_path: Path) -> None:
        recorder = self._make_recorder(tmp_path)
        assert recorder.get_latest(42) is None

    def test_get_run_artifact_reads_file(self, tmp_path: Path) -> None:
        recorder = self._make_recorder(tmp_path)
        ctx = recorder.start(42)
        ctx.save_plan("the plan")
        ctx.finalize("success")

        timestamp = ctx.run_dir.name
        content = recorder.get_run_artifact(42, timestamp, "plan.md")
        assert content == "the plan"

    def test_get_run_artifact_returns_none_for_missing(self, tmp_path: Path) -> None:
        recorder = self._make_recorder(tmp_path)
        assert recorder.get_run_artifact(42, "20260101T000000Z", "nope.txt") is None

    def test_get_run_artifact_blocks_path_traversal(self, tmp_path: Path) -> None:
        recorder = self._make_recorder(tmp_path)
        ctx = recorder.start(42)
        ctx.save_plan("the plan")
        ctx.finalize("success")
        timestamp = ctx.run_dir.name

        # Create a file outside the runs dir that traversal would reach
        secret = tmp_path / "secret.txt"
        secret.write_text("sensitive data")

        # Attempt traversal via filename
        assert recorder.get_run_artifact(42, timestamp, "../../secret.txt") is None

    def test_get_run_artifact_blocks_traversal_via_timestamp(
        self, tmp_path: Path
    ) -> None:
        recorder = self._make_recorder(tmp_path)
        # Create a file outside runs dir
        secret = tmp_path / "secret.txt"
        secret.write_text("sensitive data")

        # Attempt traversal via timestamp component
        assert recorder.get_run_artifact(42, "../../..", "secret.txt") is None

    def test_list_issues_empty(self, tmp_path: Path) -> None:
        recorder = self._make_recorder(tmp_path)
        assert recorder.list_issues() == []

    def test_list_issues_returns_issue_numbers(self, tmp_path: Path) -> None:
        recorder = self._make_recorder(tmp_path)

        # Create run dirs for two issues
        for issue_num in (10, 42):
            ctx = recorder.start(issue_num)
            ctx.finalize("success")

        issues = recorder.list_issues()
        assert 10 in issues
        assert 42 in issues

    def test_skips_corrupt_manifest(self, tmp_path: Path) -> None:
        recorder = self._make_recorder(tmp_path)
        runs_dir = tmp_path / "repo" / ".hydraflow" / "runs" / "42" / "20260101T000000Z"
        runs_dir.mkdir(parents=True)
        (runs_dir / "manifest.json").write_text("not valid json {{{")

        runs = recorder.list_runs(42)
        assert runs == []

    def test_runs_dir_property(self, tmp_path: Path) -> None:
        recorder = self._make_recorder(tmp_path)
        assert recorder.runs_dir == tmp_path / "repo" / ".hydraflow" / "runs"


# ---------------------------------------------------------------------------
# RunManifest model
# ---------------------------------------------------------------------------


class TestRunManifest:
    """Tests for the RunManifest Pydantic model."""

    def test_run_manifest_defaults_to_empty_outcome_and_zero_duration(self) -> None:
        m = RunManifest(issue_number=42, timestamp="20260101T000000Z")
        assert m.outcome == ""
        assert m.error is None
        assert m.duration_seconds == 0.0
        assert m.files == []

    def test_roundtrip_json(self) -> None:
        m = RunManifest(
            issue_number=42,
            timestamp="20260101T000000Z",
            outcome="success",
            duration_seconds=12.3,
            files=["manifest.json", "plan.md"],
        )
        restored = RunManifest.model_validate_json(m.model_dump_json())
        assert restored == m


# ---------------------------------------------------------------------------
# RunManifest.outcome Literal validation (issue #1048)
# ---------------------------------------------------------------------------


class TestRunManifestOutcome:
    """Tests for RunManifest.outcome Literal constraint."""

    @pytest.mark.parametrize("outcome", ["success", "failed", "stopped", ""])
    def test_valid_outcomes_accepted(self, outcome: str) -> None:
        m = RunManifest(issue_number=42, timestamp="20260101T000000Z", outcome=outcome)
        assert m.outcome == outcome

    def test_invalid_outcome_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RunManifest(
                issue_number=42, timestamp="20260101T000000Z", outcome="cancelled"
            )

    def test_invalid_outcome_partial_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            RunManifest(
                issue_number=42, timestamp="20260101T000000Z", outcome="partial"
            )
