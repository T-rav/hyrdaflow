"""Tests for runtime_config load helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import HydraFlowConfig
from runtime_config import apply_repo_config_overlay, load_runtime_config


class TestLoadRuntimeConfig:
    def test_config_file_values_applied(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"max_workers": 7, "model": "opus"}))
        monkeypatch.setenv("HYDRAFLOW_CONFIG_FILE", str(config_path))

        cfg = load_runtime_config()

        assert cfg.max_workers == 7
        assert cfg.model == "opus"
        assert cfg.config_file == config_path

    def test_missing_config_file_uses_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_CONFIG_FILE", str(tmp_path / "missing.json"))
        cfg = load_runtime_config()
        assert cfg.max_workers == HydraFlowConfig().max_workers

    def test_overrides_take_priority(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"max_workers": 3, "model": "opus"}))
        cfg = load_runtime_config(config_file=config_path, overrides={"max_workers": 9})
        assert cfg.max_workers == 9
        assert cfg.model == "opus"


class TestApplyRepoConfigOverlay:
    def test_repo_config_overrides_shared_values(self, tmp_path: Path) -> None:
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        data_root = repo_root / ".hydraflow"
        data_root.mkdir()
        repo_cfg = data_root / "repo-name" / "config.json"
        repo_cfg.parent.mkdir(parents=True, exist_ok=True)
        repo_cfg.write_text(json.dumps({"batch_size": 42}))

        cfg = HydraFlowConfig(
            repo_root=repo_root,
            data_root=data_root,
            repo="owner/repo-name",
            config_file=repo_cfg,
            batch_size=20,
        )

        apply_repo_config_overlay(cfg, cli_explicit=set())

        assert cfg.batch_size == 42

    def test_cli_explicit_values_are_preserved(self, tmp_path: Path) -> None:
        repo_cfg = tmp_path / "repo-config.json"
        repo_cfg.write_text(json.dumps({"batch_size": 50}))
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            data_root=tmp_path,
            repo="owner/example",
            config_file=repo_cfg,
            batch_size=10,
        )
        apply_repo_config_overlay(cfg, cli_explicit={"batch_size"})
        assert cfg.batch_size == 10
