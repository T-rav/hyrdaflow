# Testing


## Enforce function structure limits for testability

Limit handler functions to 50 lines and registration wiring to 30 lines. Extract nested closures into instance methods to flatten nesting to ≤3 levels. Example: move callback validation from nested closures to instance methods. **Why:** Deep nesting and long functions are difficult to test in isolation and encourage tight coupling.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA0","title":"Enforce function structure limits for testability","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643489+00:00","updated_at":"2026-05-03T04:19:35.643728+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Mock at definition site, not usage site

For module-level imports, patch the assignment; for deferred imports, patch the definition module. For optional dependencies, use `unittest.mock.patch.dict("sys.modules", ...)` to guarantee cleanup. Mock sub-modules explicitly (both 'sentry_sdk' and 'sentry_sdk.integrations'). **Why:** Mocking at usage site leaves stale code paths and misses circular imports.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA1","title":"Mock at definition site, not usage site","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643783+00:00","updated_at":"2026-05-03T04:19:35.643784+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Mark integration tests with @pytest.mark.integration

Only mark tests that exercise real external dependencies (Docker, network, filesystem, worktrees, service instances). Tests with `spec=AsyncMock` for all deps are unit/functional. Use `pytest.mark.skipif` with `shutil.which()` for optional CLI tools. **Why:** Separates true integration tests from unit tests for faster feedback loops.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA2","title":"Mark integration tests with @pytest.mark.integration","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643796+00:00","updated_at":"2026-05-03T04:19:35.643797+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Test async patterns with AsyncMock and fire-and-forget cleanup

Use `AsyncMock` with explicit `assert_called_with()`. For fire-and-forget tasks via `create_task()`, call `await asyncio.sleep(0)` before assertions. Test async context managers: idempotent close, context manager triggers close on exit, returns self. **Why:** Async fire-and-forget races without yield points; explicit sleep ensures task completion.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA3","title":"Test async patterns with AsyncMock and fire-and-forget cleanup","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643805+00:00","updated_at":"2026-05-03T04:19:35.643808+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Create Python script stand-ins for subprocess/CLI testing

Instead of mocking subprocess calls, create small Python scripts acting as CLI stand-ins that log invocations to JSON-lines files for post-hoc assertions. Example: test helper script that records CLI args and exit codes to a timestamped log. **Why:** Real subprocess invocation catches shell escaping bugs and argument ordering mistakes mocks hide.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA4","title":"Create Python script stand-ins for subprocess/CLI testing","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643816+00:00","updated_at":"2026-05-03T04:19:35.643817+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use conftest as single source of truth for fixture setup

Session-scoped fixtures load before test modules. Use conftest.py for sys.path manipulation and autouse fixtures for state cleanup. Reset global/module-level state in both setup and teardown. Verify cleanup with `pytest --randomly-seed` using multiple seeds. **Why:** Shared state bleeds across tests when cleanup is incomplete.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA5","title":"Use conftest as single source of truth for fixture setup","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643824+00:00","updated_at":"2026-05-03T04:19:35.643827+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Wire real business logic in integration tests, mock subprocess boundary

For integration testing with phase runners: use real StateTracker, EventBus, VerificationJudge, RetrospectiveCollector; mock only `_execute()` subprocess boundary. Provide configurable transcript strings for real runner parsing. Validate state via StateTracker APIs and EventBus.get_history(). **Why:** Real phase logic catches mismatches fully-mocked runners hide.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA6","title":"Wire real business logic in integration tests, mock subprocess boundary","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643836+00:00","updated_at":"2026-05-03T04:19:35.643837+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Test protocol satisfaction with structural + duck typing

Use two approaches: (1) Structural typing with `isinstance(obj, ProtocolName)` and `@runtime_checkable`; (2) Duck-typing assertions via `hasattr(obj, 'method_name')`. Use `inspect.signature()` to catch parameter drift. Parametrize tests for each protocol method. **Why:** Structural typing alone misses runtime `__getattr__` issues; duck typing alone misses signature changes.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA7","title":"Test protocol satisfaction with structural + duck typing","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643856+00:00","updated_at":"2026-05-03T04:19:35.643857+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Verify façaded refactors with __getattr__ routing tests

When refactoring into a façade: verify `__getattr__` routes methods correctly, raises `AttributeError` for nonexistent methods, satisfies protocols via delegation, and existing tests mocking the original class still work. Sub-components receive mutable dict/set references (not copies) to shared state. **Why:** Incorrect delegation silently breaks public APIs.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA8","title":"Verify façaded refactors with __getattr__ routing tests","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643866+00:00","updated_at":"2026-05-03T04:19:35.643867+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Test extraction by running prompt-assertion tests in isolation

