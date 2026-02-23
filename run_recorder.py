"""Per-issue run recording for replay and debugging."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from config import HydraFlowConfig

logger = logging.getLogger("hydra.run_recorder")


class RunManifest(BaseModel):
    """Metadata for a single recorded run."""

    issue_number: int
    timestamp: str
    outcome: str = ""
    error: str | None = None
    duration_seconds: float = 0.0
    files: list[str] = Field(default_factory=list)


class RunContext:
    """Active recording session for a single issue run.

    Created by :meth:`RunRecorder.start`, captures plan text,
    config snapshot, transcript lines, and git diff. Call
    :meth:`finalize` when the run completes or fails.
    """

    def __init__(self, run_dir: Path, issue_number: int, timestamp: str) -> None:
        self._run_dir = run_dir
        self._issue_number = issue_number
        self._timestamp = timestamp
        self._transcript_lines: list[str] = []
        self._start_time = time.monotonic()

    @property
    def run_dir(self) -> Path:
        """Return the directory where run artifacts are stored."""
        return self._run_dir

    def save_plan(self, plan_text: str) -> None:
        """Write the plan text used for this implementation run."""
        (self._run_dir / "plan.md").write_text(plan_text)

    def save_config(self, config_data: dict[str, Any]) -> None:
        """Write a config snapshot for this run."""
        (self._run_dir / "config.json").write_text(
            json.dumps(config_data, indent=2, default=str)
        )

    def append_transcript(self, line: str) -> None:
        """Buffer a transcript line for later writing."""
        self._transcript_lines.append(line)

    def save_diff(self, diff_text: str) -> None:
        """Write the git diff produced by this run."""
        (self._run_dir / "diff.patch").write_text(diff_text)

    def finalize(self, outcome: str, error: str | None = None) -> RunManifest:
        """Write transcript, manifest, and return the manifest.

        *outcome* should be ``"success"``, ``"failed"``, or ``"stopped"``.
        """
        elapsed = time.monotonic() - self._start_time

        # Write transcript
        transcript_path = self._run_dir / "transcript.log"
        transcript_path.write_text("\n".join(self._transcript_lines))

        # Collect file names
        artifact_files = sorted(f.name for f in self._run_dir.iterdir() if f.is_file())

        manifest = RunManifest(
            issue_number=self._issue_number,
            timestamp=self._timestamp,
            outcome=outcome,
            error=error,
            duration_seconds=round(elapsed, 1),
            files=artifact_files,
        )

        # Write manifest (after collecting files so it includes itself)
        manifest_path = self._run_dir / "manifest.json"
        manifest_path.write_text(manifest.model_dump_json(indent=2))

        # Re-collect to include manifest.json
        manifest.files = sorted(f.name for f in self._run_dir.iterdir() if f.is_file())
        manifest_path.write_text(manifest.model_dump_json(indent=2))

        return manifest


class RunRecorder:
    """Records per-issue run artifacts under ``.hydra/runs/``."""

    def __init__(self, config: HydraFlowConfig) -> None:
        self._runs_dir = config.repo_root / ".hydra" / "runs"

    @property
    def runs_dir(self) -> Path:
        """Base directory for all run recordings."""
        return self._runs_dir

    def start(self, issue_number: int) -> RunContext:
        """Begin recording a run for *issue_number*.

        Creates a timestamped directory under
        ``.hydra/runs/{issue_number}/{timestamp}/``.
        """
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_dir = self._runs_dir / str(issue_number) / timestamp
        run_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Started recording run for issue #%d at %s",
            issue_number,
            run_dir,
        )
        return RunContext(run_dir, issue_number, timestamp)

    def list_runs(self, issue_number: int) -> list[RunManifest]:
        """Return all recorded runs for *issue_number*, oldest first."""
        issue_dir = self._runs_dir / str(issue_number)
        if not issue_dir.is_dir():
            return []

        manifests: list[RunManifest] = []
        for run_dir in sorted(issue_dir.iterdir()):
            manifest_path = run_dir / "manifest.json"
            if manifest_path.is_file():
                try:
                    manifests.append(
                        RunManifest.model_validate_json(manifest_path.read_text())
                    )
                except Exception:
                    logger.debug(
                        "Skipping corrupt manifest in %s", run_dir, exc_info=True
                    )
        return manifests

    def get_latest(self, issue_number: int) -> RunManifest | None:
        """Return the most recent run for *issue_number*, or None."""
        runs = self.list_runs(issue_number)
        return runs[-1] if runs else None

    def get_run_artifact(
        self, issue_number: int, timestamp: str, filename: str
    ) -> str | None:
        """Read a specific artifact file from a recorded run."""
        artifact_path = self._runs_dir / str(issue_number) / timestamp / filename
        if not artifact_path.is_file():
            return None
        try:
            return artifact_path.read_text()
        except OSError:
            return None

    def list_issues(self) -> list[int]:
        """Return issue numbers that have recorded runs."""
        if not self._runs_dir.is_dir():
            return []
        issues: list[int] = []
        for d in sorted(self._runs_dir.iterdir()):
            if d.is_dir() and d.name.isdigit():
                issues.append(int(d.name))
        return issues
