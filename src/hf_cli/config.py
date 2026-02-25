"""hf CLI configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path

STATE_DIR = Path(
    os.environ.get("HYDRAFLOW_HOME", str(Path.home() / ".hydraflow"))
).expanduser()
STATE_DIR.mkdir(parents=True, exist_ok=True)

SUPERVISOR_STATE_FILE = STATE_DIR / "supervisor-state.json"
SUPERVISOR_PORT_FILE = STATE_DIR / "supervisor-port"
DEFAULT_SUPERVISOR_PORT = 8765
