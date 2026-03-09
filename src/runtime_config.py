"""Runtime configuration loader for HydraFlow server."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from config import HydraFlowConfig, load_config_file


def _default_data_root_path() -> Path:
    """Return the preferred HydraFlow data root."""
    env_home = os.environ.get("HYDRAFLOW_HOME", "").strip()
    if env_home:
        return Path(env_home).expanduser()
    return Path(".hydraflow")


DEFAULT_CONFIG_PATH = _default_data_root_path() / "config.json"
DEFAULT_LOG_FILE = _default_data_root_path() / "logs" / "hydraflow.log"


def apply_repo_config_overlay(
    config: HydraFlowConfig, cli_explicit: set[str] | None = None
) -> None:
    """Apply repo-scoped config overlay, mirroring legacy CLI behavior."""
    explicit = cli_explicit or set()
    if config.config_file is None:
        return
    repo_cfg = load_config_file(config.config_file)
    if not repo_cfg:
        return
    known_fields = set(HydraFlowConfig.model_fields.keys())
    for key, val in repo_cfg.items():
        if key in known_fields and key not in explicit:
            object.__setattr__(config, key, val)


def load_runtime_config(
    config_file: str | os.PathLike[str] | None = None,
    overrides: dict[str, Any] | None = None,
) -> HydraFlowConfig:
    """Load HydraFlow configuration from disk, applying overrides."""
    env_override = os.environ.get("HYDRAFLOW_CONFIG_FILE", "").strip()
    chosen_path: Path
    if config_file is not None:
        chosen_path = Path(config_file).expanduser().resolve()
    elif env_override:
        chosen_path = Path(env_override).expanduser().resolve()
    else:
        chosen_path = DEFAULT_CONFIG_PATH.expanduser().resolve()

    file_kwargs = load_config_file(chosen_path)
    known_fields = set(HydraFlowConfig.model_fields.keys())
    kwargs: dict[str, Any] = {
        key: value for key, value in file_kwargs.items() if key in known_fields
    }
    kwargs["config_file"] = chosen_path

    explicit_fields: set[str] = set()
    if overrides:
        for key, value in overrides.items():
            if key in known_fields:
                kwargs[key] = value
                explicit_fields.add(key)

    config = HydraFlowConfig(**kwargs)
    apply_repo_config_overlay(config, explicit_fields)
    return config


__all__ = [
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_LOG_FILE",
    "apply_repo_config_overlay",
    "load_runtime_config",
]
