"""hf CLI configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path


def _default_state_dir() -> Path:
    """Return the preferred CLI state directory honoring HYDRAFLOW_HOME."""
    env_home = os.environ.get("HYDRAFLOW_HOME", "").strip()
    if env_home:
        return Path(env_home).expanduser()
    return Path.home() / ".hydraflow"


def _resolve_state_dir() -> Path:
    """Create the state dir, falling back to ./ .hydraflow if the home dir is read-only."""
    preferred = _default_state_dir()
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        fallback = Path(".hydraflow")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


STATE_DIR = _resolve_state_dir()

SUPERVISOR_STATE_FILE = STATE_DIR / "supervisor-state.json"
SUPERVISOR_PORT_FILE = STATE_DIR / "supervisor-port"
DEFAULT_SUPERVISOR_PORT = 8765
