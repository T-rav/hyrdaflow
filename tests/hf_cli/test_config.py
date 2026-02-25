from __future__ import annotations

import importlib
from pathlib import Path


def test_state_dir_defaults_to_user_home(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("HYDRAFLOW_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    import hf_cli.config as hf_config

    importlib.reload(hf_config)

    assert tmp_path / ".hydraflow" == hf_config.STATE_DIR
    assert (
        hf_config.SUPERVISOR_STATE_FILE == hf_config.STATE_DIR / "supervisor-state.json"
    )
    assert hf_config.SUPERVISOR_PORT_FILE == hf_config.STATE_DIR / "supervisor-port"


def test_state_dir_respects_env_override(monkeypatch, tmp_path) -> None:
    custom_home = tmp_path / "custom-hf-home"
    monkeypatch.setenv("HYDRAFLOW_HOME", str(custom_home))

    import hf_cli.config as hf_config

    importlib.reload(hf_config)

    assert custom_home == hf_config.STATE_DIR
    assert custom_home.exists()