When extracting prompt-building methods, run prompt-assertion tests immediately after extraction. For private method extraction with unchanged public API, existing tests provide complete coverage (no new tests needed). For parameter renames using positional arguments, refactoring is low-risk. **Why:** Post-extraction testing catches prompt generation regressions immediately.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCA9","title":"Test extraction by running prompt-assertion tests in isolation","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643873+00:00","updated_at":"2026-05-03T04:19:35.643875+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Test Sentry/telemetry by asserting numeric values, not just key presence

Use `patch.dict("sys.modules", ...)` to mock sentry_sdk imports. Assert actual numeric values in breadcrumbs/metrics, not just presence of keys. For logging assertions, specify exact logger: `caplog.at_level(level, logger="module.name")`. Clear caplog before action. **Why:** Key-only assertions pass when values are wrong; wrong logger names miss assertions.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAA","title":"Test Sentry/telemetry by asserting numeric values, not just key presence","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643880+00:00","updated_at":"2026-05-03T04:19:35.643881+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Assert on key terms, not exact query strings

For AST-based regression tests, parse source ASTs and allow ±3 line drift. For assertions on query strings, verify specific key terms appear rather than exact string match. Use f-strings to embed constants in assertions. Use word-boundary matching to avoid collisions. **Why:** Exact query assertions break with refactoring; key-term matching is resilient.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAB","title":"Assert on key terms, not exact query strings","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643887+00:00","updated_at":"2026-05-03T04:19:35.643887+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use Playwright for frontend testing, not TestClient alone

TestClient only sees initial HTML shell, not JavaScript-rendered attributes. `aria-labelledby` and client-rendered properties require Playwright or browser testing. Delete dead Python tests attempting to verify these. Organize browser test fixtures in conftest.py for reuse. **Why:** Server-side rendering misses JavaScript-dependent behavior that breaks in production.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAC","title":"Use Playwright for frontend testing, not TestClient alone","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643893+00:00","updated_at":"2026-05-03T04:19:35.643893+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Never assert on absolute singleton ID values

Global singletons like `_event_counter` are shared across all instances. Tests must assert only on relative ordering and uniqueness within a single test, never on absolute values. Example: assert `id1 < id2` rather than `id1 == 42`. **Why:** Absolute ID assertions cause cross-test pollution when tests run in different orders.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAD","title":"Never assert on absolute singleton ID values","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643899+00:00","updated_at":"2026-05-03T04:19:35.643900+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Keep schema evolution tests in sync with constants

Before property-based tests, add structural tests: every target stage is valid, every stage has transition entry, no dangling references. Test constants serve as both oracles and documentation—keep synchronized. Use `len(LABELS) == 13` instead of hardcoding. **Why:** Drift between constants and tests silently allows invalid transitions.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAE","title":"Keep schema evolution tests in sync with constants","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643905+00:00","updated_at":"2026-05-03T04:19:35.643906+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Update all serialization tests when adding Pydantic fields

When adding a field to a Pydantic model (e.g., `PRListItem`, `StateData`), grep `tests/` for the model name and update: `model_dump()` assertions, expected key sets in smoke tests, and any `assert result == {...}` hard-coding the full shape. **Why:** New fields silently fail in unrelated refactors when serialization tests aren't updated.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAF","title":"Update all serialization tests when adding Pydantic fields","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643911+00:00","updated_at":"2026-05-03T04:19:35.643912+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use `is None` for optional object truthiness checks

Never write `if not self._hindsight:` to test optional presence. Use explicit `if self._hindsight is None:`. Mock objects with `spec=...` and empty collections can be falsy, triggering wrong branches. Example: `if callback is None:` instead of `if not callback:`. **Why:** Identity checks are unambiguous; truthiness checks can unexpectedly match falsy objects.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAG","title":"Use `is None` for optional object truthiness checks","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643917+00:00","updated_at":"2026-05-03T04:19:35.643918+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Check conftest before adding duplicate test helpers

Before adding `def _<helper>` to a test file, grep `tests/conftest.py` and `tests/helpers*.py` for similar helpers. Shared fixtures belong in conftest; duplicates cause silent drift when one copy is updated. **Why:** Duplicated helpers diverge silently when one copy gains parameters the other lacks.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAH","title":"Check conftest before adding duplicate test helpers","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643923+00:00","updated_at":"2026-05-03T04:19:35.643925+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Never test ADR markdown content

Do not create `test_adr_NNNN_*.py` files asserting on markdown headings, status fields, or prose. Only test ADR-related code (e.g., `test_adr_reviewer.py` tests the reviewer logic, not the doc). **Why:** Content tests break on edits; they provide no runtime value.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAJ","title":"Never test ADR markdown content","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643930+00:00","updated_at":"2026-05-03T04:19:35.643931+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Always run make quality before declaring work complete

