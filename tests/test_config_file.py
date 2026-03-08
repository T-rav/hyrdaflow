"""Tests for config file persistence — loading, saving, and merge priority."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from config import HydraFlowConfig, load_config_file, save_config_file

# All worker count fields that must round-trip through save/load
_ALL_WORKER_FIELDS = {
    "max_workers": 3,
    "max_planners": 4,
    "max_reviewers": 5,
    "max_triagers": 2,
    "max_hitl_workers": 2,
}

# ---------------------------------------------------------------------------
# load_config_file
# ---------------------------------------------------------------------------


class TestLoadConfigFile:
    """Tests for the load_config_file() helper."""

    def test_returns_empty_dict_when_file_missing(self, tmp_path: Path) -> None:
        """Missing config file should silently return empty dict."""
        result = load_config_file(tmp_path / "nonexistent.json")
        assert result == {}

    def test_returns_empty_dict_when_path_is_none(self) -> None:
        """None path should return empty dict."""
        result = load_config_file(None)
        assert result == {}

    def test_loads_valid_json_file(self, tmp_path: Path) -> None:
        """Should parse a valid JSON config file."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"max_workers": 5, "model": "opus"}))

        result = load_config_file(config_path)

        assert result == {"max_workers": 5, "model": "opus"}

    def test_returns_empty_dict_on_invalid_json(self, tmp_path: Path) -> None:
        """Invalid JSON should be silently ignored."""
        config_path = tmp_path / "config.json"
        config_path.write_text("not valid json {{{")

        result = load_config_file(config_path)

        assert result == {}

    def test_returns_empty_dict_on_non_dict_json(self, tmp_path: Path) -> None:
        """JSON that parses to a non-dict (e.g. a list) should return empty dict."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps([1, 2, 3]))

        result = load_config_file(config_path)

        assert result == {}

    def test_loads_all_supported_fields(self, tmp_path: Path) -> None:
        """Should load various config fields from JSON."""
        config_path = tmp_path / "config.json"
        data = {
            "max_workers": 4,
            "model": "opus",
            "batch_size": 10,
            "max_planners": 2,
            "review_model": "sonnet",
        }
        config_path.write_text(json.dumps(data))

        result = load_config_file(config_path)

        assert result == data


# ---------------------------------------------------------------------------
# save_config_file
# ---------------------------------------------------------------------------


class TestSaveConfigFile:
    """Tests for the save_config_file() helper."""

    def test_writes_json_to_file(self, tmp_path: Path) -> None:
        """Should write a JSON config file."""
        config_path = tmp_path / ".hydraflow" / "config.json"

        save_config_file(config_path, {"max_workers": 4, "model": "opus"})

        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert data == {"max_workers": 4, "model": "opus"}

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories if they don't exist."""
        config_path = tmp_path / "deep" / "nested" / "config.json"

        save_config_file(config_path, {"model": "haiku"})

        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert data == {"model": "haiku"}

    def test_merges_with_existing_file(self, tmp_path: Path) -> None:
        """Should merge new values into existing config file."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"max_workers": 3, "model": "sonnet"}))

        save_config_file(config_path, {"max_workers": 5})

        data = json.loads(config_path.read_text())
        assert data == {"max_workers": 5, "model": "sonnet"}

    def test_overwrites_existing_keys(self, tmp_path: Path) -> None:
        """Should overwrite existing keys with new values."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"model": "sonnet"}))

        save_config_file(config_path, {"model": "opus"})

        data = json.loads(config_path.read_text())
        assert data == {"model": "opus"}

    def test_does_nothing_when_path_is_none(self) -> None:
        """Should not raise when path is None."""
        result = save_config_file(None, {"model": "opus"})
        assert result is None

    def test_writes_human_readable_json(self, tmp_path: Path) -> None:
        """Config file should be formatted with indentation for readability."""
        config_path = tmp_path / "config.json"

        save_config_file(config_path, {"max_workers": 4})

        content = config_path.read_text()
        # Should be indented (not a single line)
        assert "\n" in content


# ---------------------------------------------------------------------------
# Config file integration with HydraFlowConfig
# ---------------------------------------------------------------------------


