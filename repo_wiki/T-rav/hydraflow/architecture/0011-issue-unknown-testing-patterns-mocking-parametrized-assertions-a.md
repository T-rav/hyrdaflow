---
id: 0011
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849559+00:00
status: active
---

# Testing Patterns: Mocking, Parametrized Assertions, and Test Helpers

For test isolation with sys.modules manipulation, use pytest's monkeypatch.delitem() with raising=False to handle both existing and missing keys, and monkeypatch guarantees cleanup on teardown. Save original module state via `had = k in sys.modules; original = sys.modules.get(k)`, then restore with monkeypatch. Use parametrized tests with dual lists (_REQUIRED_METHODS, _SIGNED_METHODS) to validate interface conformance via set subtraction. Tests should check presence via content assertion, not just structure (verify specific module names, not just that labels exist). Follow existing test class patterns (TestBuildStage, TestEdgeCases, TestPartialTimelines) when adding similar validators. Conftest at session scope handles sys.path setup, making explicit sys.path.insert calls in test modules redundant. For deferred imports in tests, see Deferred Imports, Type Checking, and Testing.
