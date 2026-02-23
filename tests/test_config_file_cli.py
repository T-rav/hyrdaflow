"""Tests for --config-file CLI arg and build_config integration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cli import build_config, parse_args

# ---------------------------------------------------------------------------
# parse_args — --config-file
# ---------------------------------------------------------------------------


class TestParseArgsConfigFile:
    """Tests for the --config-file CLI argument."""

    def test_config_file_defaults_to_none(self) -> None:
        """--config-file should default to None when not provided."""
        args = parse_args([])
        assert args.config_file is None

    def test_config_file_explicit_value(self) -> None:
        """--config-file should accept an explicit path."""
        args = parse_args(["--config-file", "/tmp/my-config.json"])
        assert args.config_file == "/tmp/my-config.json"


# ---------------------------------------------------------------------------
# build_config — config file integration
# ---------------------------------------------------------------------------


class TestBuildConfigWithConfigFile:
    """Tests for build_config() loading a config file."""

    def test_config_file_values_applied(self, tmp_path: Path) -> None:
        """Config file values should be applied to the resulting HydraFlowConfig."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"max_workers": 7, "model": "opus"}))

        args = parse_args(["--config-file", str(config_path)])
        cfg = build_config(args)

        assert cfg.max_workers == 7
        assert cfg.model == "opus"

    def test_cli_args_override_config_file(self, tmp_path: Path) -> None:
        """CLI args should take precedence over config file values."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"max_workers": 7, "model": "opus"}))

        args = parse_args(["--config-file", str(config_path), "--max-workers", "2"])
        cfg = build_config(args)

        assert cfg.max_workers == 2  # CLI wins
        assert cfg.model == "opus"  # From config file

    def test_missing_config_file_silently_ignored(self, tmp_path: Path) -> None:
        """A non-existent config file path should be silently ignored."""
        args = parse_args(["--config-file", str(tmp_path / "nonexistent.json")])
        cfg = build_config(args)

        # Should use defaults
        assert cfg.max_workers == 3
        assert cfg.model == "opus"

    def test_no_config_file_uses_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without --config-file, build_config should use HydraFlowConfig defaults."""
        # Use tmp_path as CWD to avoid picking up a local .hydraflow/config.json
        monkeypatch.chdir(tmp_path)
        args = parse_args([])
        cfg = build_config(args)

        assert cfg.max_workers == 3
        assert cfg.model == "opus"

    def test_config_file_with_multiple_fields(self, tmp_path: Path) -> None:
        """Config file should support multiple fields."""
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "max_workers": 5,
                    "max_planners": 3,
                    "model": "haiku",
                    "max_budget_usd": 10.0,
                    "batch_size": 20,
                }
            )
        )

        args = parse_args(["--config-file", str(config_path)])
        cfg = build_config(args)

        assert cfg.max_workers == 5
        assert cfg.max_planners == 3
        assert cfg.model == "haiku"
        assert cfg.max_budget_usd == pytest.approx(10.0)
        assert cfg.batch_size == 20

    def test_config_file_stores_path_on_config(self, tmp_path: Path) -> None:
        """The config_file path should be stored on the resulting HydraFlowConfig."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({}))

        args = parse_args(["--config-file", str(config_path)])
        cfg = build_config(args)

        assert cfg.config_file == config_path

    def test_config_file_unknown_fields_ignored(self, tmp_path: Path) -> None:
        """Unknown fields in the config file should be ignored, not cause errors."""
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps({"max_workers": 5, "unknown_field": "should_be_ignored"})
        )

        args = parse_args(["--config-file", str(config_path)])
        cfg = build_config(args)

        assert cfg.max_workers == 5
