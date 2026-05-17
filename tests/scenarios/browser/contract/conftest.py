"""Contract test fixtures.

The snapshot-based ``assert_screenshot`` fixture and its
``--update-snapshots`` CLI option were removed 2026-05-17 along with
``test_tabs_empty.py`` / ``test_tabs_populated.py``. Pixel-diff
baselines are platform-fragile (font rendering varies between
macOS/Linux/x86_64/aarch64) and the maintenance cost has consistently
exceeded the regression-detection value. Behaviour-level browser
scenarios under ``tests/scenarios/browser/scenarios/`` are the new
contract surface — they assert DOM presence, navigation, and event
flow rather than visual fidelity.

Kept here as an empty conftest so the package remains a valid pytest
collection target (``test_seeds.py`` still lives in this directory).
"""

from __future__ import annotations
