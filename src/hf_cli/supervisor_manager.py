"""Utilities for starting and interacting with the supervisor."""

from __future__ import annotations

import subprocess
import sys
import time

from . import supervisor_client
from .config import STATE_DIR

_SUPERVISOR_LOG = STATE_DIR / "supervisor.log"


def ensure_running() -> None:
    if supervisor_client.ping():
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = _SUPERVISOR_LOG.open("a")
    try:
        process = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "hf_cli.supervisor_service"],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_handle.close()
    start = time.time()
    timeout = 5.0
    while time.time() - start < timeout:
        if supervisor_client.ping():
            return
        if process.poll() is not None:
            code = process.returncode
            raise RuntimeError(
                f"Supervisor exited unexpectedly (code {code}); see {_SUPERVISOR_LOG}"
            )
        time.sleep(0.1)
    raise RuntimeError(
        f"Timed out waiting for supervisor to start; see {_SUPERVISOR_LOG}"
    )