class TestConfigFileMergePriority:
    """Tests that config file values are merged correctly with other sources."""

    def test_config_file_overrides_defaults(self, tmp_path: Path) -> None:
        """Config file values should override HydraFlowConfig defaults."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"max_workers": 7, "model": "opus"}))

        file_values = load_config_file(config_path)
        cfg = HydraFlowConfig(
            **file_values,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )

        assert cfg.max_workers == 7
        assert cfg.model == "opus"

    def test_explicit_values_override_config_file(self, tmp_path: Path) -> None:
        """Explicitly passed values should override config file values."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"max_workers": 7, "model": "opus"}))

        file_values = load_config_file(config_path)
        # Explicit value for max_workers should win
        file_values["max_workers"] = 2
        cfg = HydraFlowConfig(
            **file_values,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )

        assert cfg.max_workers == 2
        assert cfg.model == "opus"  # From config file

    def test_empty_config_file_uses_defaults(self, tmp_path: Path) -> None:
        """Empty config file should result in all defaults."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))

        file_values = load_config_file(config_path)
        cfg = HydraFlowConfig(
            **file_values,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )

        assert cfg.max_workers == 1  # Default
        assert cfg.model == "opus"  # Default

    def test_config_file_with_float_field(self, tmp_path: Path) -> None:
        """Float fields from config file should be preserved."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"docker_cpu_limit": 5.0}))

        file_values = load_config_file(config_path)
        cfg = HydraFlowConfig(
            **file_values,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )

        assert cfg.docker_cpu_limit == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Round-trip persistence for ALL worker count fields
# ---------------------------------------------------------------------------


class TestWorkerCountRoundTrip:
    """Regression tests ensuring all worker count fields survive save → load."""

    def test_all_worker_counts_round_trip(self, tmp_path: Path) -> None:
        """Every worker count field should survive a save → load cycle."""
        config_path = tmp_path / "config.json"

        save_config_file(config_path, _ALL_WORKER_FIELDS)
        loaded = load_config_file(config_path)

        for field, expected in _ALL_WORKER_FIELDS.items():
            assert loaded[field] == expected, f"{field} lost during round-trip"

    def test_max_reviewers_persists_after_incremental_save(
        self, tmp_path: Path
    ) -> None:
        """max_reviewers should not be lost when another field is saved later."""
        config_path = tmp_path / "config.json"

        # First save: set reviewers
        save_config_file(config_path, {"max_reviewers": 5})
        # Second save: update a different field
        save_config_file(config_path, {"max_workers": 3})

        loaded = load_config_file(config_path)
        assert loaded["max_reviewers"] == 5
        assert loaded["max_workers"] == 3

    def test_all_worker_counts_applied_to_config_model(self, tmp_path: Path) -> None:
        """Worker counts from config file should be applied to HydraFlowConfig."""
        config_path = tmp_path / "config.json"
        save_config_file(config_path, _ALL_WORKER_FIELDS)

        file_values = load_config_file(config_path)
        cfg = HydraFlowConfig(
            **file_values,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )

        assert cfg.max_workers == 3
        assert cfg.max_planners == 4
        assert cfg.max_reviewers == 5
        assert cfg.max_triagers == 2
        assert cfg.max_hitl_workers == 2


# ---------------------------------------------------------------------------
# Atomic write and logging in save_config_file
# ---------------------------------------------------------------------------


class TestSaveConfigFileAtomicAndLogging:
    """Tests for atomic write behaviour and logging in save_config_file."""

    def test_save_uses_atomic_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """save_config_file should use atomic_write instead of direct write."""
        config_path = tmp_path / "config.json"
        calls: list[tuple[Path, str]] = []

        def fake_atomic_write(path: Path, data: str) -> None:
            calls.append((path, data))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data)

        import file_util  # noqa: PLC0415

        monkeypatch.setattr(file_util, "atomic_write", fake_atomic_write)

        save_config_file(config_path, {"max_reviewers": 3})

        assert len(calls) == 1
        assert calls[0][0] == config_path
        data = json.loads(calls[0][1])
        assert data["max_reviewers"] == 3

    def test_logs_warning_on_corrupt_json(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Corrupt JSON in config file should log a warning and start fresh."""
        config_path = tmp_path / "config.json"
        config_path.write_text("not-valid-json")

        with caplog.at_level(logging.WARNING, logger="hydraflow.config"):
            save_config_file(config_path, {"max_reviewers": 3})

        assert any("Failed to read" in r.message for r in caplog.records)
        loaded = load_config_file(config_path)
        assert loaded["max_reviewers"] == 3
