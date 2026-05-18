"""CI guard: MockWorld catalog must cover every loop in bg_loop_registry.

Any loop added to ``orchestrator.py``'s ``bg_loop_registry`` without a
corresponding builder in ``loop_registrations._BUILDERS`` will be caught here
before it reaches code review.

Loops intentionally excluded from the catalog (e.g. ``github_cache``, which
is started separately and has no scenario coverage) are listed in
``_CATALOG_SKIP``. Add to the skip list only with a comment explaining why.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.scenarios.catalog.loop_registrations import _BUILDERS

SRC = Path(__file__).resolve().parents[3] / "src"

# ---------------------------------------------------------------------------
# Loops that exist in bg_loop_registry but intentionally lack catalog builders.
# These are loops started outside the standard BGWorkerManager lifecycle.
# ---------------------------------------------------------------------------
_CATALOG_SKIP: set[str] = {
    "github_cache",  # started separately via GitHubCacheLoop; no scenario needed
}


def _parse_bg_loop_registry() -> set[str]:
    """Extract worker_name keys from orchestrator.py's bg_loop_registry dict."""
    text = (SRC / "orchestrator.py").read_text()
    # Match lines like:  "memory_sync": svc.memory_sync_bg,
    return set(re.findall(r'"(\w+)"\s*:\s*svc\.', text))


def test_catalog_covers_bg_loop_registry() -> None:
    """Every loop in bg_loop_registry must have a catalog builder.

    When this test fails, add the missing loop to
    ``tests/scenarios/catalog/loop_registrations.py`` following the builder
    pattern documented there. Only add to ``_CATALOG_SKIP`` if the loop is
    genuinely not exercised via MockWorld scenarios.
    """
    registry_keys = _parse_bg_loop_registry()
    catalog_keys = set(_BUILDERS.keys())
    missing = (registry_keys - catalog_keys) - _CATALOG_SKIP
    assert not missing, (
        f"Loops in bg_loop_registry but missing from MockWorld catalog: "
        f"{sorted(missing)}\n\n"
        f"Add a builder to tests/scenarios/catalog/loop_registrations.py, "
        f"or add to _CATALOG_SKIP with a justification comment."
    )


def test_catalog_skip_entries_are_real_loops() -> None:
    """Catch stale entries in _CATALOG_SKIP that are neither in the registry
    nor in the catalog itself.

    An entry is valid if it appears in either the orchestrator ``bg_loop_registry``
    or the catalog ``_BUILDERS`` (``github_cache`` is in the catalog but started
    outside the registry lifecycle). An entry that appears in neither is a typo.
    """
    registry_keys = _parse_bg_loop_registry()
    catalog_keys = set(_BUILDERS.keys())
    known = registry_keys | catalog_keys
    stale = _CATALOG_SKIP - known
    assert not stale, (
        f"_CATALOG_SKIP entries not found in bg_loop_registry or catalog (stale?): "
        f"{sorted(stale)}"
    )


@pytest.mark.parametrize("name", sorted(_BUILDERS.keys()))
def test_builder_key_matches_registry(name: str) -> None:
    """Each catalog key must match a key in bg_loop_registry (or the skip list).

    This catches typos where the catalog registers a builder under the wrong
    name (e.g. ``sentry`` vs the canonical ``sentry_ingest``).
    """
    registry_keys = _parse_bg_loop_registry()
    # github_cache is in the catalog for historical reasons but not in the
    # orchestrator registry; allow it via the same skip mechanism.
    allowed = registry_keys | _CATALOG_SKIP
    assert name in allowed, (
        f"Catalog key {name!r} is not present in bg_loop_registry. "
        f"Either fix the key to match the registry, or add it to _CATALOG_SKIP."
    )
