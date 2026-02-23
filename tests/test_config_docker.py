"""Tests for config.py — Docker configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from config import HydraFlowConfig

# ---------------------------------------------------------------------------
# Docker config – defaults
# ---------------------------------------------------------------------------


class TestDockerConfigDefaults:
    """Tests that Docker config fields have correct default values."""

    def test_execution_mode_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "host"

    def test_docker_image_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_image == "ghcr.io/t-rav/hydraflow-agent:latest"

    def test_docker_cpu_limit_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(2.0)

    def test_docker_memory_limit_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "4g"

    def test_docker_pids_limit_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_pids_limit == 256

    def test_docker_tmp_size_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_tmp_size == "1g"

    def test_docker_network_mode_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_network_mode == "bridge"

    def test_docker_spawn_delay_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(2.0)

    def test_docker_read_only_root_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_read_only_root is True

    def test_docker_no_new_privileges_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
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
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "docker"

    def test_custom_docker_image(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_image="my-registry/my-image:v1",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_image == "my-registry/my-image:v1"

    def test_custom_docker_cpu_limit(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_cpu_limit=4.0,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(4.0)

    def test_custom_docker_memory_limit(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_memory_limit="8g",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "8g"

    def test_custom_docker_network_mode(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_network_mode="none",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_network_mode == "none"

    def test_custom_docker_spawn_delay(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_spawn_delay=5.0,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(5.0)

    def test_custom_docker_read_only_root_false(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_read_only_root=False,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_read_only_root is False

    def test_custom_docker_no_new_privileges_false(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_no_new_privileges=False,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_no_new_privileges is False


# ---------------------------------------------------------------------------
# Docker config – validation constraints
# ---------------------------------------------------------------------------


class TestDockerConfigValidation:
    """Tests for Docker config validation constraints."""

    def test_invalid_execution_mode_raises(self, tmp_path: Path) -> None:
        """Invalid execution_mode Literal values should raise ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                execution_mode="kubernetes",  # type: ignore[arg-type]
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_invalid_docker_network_mode_raises(self, tmp_path: Path) -> None:
        """Invalid docker_network_mode Literal values should raise ValidationError."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_network_mode="overlay",  # type: ignore[arg-type]
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_cpu_limit_below_minimum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_cpu_limit=0.1,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_cpu_limit_above_maximum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_cpu_limit=32.0,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_cpu_limit_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_cpu_limit=0.5,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(0.5)

    def test_docker_cpu_limit_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_cpu_limit=16.0,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(16.0)

    def test_docker_spawn_delay_below_minimum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_spawn_delay=-1.0,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_spawn_delay_above_maximum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_spawn_delay=60.0,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_spawn_delay_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_spawn_delay=0.0,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(0.0)

    def test_docker_spawn_delay_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_spawn_delay=30.0,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(30.0)

    def test_docker_pids_limit_below_minimum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_pids_limit=15,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_pids_limit_above_maximum_raises(self, tmp_path: Path) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HydraFlowConfig(
                docker_pids_limit=4097,
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_pids_limit_minimum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_pids_limit=16,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_pids_limit == 16

    def test_docker_pids_limit_maximum_boundary(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            docker_pids_limit=4096,
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_pids_limit == 4096

    def test_docker_memory_limit_invalid_suffix_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="4gb",
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_memory_limit_invalid_text_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_memory_limit="lots",
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_tmp_size_invalid_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid Docker size notation"):
            HydraFlowConfig(
                docker_tmp_size="big",
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_not_available_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """execution_mode='docker' with Docker not on PATH should raise ValueError."""
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: None)
        with pytest.raises(ValueError, match="docker.*not found on PATH"):
            HydraFlowConfig(
                execution_mode="docker",
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_available_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """execution_mode='docker' with Docker on PATH should not raise."""
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        cfg = HydraFlowConfig(
            execution_mode="docker",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "docker"

    def test_host_mode_skips_docker_check(self, tmp_path: Path) -> None:
        """execution_mode='host' should not check for Docker availability."""
        cfg = HydraFlowConfig(
            execution_mode="host",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "host"


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
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "docker"

    def test_docker_image_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_IMAGE", "custom/image:v2")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_image == "custom/image:v2"

    def test_docker_memory_limit_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_MEMORY_LIMIT", "16g")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_memory_limit == "16g"

    def test_docker_network_mode_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_NETWORK_MODE", "none")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_network_mode == "none"

    def test_docker_cpu_limit_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_CPU_LIMIT", "8.0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(8.0)

    def test_docker_spawn_delay_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_SPAWN_DELAY", "5.0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(5.0)

    def test_docker_read_only_root_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_READ_ONLY_ROOT", "false")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_read_only_root is False

    def test_docker_no_new_privileges_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_NO_NEW_PRIVILEGES", "0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_no_new_privileges is False

    def test_execution_mode_docker_via_env_raises_when_docker_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_EXECUTION_MODE=docker should trigger docker availability check."""
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: None)
        monkeypatch.setenv("HYDRAFLOW_EXECUTION_MODE", "docker")
        with pytest.raises(ValueError, match="docker.*not found on PATH"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_docker_cpu_limit_env_override_out_of_range_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_DOCKER_CPU_LIMIT outside ge/le bounds should be silently ignored."""
        monkeypatch.setenv("HYDRAFLOW_DOCKER_CPU_LIMIT", "50.0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_cpu_limit == pytest.approx(2.0)  # unchanged default

    def test_docker_spawn_delay_env_override_out_of_range_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_DOCKER_SPAWN_DELAY outside ge/le bounds should be silently ignored."""
        monkeypatch.setenv("HYDRAFLOW_DOCKER_SPAWN_DELAY", "999.0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == pytest.approx(2.0)  # unchanged default

    def test_pids_limit_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_PIDS_LIMIT", "512")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
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
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_pids_limit_env_override_above_maximum_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_PIDS_LIMIT", "4097")
        with pytest.raises(ValueError, match="HYDRAFLOW_DOCKER_PIDS_LIMIT"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_tmp_size_env_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_DOCKER_TMP_SIZE", "2g")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_tmp_size == "2g"

    def test_memory_limit_env_override_invalid_value_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_DOCKER_MEMORY_LIMIT with invalid notation must be rejected."""
        monkeypatch.setenv("HYDRAFLOW_DOCKER_MEMORY_LIMIT", "invalid_val")
        with pytest.raises(ValueError, match="Invalid HYDRAFLOW_DOCKER_MEMORY_LIMIT"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_tmp_size_env_override_invalid_value_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HYDRAFLOW_DOCKER_TMP_SIZE with invalid notation must be rejected."""
        monkeypatch.setenv("HYDRAFLOW_DOCKER_TMP_SIZE", "4gb")
        with pytest.raises(ValueError, match="Invalid HYDRAFLOW_DOCKER_TMP_SIZE"):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )

    def test_execution_mode_default_value_overridden_by_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When execution_mode equals the default ('host'), env var overrides it.

        The override only applies when the value is still at the default. Because
        'host' IS the default, explicitly passing execution_mode='host' is
        indistinguishable from using the default, so the env var wins.
        """
        import shutil

        monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        monkeypatch.setenv("HYDRAFLOW_EXECUTION_MODE", "docker")
        cfg = HydraFlowConfig(
            execution_mode="host",
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.execution_mode == "docker"


# ---------------------------------------------------------------------------
# Docker config fields
# ---------------------------------------------------------------------------


class TestDockerConfig:
    """Tests for Docker-related configuration fields."""

    def test_docker_disabled_by_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_enabled is False

    def test_docker_image_has_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_image == "ghcr.io/t-rav/hydraflow-agent:latest"

    def test_docker_spawn_delay_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == 2.0

    def test_docker_network_empty_by_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_network == ""

    def test_docker_extra_mounts_empty_by_default(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_extra_mounts == []

    def test_docker_enabled_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRA_DOCKER_ENABLED", "true")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_enabled is True

    def test_docker_enabled_env_var_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRA_DOCKER_ENABLED", "no")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_enabled is False

    def test_docker_image_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRA_DOCKER_IMAGE", "hydra:v2")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_image == "hydra:v2"

    def test_docker_spawn_delay_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRA_DOCKER_SPAWN_DELAY", "5.0")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == 5.0

    def test_docker_spawn_delay_invalid_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRA_DOCKER_SPAWN_DELAY", "not-a-number")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_spawn_delay == 2.0  # default preserved

    def test_docker_network_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRA_DOCKER_NETWORK", "hydra-net")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert cfg.docker_network == "hydra-net"

    def test_docker_network_env_var_not_applied_when_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRA_DOCKER_NETWORK", "from-env")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            docker_network="explicit-net",
        )
        assert cfg.docker_network == "explicit-net"

    def test_docker_enabled_explicit_overrides_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRA_DOCKER_ENABLED", "true")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            docker_enabled=True,
        )
        assert cfg.docker_enabled is True

    def test_docker_custom_values(self, tmp_path: Path) -> None:
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            docker_enabled=True,
            docker_image="hydra-agent:latest",
            docker_spawn_delay=3.5,
            docker_network="my-network",
            docker_extra_mounts=["/host:/container:rw"],
        )
        assert cfg.docker_enabled is True
        assert cfg.docker_image == "hydra-agent:latest"
        assert cfg.docker_spawn_delay == 3.5
        assert cfg.docker_network == "my-network"
        assert cfg.docker_extra_mounts == ["/host:/container:rw"]

    def test_docker_spawn_delay_too_low(self, tmp_path: Path) -> None:
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                docker_spawn_delay=-1.0,
            )

    def test_docker_spawn_delay_too_high(self, tmp_path: Path) -> None:
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
                docker_spawn_delay=31.0,
            )
