"""Boot-smoke: every loop on ServiceRegistry ticks once without an unexpected raise.

Closes the gap between "unit tests + CI green" and "the loops actually run when
the server boots in production".  Tonight's cascade had five distinct loop-runtime
failures (``JSONDecodeError`` on audit-json, ``issue #0`` sentinel mis-handling,
ADR title drift, missing-label gh failures, LiveCorpusReplayLoop wiring) and only
the wiring one was caught by static tests.

The smoke contract is intentionally permissive: a loop is allowed to fail at the
external-IO boundary (``subprocess`` returning rc!=0 for a missing ``gh`` binary,
``ConnectionError`` reaching the real GitHub API, etc.) because that's expected
when test-mode mocks aren't wired.  It is **not** allowed to raise on the
internal contract — ``TypeError`` from a missing attribute, ``json.JSONDecodeError``
from parsing tool output, ``KeyError`` from a stale dict shape — that's the
signature of a bug like the ones tonight surfaced.

Tradeoff: tick-once misses multi-cycle bugs (dedup races, attempt counters,
state-machine progression).  Those still need targeted scenario tests.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus
from service_registry import ServiceRegistry, build_services
from state import StateTracker
from tests.test_service_registry import _make_callbacks

if TYPE_CHECKING:
    from config import HydraFlowConfig


# Failure modes that mean "external IO unavailable in the test box", not "bug":
#   - subprocess called something that's not on PATH or returned rc!=0
#   - real network call hit a DNS/socket error
#   - filesystem permissions / missing path
_EXPECTED_EXTERNAL_FAILURES: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    PermissionError,
    FileNotFoundError,
)


def _all_loop_fields() -> list[str]:
    """Return every ServiceRegistry dataclass field ending in ``_loop``."""
    return [f for f in ServiceRegistry.__dataclass_fields__ if f.endswith("_loop")]


@pytest.mark.asyncio
@pytest.mark.parametrize("loop_field", _all_loop_fields())
async def test_loop_ticks_without_internal_raise(
    config: HydraFlowConfig, loop_field: str
) -> None:
    """``await loop._do_work()`` must not raise an internal-contract error.

    External-IO failures (``ConnectionError`` etc.) are tolerated — they mean
    the loop reached its boundary and a real fake would be needed to drive it
    further.  Anything else is a wiring / sentinel / parse bug, which is
    exactly what this smoke catches.
    """
    bus = EventBus()
    state = StateTracker(config.state_file)
    stop_event = asyncio.Event()
    callbacks = _make_callbacks()

    registry = build_services(config, bus, state, stop_event, callbacks)
    loop = getattr(registry, loop_field)
    if loop is None:
        pytest.skip(f"{loop_field} is gated off by config (optional integration)")

    try:
        await asyncio.wait_for(loop._do_work(), timeout=10.0)
    except _EXPECTED_EXTERNAL_FAILURES:
        # Boundary reached; that's the contract.
        pass
    except RuntimeError as exc:
        # ``RuntimeError`` is the generic wrapper that ``subprocess_util`` and
        # ``execution.SubprocessRunner`` raise for non-zero subprocess exits.
        # We allow it iff the message smells like an external-IO failure;
        # otherwise re-raise so the test fails with the real traceback.
        if any(
            marker in str(exc).lower()
            for marker in (
                "command",
                "rc=",
                "exit",
                "not found",
                "could not resolve",
                "permission denied",
            )
        ):
            pass
        else:
            raise
    except TimeoutError:
        pytest.skip(
            f"{loop_field} ticked beyond 10s — likely real network IO; "
            "consider mocking the boundary for a deterministic smoke."
        )