Run `make quality` before committing to verify lint, tests, type checks, and code coverage all pass. Do not present implementation as done until quality gates pass. **Why:** Quality gates catch regressions that individual test runs miss.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAK","title":"Always run make quality before declaring work complete","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643936+00:00","updated_at":"2026-05-03T04:19:35.643938+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Write unit tests before committing code changes

Every new function, class, or feature modification MUST include comprehensive tests in `tests/test_<module>.py` before commit. Bug fixes add regression tests in `tests/regressions/`. Coverage threshold: 70%. **Why:** Untested code causes silent regressions in background loops.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAM","title":"Write unit tests before committing code changes","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643943+00:00","updated_at":"2026-05-03T04:19:35.643943+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Kill-switch testing pattern for background loops

Every `BaseBackgroundLoop` subclass needs a unit test that asserts disabling the loop short-circuits `_do_work` to `{'status': 'disabled'}` without side effects. Construct `LoopDeps` with `enabled_cb=lambda name: name != '<worker_name>'`; mock dependent methods with `AsyncMock(side_effect=AssertionError(...))`; await `_do_work()`. **Why:** Ensures disabled loops don't execute business logic.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAN","title":"Kill-switch testing pattern for background loops","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643948+00:00","updated_at":"2026-05-03T04:19:35.643949+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Cassette-based fake adapter contract testing

Fake adapters in `tests/scenarios/fakes/` record cassettes against live github/git/docker/claude, normalize volatile fields (timestamps, PR numbers, SHAs), and replay via `tests/trust/contracts/_replay.py`. Cassettes are Pydantic v2 YAML for github/git/docker; .jsonl streams for claude. **Why:** Cassettes catch API contract drift that mocks miss.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAP","title":"Cassette-based fake adapter contract testing","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643954+00:00","updated_at":"2026-05-03T04:19:35.643955+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Meta-observability with bounded recursion via trust fleet

TrustFleetSanityLoop monitors 9 trust loops for anomalies: issues_per_hour, repair_ratio, tick_error_ratio, staleness, cost_spike. HealthMonitorLoop is the dead-man-switch watching TrustFleetSanityLoop. Recursion is bounded because trust-loop set is frozen and HealthMonitorLoop is outside the trust-fleet floor. **Why:** Unbounded recursion breaks observability.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAQ","title":"Meta-observability with bounded recursion via trust fleet","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643960+00:00","updated_at":"2026-05-03T04:19:35.643961+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## MockWorld fixture composes all external fakes into controllable environment

Wire FakeGitHub, FakeLLM, FakeHindsight, FakeWorkspace, FakeSentry, FakeClock as stateful in-memory fakes (not AsyncMock). Expose fluent API: `world.add_issue()`, `world.set_phase_result()`, `world.fail_service()`, `await world.run_pipeline()`. Assertions inspect final state directly. **Why:** Stateful fakes catch behavioral bugs AsyncMock misses.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAR","title":"MockWorld fixture composes all external fakes into controllable environment","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643970+00:00","updated_at":"2026-05-03T04:19:35.643971+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Scenario tests are additive to unit and integration tests

Unit tests (9K+) test individual functions. Integration tests (`PipelineHarness`) test phase wiring with mocked runners. Scenario tests test complete flows with stateful fakes. All three tiers coexist; scenario tests don't replace the others. **Why:** Each tier catches different bug classes.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAS","title":"Scenario tests are additive to unit and integration tests","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643976+00:00","updated_at":"2026-05-03T04:19:35.643977+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Run scenario tests with make scenario and make scenario-loops

Execute `make scenario` for pipeline scenarios (`pytest -m scenario`) and `make scenario-loops` for background loop scenarios (`pytest -m scenario_loops`). Both are included in `make quality`. **Why:** CI needs explicit markers to run scenario tests in gates.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAT","title":"Run scenario tests with make scenario and make scenario-loops","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643981+00:00","updated_at":"2026-05-03T04:19:35.643982+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Caretaker-loop Pattern A: catalog-driven invocation

Use `await world.run_with_loops(["loop_name"], cycles=1)` when the loop is registered in `tests/scenarios/catalog/loop_registrations.py`. Minimal boilerplate; works with default catalog config. **Why:** Avoids manual loop instantiation and dependency wiring.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAV","title":"Caretaker-loop Pattern A: catalog-driven invocation","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643987+00:00","updated_at":"2026-05-03T04:19:35.643988+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Caretaker-loop Pattern B: direct instantiation with config overrides

