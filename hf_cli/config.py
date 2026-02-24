"""hf CLI configuration helpers."""

from __future__ import annotations

from pathlib import Path

STATE_DIR = Path.home() / ".hydraflow"
STATE_DIR.mkdir(parents=True, exist_ok=True)

SUPERVISOR_STATE_FILE = STATE_DIR / "supervisor-state.json"
SUPERVISOR_PORT_FILE = STATE_DIR / "supervisor-port"
DEFAULT_SUPERVISOR_PORT = 8765
