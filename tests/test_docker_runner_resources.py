"""Tests for build_container_kwargs — resource limits, network, and security."""

from __future__ import annotations

from docker_runner import build_container_kwargs
from tests.helpers import ConfigFactory


class TestBuildContainerKwargsDefaults:
    """Tests that default config produces correct Docker SDK kwargs."""

    def test_nano_cpus_from_default_cpu_limit(self) -> None:
        """Default 2.0 CPU cores → 2_000_000_000 nanoseconds."""
        cfg = ConfigFactory.create()
        kwargs = build_container_kwargs(cfg)
        assert kwargs["nano_cpus"] == 2_000_000_000

    def test_mem_limit_from_default(self) -> None:
        cfg = ConfigFactory.create()
        kwargs = build_container_kwargs(cfg)
        assert kwargs["mem_limit"] == "4g"

    def test_memswap_limit_equals_mem_limit(self) -> None:
        """memswap_limit should equal mem_limit to disable swap."""
        cfg = ConfigFactory.create()
        kwargs = build_container_kwargs(cfg)
        assert kwargs["memswap_limit"] == kwargs["mem_limit"]

    def test_pids_limit_from_default(self) -> None:
        cfg = ConfigFactory.create()
        kwargs = build_container_kwargs(cfg)
        assert kwargs["pids_limit"] == 256

    def test_network_mode_from_default(self) -> None:
        cfg = ConfigFactory.create()
        kwargs = build_container_kwargs(cfg)
        assert kwargs["network_mode"] == "bridge"

    def test_read_only_from_default(self) -> None:
        cfg = ConfigFactory.create()
        kwargs = build_container_kwargs(cfg)
        assert kwargs["read_only"] is True

    def test_security_opt_includes_no_new_privileges(self) -> None:
        cfg = ConfigFactory.create()
        kwargs = build_container_kwargs(cfg)
        assert "no-new-privileges:true" in kwargs["security_opt"]

    def test_cap_drop_all(self) -> None:
        cfg = ConfigFactory.create()
        kwargs = build_container_kwargs(cfg)
        assert kwargs["cap_drop"] == ["ALL"]

    def test_tmpfs_includes_tmp_with_size(self) -> None:
        cfg = ConfigFactory.create()
        kwargs = build_container_kwargs(cfg)
        assert "/tmp" in kwargs["tmpfs"]
        assert kwargs["tmpfs"]["/tmp"] == "size=1g"


class TestBuildContainerKwargsCustom:
    """Tests that custom config values are correctly translated to kwargs."""

    def test_custom_cpu_limit(self) -> None:
        cfg = ConfigFactory.create(docker_cpu_limit=4.0)
        kwargs = build_container_kwargs(cfg)
        assert kwargs["nano_cpus"] == 4_000_000_000

    def test_custom_memory_limit(self) -> None:
        cfg = ConfigFactory.create(docker_memory_limit="8g")
        kwargs = build_container_kwargs(cfg)
        assert kwargs["mem_limit"] == "8g"
        assert kwargs["memswap_limit"] == "8g"

    def test_custom_pids_limit(self) -> None:
        cfg = ConfigFactory.create(docker_pids_limit=512)
        kwargs = build_container_kwargs(cfg)
        assert kwargs["pids_limit"] == 512

    def test_network_mode_none(self) -> None:
        cfg = ConfigFactory.create(docker_network_mode="none")
        kwargs = build_container_kwargs(cfg)
        assert kwargs["network_mode"] == "none"

    def test_custom_tmp_size(self) -> None:
        cfg = ConfigFactory.create(docker_tmp_size="2g")
        kwargs = build_container_kwargs(cfg)
        assert kwargs["tmpfs"]["/tmp"] == "size=2g"

    def test_fractional_cpu_limit(self) -> None:
        cfg = ConfigFactory.create(docker_cpu_limit=0.5)
        kwargs = build_container_kwargs(cfg)
        assert kwargs["nano_cpus"] == 500_000_000


class TestBuildContainerKwargsSecurityOpts:
    """Tests for security_opt behavior based on config."""

    def test_no_new_privileges_true_includes_security_opt(self) -> None:
        cfg = ConfigFactory.create(docker_no_new_privileges=True)
        kwargs = build_container_kwargs(cfg)
        assert "security_opt" in kwargs
        assert "no-new-privileges:true" in kwargs["security_opt"]

    def test_no_new_privileges_false_omits_security_opt(self) -> None:
        cfg = ConfigFactory.create(docker_no_new_privileges=False)
        kwargs = build_container_kwargs(cfg)
        assert "security_opt" not in kwargs

    def test_read_only_false(self) -> None:
        cfg = ConfigFactory.create(docker_read_only_root=False)
        kwargs = build_container_kwargs(cfg)
        assert kwargs["read_only"] is False

    def test_cap_drop_always_present(self) -> None:
        """cap_drop=["ALL"] should always be set regardless of other security opts."""
        cfg = ConfigFactory.create(docker_no_new_privileges=False)
        kwargs = build_container_kwargs(cfg)
        assert kwargs["cap_drop"] == ["ALL"]


class TestBuildContainerKwargsTmpfs:
    """Tests for tmpfs configuration."""

    def test_tmpfs_dict_has_tmp_key(self) -> None:
        cfg = ConfigFactory.create()
        kwargs = build_container_kwargs(cfg)
        assert isinstance(kwargs["tmpfs"], dict)
        assert "/tmp" in kwargs["tmpfs"]

    def test_tmpfs_size_from_config(self) -> None:
        cfg = ConfigFactory.create(docker_tmp_size="512m")
        kwargs = build_container_kwargs(cfg)
        assert kwargs["tmpfs"]["/tmp"] == "size=512m"
