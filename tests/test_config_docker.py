"""Tests for dx/hydraflow/config.py — Docker config."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

# conftest.py already inserts the hydraflow package directory into sys.path
from config import HydraFlowConfig


class GitIdentityEnvMixin:
    """Utility mixin for clearing git identity env vars across tests."""

    @staticmethod
    def _clear_git_identity_env(monkeypatch: pytest.MonkeyPatch) -> None:
        for var in (
            "HYDRAFLOW_GIT_USER_NAME",
            "HYDRAFLOW_GIT_USER_EMAIL",
            "GIT_AUTHOR_NAME",
            "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL",
        ):
            monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Docker config – defaults
# ---------------------------------------------------------------------------


class TestDockerConfigDefaults:
    """Tests that Docker config fields have correct default values."""

    def test_execution_mode_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "host"

    def test_docker_image_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_image == "ghcr.io/t-rav/hydraflow-agent:latest"

    def test_docker_cpu_limit_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(2.0)

    def test_docker_memory_limit_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "4g"

    def test_docker_pids_limit_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_pids_limit == 256

    def test_docker_tmp_size_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_tmp_size == "1g"

    def test_docker_network_mode_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_network_mode == "bridge"

    def test_docker_spawn_delay_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(2.0)

    def test_docker_read_only_root_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_read_only_root is True

    def test_docker_no_new_privileges_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_no_new_privileges is True


# ---------------------------------------------------------------------------
# Docker config – custom values override defaults
# ---------------------------------------------------------------------------


class TestDockerConfigCustomValues:
    """Tests that custom Docker config values take precedence over defaults."""

    def test_custom_execution_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        cfg = HydraFlowConfig(
            execution_mode="docker",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "docker"

    def test_custom_docker_image(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_image="my-registry/my-image:v1",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_image == "my-registry/my-image:v1"

    def test_custom_docker_cpu_limit(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_cpu_limit=4.0,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(4.0)

    def test_custom_docker_memory_limit(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_memory_limit="8g",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "8g"

    def test_custom_docker_network_mode(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_network_mode="none",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_network_mode == "none"

    def test_custom_docker_spawn_delay(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_spawn_delay=5.0,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(5.0)

    def test_custom_docker_read_only_root_false(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_read_only_root=False,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_read_only_root is False

    def test_custom_docker_no_new_privileges_false(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_no_new_privileges=False,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_no_new_privileges is False


# ---------------------------------------------------------------------------
# Docker config – validation constraints
# ---------------------------------------------------------------------------


class TestDockerConfigValidation(GitIdentityEnvMixin):
    """Tests for Docker config validation constraints."""

    def test_invalid_execution_mode_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                execution_mode="kubernetes",
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_invalid_docker_network_mode_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_network_mode="overlay",
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_cpu_limit_below_minimum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_cpu_limit=0.1,
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_cpu_limit_above_maximum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_cpu_limit=32.0,
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_cpu_limit_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_cpu_limit=0.5,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(0.5)

    def test_docker_cpu_limit_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_cpu_limit=16.0,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(16.0)

    def test_docker_spawn_delay_below_minimum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_spawn_delay=-1.0,
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_spawn_delay_above_maximum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_spawn_delay=60.0,
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_spawn_delay_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_spawn_delay=0.0,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(0.0)

    def test_docker_spawn_delay_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_spawn_delay=30.0,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(30.0)

    def test_docker_pids_limit_below_minimum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_pids_limit=15,
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_pids_limit_above_maximum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_pids_limit=4097,
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_pids_limit_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_pids_limit=16,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_pids_limit == 16

    def test_docker_pids_limit_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_pids_limit=4096,
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_pids_limit == 4096

    def test_docker_memory_limit_invalid_suffix_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="4gb",
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_memory_limit_invalid_text_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="lots",
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_tmp_size_invalid_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_tmp_size="big",
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_not_available_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: None)
        with pytest.raises(ValueError, match="docker.*not found on PATH"):
            HydraFlowConfig(
                execution_mode="docker",
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_available_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        cfg = HydraFlowConfig(
            execution_mode="docker",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "docker"

    def test_host_mode_skips_docker_check(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            execution_mode="host",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "host"

    def test_docker_mode_warns_when_identity_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        monkeypatch.delenv("HYDRAFLOW_GH_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        self._clear_git_identity_env(monkeypatch)
        caplog.clear()
        with caplog.at_level("WARNING", logger="hydraflow.config"):
            HydraFlowConfig(
                execution_mode="docker",
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )
        warnings = "\n".join(rec.getMessage() for rec in caplog.records)
        # gh_token warning removed — credentials are no longer on HydraFlowConfig
        assert "git identity not configured" in warnings

    def test_docker_mode_warns_on_partial_git_identity(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        self._clear_git_identity_env(monkeypatch)
        caplog.clear()
        with caplog.at_level("WARNING", logger="hydraflow.config"):
            HydraFlowConfig(
                execution_mode="docker",
                gh_token="ghp_bot",
                git_user_name="Bot Name",
                git_user_email="",
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )
        warnings = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "git identity is incomplete" in warnings


# ---------------------------------------------------------------------------
# Docker size notation validator
# ---------------------------------------------------------------------------


class TestDockerSizeNotationValidator:
    """Tests for the validate_docker_size_notation field validator."""

    def test_valid_size_512m(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_memory_limit="512m",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "512m"

    def test_valid_size_1024k(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_memory_limit="1024k",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "1024k"

    def test_valid_size_100b(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_memory_limit="100b",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "100b"

    def test_valid_size_uppercase_4G(self, tmp_path: Path) -> None:
        """Validator uses re.IGNORECASE — uppercase units should be accepted."""
        cfg = HydraFlowConfig(
            docker_memory_limit="4G",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "4G"

    def test_valid_size_uppercase_512M(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_memory_limit="512M",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "512M"

    def test_valid_docker_tmp_size(self, tmp_path: Path) -> None:
        """Validator applies to docker_tmp_size as well."""
        cfg = HydraFlowConfig(
            docker_tmp_size="512m",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_tmp_size == "512m"

    def test_invalid_empty_string(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="",
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_invalid_digits_only(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="4",
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_invalid_unit_only(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="g",
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_valid_size_4g(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_memory_limit="4g",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "4g"

    def test_invalid_size_with_suffix_gb(self, tmp_path: Path) -> None:
        """'4gb' should fail — only single-char unit suffix is valid."""
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="4gb",
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_invalid_size_alpha_only(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="abc",
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )


# ---------------------------------------------------------------------------
# Docker config – env var overrides
# ---------------------------------------------------------------------------


class TestDockerConfigEnvVarOverrides:
    """Tests for Docker-specific env var overrides."""

    def test_execution_mode_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        monkeypatch.setenv("HYDRAFLOW_EXECUTION_MODE", "docker")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "docker"

    def test_docker_image_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_IMAGE", "custom/image:v2")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_image == "custom/image:v2"

    def test_docker_memory_limit_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_MEMORY_LIMIT", "16g")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "16g"

    def test_docker_network_mode_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_NETWORK_MODE", "none")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_network_mode == "none"

    def test_docker_cpu_limit_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_CPU_LIMIT", "8.0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(8.0)

    def test_docker_spawn_delay_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_SPAWN_DELAY", "5.0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(5.0)

    def test_docker_read_only_root_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_READ_ONLY_ROOT", "false")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_read_only_root is False

    def test_docker_no_new_privileges_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_NO_NEW_PRIVILEGES", "0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_no_new_privileges is False

    def test_execution_mode_docker_via_env_raises_when_docker_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: None)
        monkeypatch.setenv("HYDRAFLOW_EXECUTION_MODE", "docker")
        with pytest.raises(ValueError, match="docker.*not found on PATH"):
            HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_cpu_limit_env_override_out_of_range_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_CPU_LIMIT", "50.0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(2.0)

    def test_docker_spawn_delay_env_override_out_of_range_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_SPAWN_DELAY", "999.0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(2.0)

    def test_pids_limit_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_PIDS_LIMIT", "512")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_pids_limit == 512

    def test_pids_limit_env_override_below_minimum_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_PIDS_LIMIT", "15")
        with pytest.raises(ValueError, match="HYDRAFLOW_DOCKER_PIDS_LIMIT"):
            HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_pids_limit_env_override_above_maximum_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_PIDS_LIMIT", "4097")
        with pytest.raises(ValueError, match="HYDRAFLOW_DOCKER_PIDS_LIMIT"):
            HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_pids_limit_env_override_invalid_value_logs_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_PIDS_LIMIT", "not-an-int")
        with caplog.at_level(logging.WARNING):
            cfg = HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )
        assert cfg.docker_pids_limit == 256
        assert "HYDRAFLOW_DOCKER_PIDS_LIMIT value" in caplog.text

    def test_tmp_size_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_TMP_SIZE", "2g")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_tmp_size == "2g"

    def test_memory_limit_env_override_invalid_value_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_MEMORY_LIMIT", "invalid_val")
        with pytest.raises(ValueError, match="Invalid HYDRAFLOW_DOCKER_MEMORY_LIMIT"):
            HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_tmp_size_env_override_invalid_value_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_TMP_SIZE", "4gb")
        with pytest.raises(ValueError, match="Invalid HYDRAFLOW_DOCKER_TMP_SIZE"):
            HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_execution_mode_default_value_overridden_by_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When execution_mode equals the default ('host'), env var overrides it."""
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        monkeypatch.setenv("HYDRAFLOW_EXECUTION_MODE", "docker")
        cfg = HydraFlowConfig(
            execution_mode="host",
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "docker"


# ---------------------------------------------------------------------------
# Docker config fields
# ---------------------------------------------------------------------------


class TestDockerConfig:
    """Tests for Docker-related configuration fields."""

    def test_docker_image_has_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_image == "ghcr.io/t-rav/hydraflow-agent:latest"

    def test_docker_spawn_delay_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == 2.0

    def test_docker_network_empty_by_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_network == ""

    def test_docker_extra_mounts_empty_by_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_extra_mounts == []

    def test_docker_spawn_delay_invalid_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_SPAWN_DELAY", "not-a-number")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == 2.0

    def test_docker_network_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_NETWORK", "hydra-net")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_network == "hydra-net"

    def test_docker_network_env_var_not_applied_when_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_NETWORK", "from-env")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            docker_network="explicit-net",
        )
        assert cfg.docker_network == "explicit-net"

    def test_docker_custom_values(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            docker_image="hydra-agent:latest",
            docker_spawn_delay=3.5,
            docker_network="my-network",
            docker_extra_mounts=["/host:/container:rw"],
        )
        assert cfg.docker_image == "hydra-agent:latest"
        assert cfg.docker_spawn_delay == 3.5
        assert cfg.docker_network == "my-network"
        assert cfg.docker_extra_mounts == ["/host:/container:rw"]

    def test_docker_spawn_delay_too_low(self, tmp_path: Path) -> None:
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                docker_spawn_delay=-1.0,
            )

    def test_docker_spawn_delay_too_high(self, tmp_path: Path) -> None:
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            HydraFlowConfig(
                repo_root=tmp_path,
                workspace_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                docker_spawn_delay=31.0,
            )
