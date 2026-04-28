"""Sandbox-tier scenario suite (PR A onward).

Each scenario module under ``scenarios/`` is a Python file exposing
``NAME``, ``DESCRIPTION``, ``seed()`` (returning a ``MockWorldSeed``) and
optionally ``assert_outcome(world)``. The scenarios are dual-tier:

- Tier 1 (in-process): driven by ``tests/scenarios/test_sandbox_parity.py``
  using a ``MockWorld`` directly. Fast (<1s). Catches scenario-logic and
  Fake-behavior bugs.

- Tier 2 (sandbox): driven by Playwright against a docker-compose stack
  booted from ``mockworld.sandbox_main``. Slower (15-30s). Catches
  container/wiring/UI regressions Tier 1 cannot. Lands in PR B.
"""
