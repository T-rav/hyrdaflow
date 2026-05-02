"""Regression: contract_recording must not block the asyncio event loop.

Originally surfaced by sandbox-tier work (PR #8452): on the air-gapped
internal:true network, ContractRefreshLoop's subprocess.run(claude -p ping)
hung indefinitely, deadlocking the orchestrator's asyncio loop and
preventing the dashboard from binding port 5555.

Fix:
1. subprocess.run gets an explicit timeout so it cannot hang forever.
2. The callers wrap the blocking subprocess.run in asyncio.to_thread.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
_RECORDING = _REPO / "src" / "contract_recording.py"
_LOOP = _REPO / "src" / "contract_refresh_loop.py"


def test_contract_recording_subprocess_has_timeout() -> None:
    """Every subprocess.run call in contract_recording.py must specify a timeout."""
    src = _RECORDING.read_text()
    assert "subprocess.run(" in src, "subprocess.run not found in contract_recording.py"
    pattern = re.compile(r"subprocess\.run\([^)]*timeout=", re.DOTALL)
    matches = pattern.findall(src)
    assert matches, (
        "subprocess.run is called without a timeout argument; this can "
        "block the asyncio event loop forever on network-hung subprocesses."
    )


def test_contract_refresh_loop_wraps_blocking_call() -> None:
    """ContractRefreshLoop must wrap the blocking record_claude_stream call
    in asyncio.to_thread so the event loop is not blocked.
    """
    src = _LOOP.read_text()
    assert "asyncio.to_thread" in src, (
        "contract_refresh_loop.py does not use asyncio.to_thread anywhere; "
        "the blocking subprocess.run from record_claude_stream will deadlock "
        "the asyncio event loop."
    )
