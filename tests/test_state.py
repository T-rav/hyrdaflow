"""Tests for state backup and restore functionality."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from models import StateData
from state import StateTracker

# ---------------------------------------------------------------------------
# StateData.schema_version
# ---------------------------------------------------------------------------


class TestSchemaVersion:
    def test_default_schema_version(self) -> None:
        data = StateData()
        assert data.schema_version == 1

    def test_schema_version_roundtrips(self) -> None:
        data = StateData(schema_version=1)
        raw = json.loads(data.model_dump_json())
        assert raw["schema_version"] == 1

    def test_old_state_without_schema_version_gets_default(self) -> None:
        raw = {"processed_issues": {"1": "success"}}
        data = StateData.model_validate(raw)
        assert data.schema_version == 1


# ---------------------------------------------------------------------------
# StateTracker.backup()
# ---------------------------------------------------------------------------


class TestStateBackup:
    def test_backup_creates_bak_file(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_issue(1, "success")
        tracker.backup()
        bak = Path(f"{state_file}.bak")
        assert bak.exists()
        assert json.loads(bak.read_text())["processed_issues"]["1"] == "success"

    def test_backup_rotates_existing_bak(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_issue(1, "success")
        tracker.backup()
        tracker.mark_issue(2, "success")
        tracker.backup()
        bak0 = Path(f"{state_file}.bak")
        bak1 = Path(f"{state_file}.bak.1")
        assert bak0.exists()
        assert bak1.exists()
        # .bak should have the newer data
        assert "2" in json.loads(bak0.read_text())["processed_issues"]
        # .bak.1 should have the older data
        assert "1" in json.loads(bak1.read_text())["processed_issues"]
        assert "2" not in json.loads(bak1.read_text())["processed_issues"]

    def test_backup_resets_timer(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file)
        tracker.mark_issue(1, "success")
        before = tracker._last_backup
        tracker.backup()
        assert tracker._last_backup >= before


# ---------------------------------------------------------------------------
# StateTracker.save() auto-backup
# ---------------------------------------------------------------------------


class TestSaveAutoBackup:
    def test_save_triggers_backup_after_interval(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file, backup_interval=10)
        tracker.mark_issue(1, "success")
        # Simulate time passing beyond the interval
        tracker._last_backup = time.monotonic() - 20
        tracker.save()
        assert Path(f"{state_file}.bak").exists()

    def test_save_skips_backup_within_interval(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file, backup_interval=9999)
        tracker.mark_issue(1, "success")
        tracker.save()
        assert not Path(f"{state_file}.bak").exists()

    def test_backup_count_configurable(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        tracker = StateTracker(state_file, backup_interval=0, backup_count=2)
        for i in range(5):
            tracker.mark_issue(i, "success")
            tracker.save()
        # Should have .bak and .bak.1 and .bak.2 (count=2)
        assert Path(f"{state_file}.bak").exists()
        assert Path(f"{state_file}.bak.1").exists()
        assert Path(f"{state_file}.bak.2").exists()


# ---------------------------------------------------------------------------
# StateTracker.load() restore from backup
# ---------------------------------------------------------------------------


class TestLoadRestoreFromBackup:
    def test_load_restores_from_bak_when_primary_corrupt(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        # Create a valid backup
        good_data = StateData(processed_issues={"1": "success"})
        bak = Path(f"{state_file}.bak")
        bak.write_text(good_data.model_dump_json())
        # Write corrupt primary
        state_file.write_text("{{{CORRUPT")
        tracker = StateTracker(state_file)
        assert tracker._data.processed_issues.get("1") == "success"

    def test_load_tries_bak_1_when_bak_also_corrupt(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text("{{{CORRUPT")
        Path(f"{state_file}.bak").write_text("{{{ALSO CORRUPT")
        good_data = StateData(processed_issues={"42": "restored"})
        Path(f"{state_file}.bak.1").write_text(good_data.model_dump_json())
        tracker = StateTracker(state_file)
        assert tracker._data.processed_issues.get("42") == "restored"

    def test_load_falls_back_to_empty_when_all_backups_corrupt(
        self, tmp_path: Path
    ) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text("{{{CORRUPT")
        Path(f"{state_file}.bak").write_text("{{{ALSO CORRUPT")
        Path(f"{state_file}.bak.1").write_text("{{{STILL CORRUPT")
        tracker = StateTracker(state_file)
        assert tracker._data.processed_issues == {}

    def test_load_skips_missing_backups(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state_file.write_text("{{{CORRUPT")
        # No backup files exist at all
        tracker = StateTracker(state_file)
        assert tracker._data.processed_issues == {}

    def test_load_normal_file_does_not_touch_backups(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        good_data = StateData(processed_issues={"1": "success"})
        state_file.write_text(good_data.model_dump_json())
        with patch("state.rotate_backups") as mock_rotate:
            tracker = StateTracker(state_file)
            mock_rotate.assert_not_called()
        assert tracker._data.processed_issues.get("1") == "success"
