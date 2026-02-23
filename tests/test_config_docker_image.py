"""Tests for docker_image config field in HydraFlowConfig — unique cases only.

Default, custom value, and basic env-var-override cases are already covered
in tests/test_config.py (TestDockerConfigDefaults / TestDockerConfigEnvOverrides).
Only the cases unique to this behaviour are kept here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import HydraFlowConfig

DEFAULT_DOCKER_IMAGE = "ghcr.io/t-rav/hydraflow-agent:latest"


# ---------------------------------------------------------------------------
# HydraFlowConfig – docker_image field (unique edge cases)
# ---------------------------------------------------------------------------


class TestDockerImageConfig:
    """Unique edge cases for the docker_image env-var override logic."""

    def test_docker_image_explicit_not_overridden_by_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit docker_image should NOT be overridden by env var."""
        monkeypatch.setenv("HYDRAFLOW_DOCKER_IMAGE", "env/override:latest")
        cfg = HydraFlowConfig(
            docker_image="explicit/image:v1",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_image == "explicit/image:v1"

    def test_docker_image_env_var_not_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without env var, default should be used."""
        monkeypatch.delenv("HYDRAFLOW_DOCKER_IMAGE", raising=False)
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_image == DEFAULT_DOCKER_IMAGE