Use `_make_loop_deps(world, config_overrides={...})` and construct the loop class directly when: config flags differ from catalog defaults, or loop is not yet registered. See: `tests/helpers.py:_make_loop_deps`. **Why:** Enables testing with custom config without modifying the catalog.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAW","title":"Caretaker-loop Pattern B: direct instantiation with config overrides","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.643994+00:00","updated_at":"2026-05-03T04:19:35.643995+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Test concurrent file operations with deterministic iteration counts

Test concurrent file operations using `concurrent.futures.ThreadPoolExecutor` with fixed thread counts and deterministic iterations (e.g., 10 threads × 20 events = 200 total). Assert exact event counts. POSIX guarantees atomicity for writes under ~4KB, so concurrent appends should be safe—validate empirically. **Why:** Timing-based assertions are flaky; iteration counts are deterministic.


```json:entry
{"id":"01KQP10AJV73YGEATZKR6QXCAX","title":"Test concurrent file operations with deterministic iteration counts","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.644000+00:00","updated_at":"2026-05-03T04:19:35.644001+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Memory bank deduplication uses priority mapping

Priority: LEARNINGS=5, TROUBLESHOOTING=4, RETROSPECTIVES=3, REVIEW_INSIGHTS=2, HARNESS_INSIGHTS=1. When duplicates collide, higher-priority item survives. Bank keys must be consistent across dedup and assembly pipelines. Fallback recall tries multiple field names: `learning`, `text`, `content`, `display_text`, `description`. **Why:** Inconsistent keys silently miss banks during dedup.


```json:entry
{"id":"01KQP10AJW53QXTDM9KK5BS54A","title":"Memory bank deduplication uses priority mapping","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.644008+00:00","updated_at":"2026-05-03T04:19:35.644010+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Skill definition replication requires 4 backend consistency

HydraFlow skills replicate across 4 backends: .claude/commands/, .pi/skills/, .codex/skills/, src/*.py. Use manual SKILL_MARKERS mapping to validate all copies contain matching output markers. Consistency tests check marker presence via substring search. Each skill change requires updating all 4 copies. **Why:** Divergent copies cause silent skill failures in some execution contexts.


```json:entry
{"id":"01KQP10AJW53QXTDM9KK5BS54B","title":"Skill definition replication requires 4 backend consistency","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.644016+00:00","updated_at":"2026-05-03T04:19:35.644016+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Cross-location key consistency is critical for data pipelines

Memory deduplication and skill replication depend on consistent naming across locations. If location names or field names differ, data is silently missed. Verify bank_order keys match dict keys and skill markers match across 4 backends with identical text. **Why:** Silent misses during validation or deduplication break trust in the system.


```json:entry
{"id":"01KQP10AJW53QXTDM9KK5BS54C","title":"Cross-location key consistency is critical for data pipelines","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.644023+00:00","updated_at":"2026-05-03T04:19:35.644024+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Feature toggle implementation requires config field + ENV override

Feature toggles need both: (1) config field definition in `src/config.py`, (2) `_ENV_INT_OVERRIDES` entry for env-var override. Both are necessary for runtime configurability. Test both default value and environment-variable override behavior. **Why:** Incomplete toggles cannot be controlled at runtime.


```json:entry
{"id":"01KQP10AJW53QXTDM9KK5BS54D","title":"Feature toggle implementation requires config field + ENV override","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:19:35.644031+00:00","updated_at":"2026-05-03T04:19:35.644032+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Test pyramid — three layers, all required for load-bearing features

Every load-bearing feature ships through unit + MockWorld scenario + sandbox e2e tests before merging to staging. Skipping a layer is a procedural failure, not a judgment call. Unit tests catch code-path bugs but are blind to real-API behavior; MockWorld scenarios catch loop-integration bugs unit tests can't see; sandbox e2e tests catch the docker / wiring / UI layer that MockWorld can't reach. See [`docs/standards/testing/README.md`](../standards/testing/README.md) for the canonical reference: when each layer is required, how to write each (Pattern A full-MockWorld vs Pattern B direct-instantiation), and the anti-patterns (asserting against non-existent state shapes; module-level `import pytest` in sandbox scenarios; "this feature is too small for scenario tests" rationalisation).

**Why:** PR #8482 (rebase-on-conflict) shipped with only unit tests and was caught by the question "did you test it all?". The MockWorld and sandbox layers were added in a follow-up. The standard exists so this doesn't recur.


```json:entry
{"id":"01KQTESTPYRAMID2026B0PHASE3","title":"Test pyramid — three layers, all required for load-bearing features","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-07T05:30:00.000000+00:00","updated_at":"2026-05-07T05:30:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```
