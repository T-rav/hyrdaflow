"""Production-side contract schemas.

Lives in ``src/`` so production modules (e.g. ``contract_diff``,
``contract_recording``) can import without a ``src→tests`` dependency.
The cassette schema previously lived at ``tests/trust/contracts/_schema.py``;
it was relocated here as a follow-up to PR A's ``_factories`` move
(production code should never require ``tests/`` on ``sys.path``).

Spec: docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md
§4.2 "Cassette schema".
"""
