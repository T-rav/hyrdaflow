"""Regression: LiveCorpusReplayLoop must remain wired into the curated maps.

PR #8939 fixed staging drift caused by LiveCorpusReplayLoop (#8786 Phase 2 /
ADR-0045) landing construction-only without being threaded through:

1. ``ServiceRegistry`` dataclass (``live_corpus_replay_loop`` field)
2. ``docs/arch/functional_areas.yml`` (``trust_fleet`` area)
3. ``src/dashboard_routes/_common.py`` (``_INTERVAL_BOUNDS``)
4. ``src/ui/src/constants.js`` (``BACKGROUND_WORKERS``)
5. ``tests/test_state_tracking.py`` (expected state-keys)

The four wiring sites are independently asserted by
``tests/test_loop_wiring_completeness.py`` (via regex over file text), and the
state-keys assertion lives in ``tests/test_state_tracking.py``. This
regression closes the loop with one assertion per *direct* surface so a
single failure here points straight at the missing wiring rather than at
half a dozen unrelated suites.

If any of these assertions start failing, restore the wiring at the named
location rather than weakening the assertion.
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"


def test_service_registry_declares_live_corpus_replay_loop_field() -> None:
    text = (_SRC / "service_registry.py").read_text(encoding="utf-8")
    assert "live_corpus_replay_loop: LiveCorpusReplayLoop | None" in text, (
        "ServiceRegistry must declare `live_corpus_replay_loop: "
        "LiveCorpusReplayLoop | None` — see PR #8939."
    )


def test_functional_areas_assigns_live_corpus_replay_to_trust_fleet() -> None:
    text = (_REPO / "docs" / "arch" / "functional_areas.yml").read_text(
        encoding="utf-8"
    )
    # Look for the literal class name under the trust_fleet area's loops list.
    # The area-coverage test asserts global presence; this asserts the
    # specific bucket so a future renamer can't silently move it elsewhere.
    trust_fleet_block = text.split("trust_fleet:", 1)[-1].split("hexagonal_", 1)[0]
    assert "LiveCorpusReplayLoop" in trust_fleet_block, (
        "LiveCorpusReplayLoop must remain under `trust_fleet.loops` "
        "(ADR-0045 fleet) — see PR #8939."
    )


def test_interval_bounds_includes_live_corpus_replay() -> None:
    text = (_SRC / "dashboard_routes" / "_common.py").read_text(encoding="utf-8")
    assert '"live_corpus_replay":' in text, (
        "`_INTERVAL_BOUNDS` must include `live_corpus_replay` so the "
        "dashboard can render its interval control — see PR #8939."
    )


def test_constants_js_lists_live_corpus_replay_worker() -> None:
    text = (_SRC / "ui" / "src" / "constants.js").read_text(encoding="utf-8")
    assert "key: 'live_corpus_replay'" in text, (
        "`BACKGROUND_WORKERS` in constants.js must include the "
        "live_corpus_replay entry — see PR #8939."
    )
