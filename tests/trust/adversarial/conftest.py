"""Prevent pytest from collecting adversarial fixture files as tests.

Each case under `cases/` contains intentionally-broken `before/` and
`after/` trees. Some test-adequacy cases include `tests/` subdirectories
with files named `test_*.py` — those are fixtures the harness feeds to
skills, not tests that should run in the suite.

`collect_ignore_glob = ["cases/*"]` tells pytest to skip discovery for
everything under cases/, so only this directory's
`test_adversarial_corpus.py` harness runs.
"""

from __future__ import annotations

collect_ignore_glob = ["cases/*"]
