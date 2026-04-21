"""Tests for the boot-time install branch of preflight._check_plugins."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from config import HydraFlowConfig
from plugin_skill_registry import clear_plugin_skill_cache
from preflight import CheckStatus, _check_plugins


@pytest.fixture(autouse=True)
def _clear_caches():
    clear_plugin_skill_cache()
    yield
    clear_plugin_skill_cache()


def _write_fake_skill(
    cache_root: Path, marketplace: str, plugin: str, skill: str
) -> None:
    skill_dir = cache_root / marketplace / plugin / "1.0.0" / "skills" / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {skill}\ndescription: test skill\n---\nbody\n"
    )


def test_auto_install_runs_claude_for_missing_plugin(tmp_path: Path):
    cfg = HydraFlowConfig(
        required_plugins=["superpowers"],
        auto_install_plugins=True,
    )

    def fake_run(argv, **kwargs):
        # Simulate install by populating the cache, then return success.
        assert argv == [
            "claude",
            "plugin",
            "install",
            "superpowers@claude-plugins-official",
            "--scope",
            "user",
        ]
        _write_fake_skill(tmp_path, "claude-plugins-official", "superpowers", "tdd")
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    with patch("preflight.subprocess.run", side_effect=fake_run) as mock_run:
        result = _check_plugins(cfg, cache_root=tmp_path)

    assert result.status == CheckStatus.PASS
    assert mock_run.call_count == 1


def test_auto_install_failure_falls_through_to_rich_fail(tmp_path: Path):
    cfg = HydraFlowConfig(
        required_plugins=["superpowers"],
        auto_install_plugins=True,
    )

    def fake_run(argv, **kwargs):
        # Install "succeeds" but plugin still isn't in the cache.
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")

    with patch("preflight.subprocess.run", side_effect=fake_run):
        result = _check_plugins(cfg, cache_root=tmp_path)

    assert result.status == CheckStatus.FAIL
    assert "make install-plugins" in result.message
    assert "claude login" in result.message


def test_install_timeout_treated_as_failure(tmp_path: Path):
    cfg = HydraFlowConfig(
        required_plugins=["superpowers"],
        auto_install_plugins=True,
    )

    with patch(
        "preflight.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120),
    ):
        result = _check_plugins(cfg, cache_root=tmp_path)

    assert result.status == CheckStatus.FAIL
    assert "timed out" in result.message.lower()


def test_claude_binary_missing_skips_install_and_fails(tmp_path: Path):
    cfg = HydraFlowConfig(
        required_plugins=["superpowers"],
        auto_install_plugins=True,
    )

    with patch("preflight.subprocess.run", side_effect=FileNotFoundError):
        result = _check_plugins(cfg, cache_root=tmp_path)

    assert result.status == CheckStatus.FAIL
    assert "claude" in result.message.lower()


def test_auto_install_disabled_matches_legacy_behavior(tmp_path: Path):
    cfg = HydraFlowConfig(
        required_plugins=["superpowers"],
        auto_install_plugins=False,
    )

    with patch("preflight.subprocess.run") as mock_run:
        result = _check_plugins(cfg, cache_root=tmp_path)

    assert result.status == CheckStatus.FAIL
    assert mock_run.call_count == 0  # never touched subprocess


def test_explicit_marketplace_in_spec(tmp_path: Path):
    cfg = HydraFlowConfig(
        required_plugins=["foo@custom-marketplace"],
        auto_install_plugins=True,
    )

    def fake_run(argv, **kwargs):
        assert argv == [
            "claude",
            "plugin",
            "install",
            "foo@custom-marketplace",
            "--scope",
            "user",
        ]
        _write_fake_skill(tmp_path, "custom-marketplace", "foo", "bar")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    with patch("preflight.subprocess.run", side_effect=fake_run):
        result = _check_plugins(cfg, cache_root=tmp_path)

    assert result.status == CheckStatus.PASS
