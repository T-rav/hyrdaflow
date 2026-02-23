"""Tests for config file persistence — loading, saving, and merge priority."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import HydraFlowConfig, load_config_file, save_config_file

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
            "max_budget_usd": 5.0,
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

        assert cfg.max_workers == 3  # Default
        assert cfg.model == "opus"  # Default

    def test_config_file_with_float_field(self, tmp_path: Path) -> None:
        """Float fields from config file should be preserved."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"max_budget_usd": 5.0}))

        file_values = load_config_file(config_path)
        cfg = HydraFlowConfig(
            **file_values,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )

        assert cfg.max_budget_usd == pytest.approx(5.0)
