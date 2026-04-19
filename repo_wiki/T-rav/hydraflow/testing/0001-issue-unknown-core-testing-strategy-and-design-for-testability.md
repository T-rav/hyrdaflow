---
id: 0001
topic: testing
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T14:53:08.908932+00:00
status: active
---

# Core Testing Strategy and Design for Testability

Function structure limits: Enforce 50-line limit on handler functions and 30-line limit on registration wiring; extract nested closures into instance methods to flatten nesting to ≤3 levels.

Mocking strategy: Mock at definition site, not usage site. For module-level imports, patch the assignment; for deferred imports, patch the definition module. For optional dependencies (sentry_sdk), use `unittest.mock.patch.dict("sys.modules", ...)` to guarantee cleanup. Mock sub-modules explicitly (both 'sentry_sdk' and 'sentry_sdk.integrations'). Mock return values must use identical keys and structure as actual TypedDict definitions.

Integration testing markers: Mark tests `@pytest.mark.integration` only if they exercise real external dependencies (Docker, network, filesystem, worktrees, service instances). Tests with `spec=AsyncMock` for all deps are unit/functional. Use `pytest.mark.skipif` with `shutil.which()` for optional CLI tools.

Async patterns: Use `AsyncMock` with explicit `assert_called_with()`. For fire-and-forget tasks via `create_task()`, call `await asyncio.sleep(0)` before assertions. Test async context managers in three scenarios: idempotent close, context manager triggers close on exit, returns self. Verify fatal exceptions propagate through multi-phase loops by mocking internal methods to raise specific types.

Subprocess/CLI testing: Create small Python scripts acting as CLI stand-ins, logging invocations to JSON-lines files for post-hoc assertions.

Conftest and fixtures: Session-scoped fixtures load before test modules. Use conftest.py as single source of truth for sys.path manipulation and autouse fixtures for state cleanup. Global/module-level state (e.g., `_gh_semaphore`, `_rate_limit_until`) must be reset completely in both setup and teardown. File-based test I/O must use `tmp_path` fixture with `ConfigFactory.create()` to avoid polluting project state. Export additive seed state variants (e.g., `seedStateWithHumanInput`) from conftest.py. Verify sys.modules cleanup with `pytest --randomly-seed` using multiple seeds.

Integration testing with phase runners: Wire real business logic (StateTracker, EventBus, VerificationJudge, RetrospectiveCollector) but mock only the `_execute()` subprocess boundary. Provide configurable transcript strings for real runner parsing, exposing mismatches fully-mocked runners hide. Validate state via StateTracker APIs and EventBus.get_history().

Protocol satisfaction: Use two complementary approaches: (1) Structural typing with `isinstance(concrete_instance, ProtocolName)` and `@runtime_checkable` to ensure contract satisfaction; (2) Duck-typing assertions using `hasattr(obj, 'method_name')` for loose coupling. Use `inspect.signature()` comparison to catch parameter drift. Parametrize tests for each protocol method.

Façaded refactors: Verify `__getattr__` correctly routes methods to sub-clients, raises `AttributeError` for nonexistent methods, the façade satisfies protocols via delegation, and existing tests that mock the original class still work. Sub-components receive mutable dict/set references (not copies) to shared state owned by the facade.

Testing during refactoring: When extracting private methods with unchanged public API, existing tests provide complete coverage (no new tests needed). When extracting prompt-building methods, run prompt-assertion tests in isolation immediately after extraction. Parameter renames are low-risk when all callers use positional arguments. For dead code removal, update all related test classes and helpers. When refactoring duplicated code, keep existing tests as regression checks. For documenting known broken behavior, use `@pytest.mark.skip(reason="documenting bug: [issue number]")` for removal after fix.

Telemetry and Sentry testing: Use `patch.dict("sys.modules", ...)` to mock sentry_sdk imports, then assert actual numeric values in breadcrumbs/metrics, not just presence of keys. When testing log output with pytest's `caplog` fixture, always specify exact logger name: `caplog.at_level(level, logger="module.name")`. Clear caplog before the action and assert on message substrings specific to logged values.

Assertion and test precision: For AST-based regression tests, parse source file ASTs to verify code structure assertions, allowing ±3 line drift tolerance. Tests asserting exact query strings are brittle; instead assert that specific key terms appear. Use f-strings to embed constants in assertions. Use `is` operator to verify runners share the same subprocess_runner instance. Substring matching in coverage checks produces false positives when short names collide; use word-boundary or full-name matching.

Frontend and browser testing: Server-side rendering via Django/FastAPI TestClient only sees the initial HTML shell, not attributes rendered by JavaScript. Accessibility attributes like `aria-labelledby` and other client-rendered properties require Playwright or browser-based testing. Dead Python tests attempting to verify these should be deleted in favor of browser-based tests. Browser tests are slower than TestClient but catch rendering-specific bugs that server-side tests miss. Organize browser test fixtures (e.g., `seedStateWithHumanInput`) in conftest.py for reuse.

See also: Type System and Data Model Consistency Testing — mock return values must match TypedDict structure.
