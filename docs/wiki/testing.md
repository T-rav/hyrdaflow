# Testing

## Core Testing Strategy and Design for Testability



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

```json:entry
{"id":"01KQ11A4GE861157N0A89NAN4P","title":"Core Testing Strategy and Design for Testability","content":"Function structure limits: Enforce 50-line limit on handler functions and 30-line limit on registration wiring; extract nested closures into instance methods to flatten nesting to ≤3 levels.\n\nMocking strategy: Mock at definition site, not usage site. For module-level imports, patch the assignment; for deferred imports, patch the definition module. For optional dependencies (sentry_sdk), use `unittest.mock.patch.dict(\"sys.modules\", ...)` to guarantee cleanup. Mock sub-modules explicitly (both 'sentry_sdk' and 'sentry_sdk.integrations'). Mock return values must use identical keys and structure as actual TypedDict definitions.\n\nIntegration testing markers: Mark tests `@pytest.mark.integration` only if they exercise real external dependencies (Docker, network, filesystem, worktrees, service instances). Tests with `spec=AsyncMock` for all deps are unit/functional. Use `pytest.mark.skipif` with `shutil.which()` for optional CLI tools.\n\nAsync patterns: Use `AsyncMock` with explicit `assert_called_with()`. For fire-and-forget tasks via `create_task()`, call `await asyncio.sleep(0)` before assertions. Test async context managers in three scenarios: idempotent close, context manager triggers close on exit, returns self. Verify fatal exceptions propagate through multi-phase loops by mocking internal methods to raise specific types.\n\nSubprocess/CLI testing: Create small Python scripts acting as CLI stand-ins, logging invocations to JSON-lines files for post-hoc assertions.\n\nConftest and fixtures: Session-scoped fixtures load before test modules. Use conftest.py as single source of truth for sys.path manipulation and autouse fixtures for state cleanup. Global/module-level state (e.g., `_gh_semaphore`, `_rate_limit_until`) must be reset completely in both setup and teardown. File-based test I/O must use `tmp_path` fixture with `ConfigFactory.create()` to avoid polluting project state. Export additive seed state variants (e.g., `seedStateWithHumanInput`) from conftest.py. Verify sys.modules cleanup with `pytest --randomly-seed` using multiple seeds.\n\nIntegration testing with phase runners: Wire real business logic (StateTracker, EventBus, VerificationJudge, RetrospectiveCollector) but mock only the `_execute()` subprocess boundary. Provide configurable transcript strings for real runner parsing, exposing mismatches fully-mocked runners hide. Validate state via StateTracker APIs and EventBus.get_history().\n\nProtocol satisfaction: Use two complementary approaches: (1) Structural typing with `isinstance(concrete_instance, ProtocolName)` and `@runtime_checkable` to ensure contract satisfaction; (2) Duck-typing assertions using `hasattr(obj, 'method_name')` for loose coupling. Use `inspect.signature()` comparison to catch parameter drift. Parametrize tests for each protocol method.\n\nFaçaded refactors: Verify `__getattr__` correctly routes methods to sub-clients, raises `AttributeError` for nonexistent methods, the façade satisfies protocols via delegation, and existing tests that mock the original class still work. Sub-components receive mutable dict/set references (not copies) to shared state owned by the facade.\n\nTesting during refactoring: When extracting private methods with unchanged public API, existing tests provide complete coverage (no new tests needed). When extracting prompt-building methods, run prompt-assertion tests in isolation immediately after extraction. Parameter renames are low-risk when all callers use positional arguments. For dead code removal, update all related test classes and helpers. When refactoring duplicated code, keep existing tests as regression checks. For documenting known broken behavior, use `@pytest.mark.skip(reason=\"documenting bug: [issue number]\")` for removal after fix.\n\nTelemetry and Sentry testing: Use `patch.dict(\"sys.modules\", ...)` to mock sentry_sdk imports, then assert actual numeric values in breadcrumbs/metrics, not just presence of keys. When testing log output with pytest's `caplog` fixture, always specify exact logger name: `caplog.at_level(level, logger=\"module.name\")`. Clear caplog before the action and assert on message substrings specific to logged values.\n\nAssertion and test precision: For AST-based regression tests, parse source file ASTs to verify code structure assertions, allowing ±3 line drift tolerance. Tests asserting exact query strings are brittle; instead assert that specific key terms appear. Use f-strings to embed constants in assertions. Use `is` operator to verify runners share the same subprocess_runner instance. Substring matching in coverage checks produces false positives when short names collide; use word-boundary or full-name matching.\n\nFrontend and browser testing: Server-side rendering via Django/FastAPI TestClient only sees the initial HTML shell, not attributes rendered by JavaScript. Accessibility attributes like `aria-labelledby` and other client-rendered properties require Playwright or browser-based testing. Dead Python tests attempting to verify these should be deleted in favor of browser-based tests. Browser tests are slower than TestClient but catch rendering-specific bugs that server-side tests miss. Organize browser test fixtures (e.g., `seedStateWithHumanInput`) in conftest.py for reuse.\n\nSee also: Type System and Data Model Consistency Testing — mock return values must match TypedDict structure.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T14:53:08.908932+00:00","updated_at":"2026-04-18T14:53:08.908940+00:00","valid_from":"2026-04-18T14:53:08.908932+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Type System and Data Model Consistency Testing



Schema evolution and field synchronization: Global singletons like `_event_counter` are shared across all instances. Tests must never assert on absolute ID values—only on relative ordering and uniqueness within a single test. This prevents test pollution and ensures event ordering is the actual concern. Before property-based tests exercise a transition graph, add structural tests: every target is a valid stage, every stage has a transition entry, no dangling references. Test constants (`ALL_PIPELINE_LABELS`, `VALID_STAGES`, `VALID_TRANSITIONS`) serve as both test oracles and executable documentation—keep them synchronized. Direct-swap labels (hitl-active, hitl-autofix, fixed, verify) are set via `swap_pipeline_labels()` calls, not transitions. STAGE_ORDER gates full lifecycle tests; new stages require STAGE_ORDER updates. Test both EVENT_TYPE_TO_STAGE and SOURCE_TO_STAGE paths independently. When related data structures must stay in sync, add dedicated sync tests asserting set equality via dynamic field extraction. Use `len(LABELS) == 13` instead of hardcoding. Validate explicitly that each label field is present in `all_pipeline_labels`.

Model and TypedDict field changes: Adding fields to Pydantic models or TypedDict structures breaks tests with exact field sets or exact equality assertions. Required updates: model definition, test factory defaults, field assertions in all_fields tests, state assertions, serialization/deserialization round-trips. Grep the test suite for each model name before committing. For TypedDict fields marked `NotRequired`, update exact-match assertions but not missing-key assertions. When changing internal dict key types (e.g., `int` → `str`), test both old format and new format loading without crashes. When narrowing field types with validators, accept empty strings explicitly to preserve backward compatibility. When adding Literal constraints to Pydantic fields, test both valid and invalid values. Use `total=False` Pydantic models to conditionally include fields like `verdict` and `duration` only when provided (non-None), not as None values.

Type annotation changes: TypedDicts are dicts at runtime, so existing test assertions work identically. Migrating from dict[str, Any] to TypedDict returns requires no test changes—the value is purely in static type validation. When narrowing function parameter types from `Any` to specific types, callers passing `Any`-typed values will still type-check successfully. `Any` is compatible with all types in pyright, enabling safe gradual type annotation migrations. Type annotation changes without runtime behavior modifications can be verified entirely through existing test suites and type checkers; new test additions are unnecessary. Verify via `make quality-lite` and `make test`.

Feature toggle implementation: Feature toggles require both a config field definition in `src/config.py` AND an `_ENV_INT_OVERRIDES` entry to support environment-variable override. Both are necessary for the toggle to be runtime-configurable. Each toggle field must be tested for both default value and environment-variable override behavior.

See also: Core Testing Strategy and Design for Testability — mock return values must match TypedDict structure.

```json:entry
{"id":"01KQ11A4GE861157N0A89NAN4Q","title":"Type System and Data Model Consistency Testing","content":"Schema evolution and field synchronization: Global singletons like `_event_counter` are shared across all instances. Tests must never assert on absolute ID values—only on relative ordering and uniqueness within a single test. This prevents test pollution and ensures event ordering is the actual concern. Before property-based tests exercise a transition graph, add structural tests: every target is a valid stage, every stage has a transition entry, no dangling references. Test constants (`ALL_PIPELINE_LABELS`, `VALID_STAGES`, `VALID_TRANSITIONS`) serve as both test oracles and executable documentation—keep them synchronized. Direct-swap labels (hitl-active, hitl-autofix, fixed, verify) are set via `swap_pipeline_labels()` calls, not transitions. STAGE_ORDER gates full lifecycle tests; new stages require STAGE_ORDER updates. Test both EVENT_TYPE_TO_STAGE and SOURCE_TO_STAGE paths independently. When related data structures must stay in sync, add dedicated sync tests asserting set equality via dynamic field extraction. Use `len(LABELS) == 13` instead of hardcoding. Validate explicitly that each label field is present in `all_pipeline_labels`.\n\nModel and TypedDict field changes: Adding fields to Pydantic models or TypedDict structures breaks tests with exact field sets or exact equality assertions. Required updates: model definition, test factory defaults, field assertions in all_fields tests, state assertions, serialization/deserialization round-trips. Grep the test suite for each model name before committing. For TypedDict fields marked `NotRequired`, update exact-match assertions but not missing-key assertions. When changing internal dict key types (e.g., `int` → `str`), test both old format and new format loading without crashes. When narrowing field types with validators, accept empty strings explicitly to preserve backward compatibility. When adding Literal constraints to Pydantic fields, test both valid and invalid values. Use `total=False` Pydantic models to conditionally include fields like `verdict` and `duration` only when provided (non-None), not as None values.\n\nType annotation changes: TypedDicts are dicts at runtime, so existing test assertions work identically. Migrating from dict[str, Any] to TypedDict returns requires no test changes—the value is purely in static type validation. When narrowing function parameter types from `Any` to specific types, callers passing `Any`-typed values will still type-check successfully. `Any` is compatible with all types in pyright, enabling safe gradual type annotation migrations. Type annotation changes without runtime behavior modifications can be verified entirely through existing test suites and type checkers; new test additions are unnecessary. Verify via `make quality-lite` and `make test`.\n\nFeature toggle implementation: Feature toggles require both a config field definition in `src/config.py` AND an `_ENV_INT_OVERRIDES` entry to support environment-variable override. Both are necessary for the toggle to be runtime-configurable. Each toggle field must be tested for both default value and environment-variable override behavior.\n\nSee also: Core Testing Strategy and Design for Testability — mock return values must match TypedDict structure.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T14:53:08.908950+00:00","updated_at":"2026-04-18T14:53:08.908951+00:00","valid_from":"2026-04-18T14:53:08.908950+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Multi-Location Consistency and Concurrent File I/O Testing



Concurrent file operations: Test concurrent file operations using `concurrent.futures.ThreadPoolExecutor` with fixed thread counts and deterministic iterations (e.g., 10 threads × 20 events = 200 total). Assert exact event counts rather than timing. `append_jsonl` has no file locking, but POSIX guarantees atomicity for writes under ~4KB (pipe buffer). Each JSON line is well under 4KB, so concurrent appends should be safe—validate empirically. If concurrent appends produce corrupt lines, locking or buffering becomes necessary.

Memory deduplication and bank consistency: Memory deduplication uses a priority mapping: LEARNINGS (memory) = 5, TROUBLESHOOTING = 4, RETROSPECTIVES = 3, REVIEW_INSIGHTS = 2, HARNESS_INSIGHTS = 1. When two near-duplicate items collide, the higher-priority bank's item survives. Bank key consistency across dedup and assembly pipelines is critical—if `bank_order` uses different key names than dict keys, banks will be silently missed. Use consistent string keys throughout (memory, troubleshooting, review_insights, etc.). Different memory banks use different JSONL record formats. Fallback recall functions must try multiple field names (`learning`, `text`, `content`, `display_text`, `description`) to extract the text payload.

Skill definition multi-location replication: HydraFlow skills are replicated across 4 backend locations (.claude/commands/, .pi/skills/, .codex/skills/, src/*.py). Use a manual SKILL_MARKERS mapping (not regex introspection) to validate that all copies contain matching output markers. Consistency tests should check marker presence via substring search to tolerate minor markdown structure differences across backends. Each skill removal or addition requires updating all test fixtures and assertions across multiple test files—a single skill change can require updates across 3+ test files. Before committing skill changes, verify that all 4 backend copies have been updated with consistent marker text.

Cross-location key consistency principle: Both memory deduplication and skill definition replication depend on consistent naming across multiple locations. If location names or field names differ across copies, data will be silently missed during validation or deduplication. Always verify that bank_order keys match dict keys and skill markers are present in all 4 backend copies with identical text.

```json:entry
{"id":"01KQ11A4GE861157N0A89NAN4R","title":"Multi-Location Consistency and Concurrent File I/O Testing","content":"Concurrent file operations: Test concurrent file operations using `concurrent.futures.ThreadPoolExecutor` with fixed thread counts and deterministic iterations (e.g., 10 threads × 20 events = 200 total). Assert exact event counts rather than timing. `append_jsonl` has no file locking, but POSIX guarantees atomicity for writes under ~4KB (pipe buffer). Each JSON line is well under 4KB, so concurrent appends should be safe—validate empirically. If concurrent appends produce corrupt lines, locking or buffering becomes necessary.\n\nMemory deduplication and bank consistency: Memory deduplication uses a priority mapping: LEARNINGS (memory) = 5, TROUBLESHOOTING = 4, RETROSPECTIVES = 3, REVIEW_INSIGHTS = 2, HARNESS_INSIGHTS = 1. When two near-duplicate items collide, the higher-priority bank's item survives. Bank key consistency across dedup and assembly pipelines is critical—if `bank_order` uses different key names than dict keys, banks will be silently missed. Use consistent string keys throughout (memory, troubleshooting, review_insights, etc.). Different memory banks use different JSONL record formats. Fallback recall functions must try multiple field names (`learning`, `text`, `content`, `display_text`, `description`) to extract the text payload.\n\nSkill definition multi-location replication: HydraFlow skills are replicated across 4 backend locations (.claude/commands/, .pi/skills/, .codex/skills/, src/*.py). Use a manual SKILL_MARKERS mapping (not regex introspection) to validate that all copies contain matching output markers. Consistency tests should check marker presence via substring search to tolerate minor markdown structure differences across backends. Each skill removal or addition requires updating all test fixtures and assertions across multiple test files—a single skill change can require updates across 3+ test files. Before committing skill changes, verify that all 4 backend copies have been updated with consistent marker text.\n\nCross-location key consistency principle: Both memory deduplication and skill definition replication depend on consistent naming across multiple locations. If location names or field names differ across copies, data will be silently missed during validation or deduplication. Always verify that bank_order keys match dict keys and skill markers are present in all 4 backend copies with identical text.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T14:53:08.908953+00:00","updated_at":"2026-04-18T14:53:08.908955+00:00","valid_from":"2026-04-18T14:53:08.908953+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## ADR Testing Patterns: Conservative Pattern Matching and Validation



Extract only high-confidence invariant patterns (4 baseline: uniqueness, usage, negative, coverage) from ADR Decision sections. Generate all tests with `@pytest.mark.skip(reason="skeleton: requires human review")` by default, deferring validation to humans. This prevents over-matching ambiguous language while supporting future pattern refinement.

ADR validation: ADRs must pass `tests/test_adr_pre_validator.py` which enforces required sections (Status, Context, Decision, Consequences), valid status values, and correct markdown formatting. Validate that each ADR's status is one of: Proposed, Accepted, Deprecated, Superseded. Markdown formatting must follow the standard ADR template.

```json:entry
{"id":"01KQ11A4GE861157N0A89NAN4S","title":"ADR Testing Patterns: Conservative Pattern Matching and Validation","content":"Extract only high-confidence invariant patterns (4 baseline: uniqueness, usage, negative, coverage) from ADR Decision sections. Generate all tests with `@pytest.mark.skip(reason=\"skeleton: requires human review\")` by default, deferring validation to humans. This prevents over-matching ambiguous language while supporting future pattern refinement.\n\nADR validation: ADRs must pass `tests/test_adr_pre_validator.py` which enforces required sections (Status, Context, Decision, Consequences), valid status values, and correct markdown formatting. Validate that each ADR's status is one of: Proposed, Accepted, Deprecated, Superseded. Markdown formatting must follow the standard ADR template.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T14:53:08.908957+00:00","updated_at":"2026-04-18T14:53:08.908958+00:00","valid_from":"2026-04-18T14:53:08.908957+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Meta-Observability with Bounded Recursion



Trust loops watch managed work; the meta-observer watches trust loops; the dead-man-switch watches the meta-observer (ADR-0046). One bounded meta-layer — no meta-meta. TrustFleetSanityLoop monitors the 9 trust loops (corpus_learning, contract_refresh, staging_bisect, principles_audit, flake_tracker, skill_prompt_eval, fake_coverage_auditor, rc_budget, wiki_rot_detector — itself explicitly excluded) for 5 anomaly kinds: issues_per_hour, repair_ratio, tick_error_ratio, staleness, cost_spike. Files hitl-escalation + trust-loop-anomaly issues per anomaly. HealthMonitorLoop._check_sanity_loop_staleness is the dead-man-switch — fires if TrustFleetSanityLoop hasn't ticked in >= 3× its configured interval. Recursion is bounded because (a) TRUST_LOOP_WORKERS is a frozen list verified by test_trust_loop_workers_contains_nine_spec_workers; (b) HealthMonitorLoop is not a 'trust loop' subject to sanity-loop watching — it pre-dates trust-fleet and watches trust-fleet from outside. Every operability question above the trust-fleet floor is answerable at /api/trust/fleet (per-loop ticks, errors, escalations, cost; anomalies_recent; escape_closure success metric). See also: Trust Fleet Pattern; Kill-Switch Convention.

```json:entry
{"id":"01KQ11A4G670SNNXM1DDZ98XJ3","title":"Meta-Observability with Bounded Recursion","content":"Trust loops watch managed work; the meta-observer watches trust loops; the dead-man-switch watches the meta-observer (ADR-0046). One bounded meta-layer — no meta-meta. TrustFleetSanityLoop monitors the 9 trust loops (corpus_learning, contract_refresh, staging_bisect, principles_audit, flake_tracker, skill_prompt_eval, fake_coverage_auditor, rc_budget, wiki_rot_detector — itself explicitly excluded) for 5 anomaly kinds: issues_per_hour, repair_ratio, tick_error_ratio, staleness, cost_spike. Files hitl-escalation + trust-loop-anomaly issues per anomaly. HealthMonitorLoop._check_sanity_loop_staleness is the dead-man-switch — fires if TrustFleetSanityLoop hasn't ticked in >= 3× its configured interval. Recursion is bounded because (a) TRUST_LOOP_WORKERS is a frozen list verified by test_trust_loop_workers_contains_nine_spec_workers; (b) HealthMonitorLoop is not a 'trust loop' subject to sanity-loop watching — it pre-dates trust-fleet and watches trust-fleet from outside. Every operability question above the trust-fleet floor is answerable at /api/trust/fleet (per-loop ticks, errors, escalations, cost; anomalies_recent; escape_closure success metric). See also: Trust Fleet Pattern; Kill-Switch Convention.","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:40:54.022865+00:00","updated_at":"2026-04-25T00:40:54.022866+00:00","valid_from":"2026-04-25T00:40:54.022865+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Cassette-Based Fake Adapter Contract Testing



Fake adapters in tests/scenarios/fakes/ avoid AsyncMock fragility by recording cassettes against live github/git/docker/claude (ADR-0047), normalizing volatile fields (timestamps, PR numbers, SHAs), and replaying them in tests via tests/trust/contracts/_replay.py. Cassettes are Pydantic v2 YAML files (Cassette model in _schema.py) for github/git/docker; .jsonl streams for claude (which has hundreds of events per stream and a different normalization model — _canonical_jsonl in src/contract_diff.py). ContractRefreshLoop weekly: re-records → detect_fleet_drift → if drift, opens auto-merge PR labeled `contract-refresh`; the replay gate (300s subprocess timeout) verifies the refreshed cassettes still match fake behavior before merge. FakeCoverageAuditorLoop scans Fake* classes and flags methods that have no cassette (adapter-surface gaps) and helpers no scenario uses (test-helper gaps). See also: MockWorld Scenario Pattern; Trust Fleet Pattern.

```json:entry
{"id":"01KQ11A4G670SNNXM1DDZ98XJ4","title":"Cassette-Based Fake Adapter Contract Testing","content":"Fake adapters in tests/scenarios/fakes/ avoid AsyncMock fragility by recording cassettes against live github/git/docker/claude (ADR-0047), normalizing volatile fields (timestamps, PR numbers, SHAs), and replaying them in tests via tests/trust/contracts/_replay.py. Cassettes are Pydantic v2 YAML files (Cassette model in _schema.py) for github/git/docker; .jsonl streams for claude (which has hundreds of events per stream and a different normalization model — _canonical_jsonl in src/contract_diff.py). ContractRefreshLoop weekly: re-records → detect_fleet_drift → if drift, opens auto-merge PR labeled `contract-refresh`; the replay gate (300s subprocess timeout) verifies the refreshed cassettes still match fake behavior before merge. FakeCoverageAuditorLoop scans Fake* classes and flags methods that have no cassette (adapter-surface gaps) and helpers no scenario uses (test-helper gaps). See also: MockWorld Scenario Pattern; Trust Fleet Pattern.","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:40:54.022872+00:00","updated_at":"2026-04-25T00:40:54.022873+00:00","valid_from":"2026-04-25T00:40:54.022872+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Kill-Switch Tests — Direct _do_work Invocation



Per ADR-0049, every BaseBackgroundLoop subclass needs a unit test that asserts disabling the loop short-circuits _do_work to {'status': 'disabled'} without side effects. Test pattern: construct LoopDeps with enabled_cb=lambda name: name != '<worker_name>'; build the loop; mock dependent methods with AsyncMock(side_effect=AssertionError('must not run when disabled')); await loop._do_work() and assert the return dict equals {'status': 'disabled'}. The base class's run() loop has its own gate but the in-body check is what unit tests can deterministically exercise. Pattern lives in tests/test_<loop>_loop.py::test_kill_switch_short_circuits_do_work for all 10 trust loops + health_monitor + ci_monitor (added in #8390 + #8416). See also: Kill-Switch Convention; DedupStore + Reconcile Pattern.

```json:entry
{"id":"01KQ11A4G670SNNXM1DDZ98XJ7","title":"Kill-Switch Tests — Direct _do_work Invocation","content":"Per ADR-0049, every BaseBackgroundLoop subclass needs a unit test that asserts disabling the loop short-circuits _do_work to {'status': 'disabled'} without side effects. Test pattern: construct LoopDeps with enabled_cb=lambda name: name != '<worker_name>'; build the loop; mock dependent methods with AsyncMock(side_effect=AssertionError('must not run when disabled')); await loop._do_work() and assert the return dict equals {'status': 'disabled'}. The base class's run() loop has its own gate but the in-body check is what unit tests can deterministically exercise. Pattern lives in tests/test_<loop>_loop.py::test_kill_switch_short_circuits_do_work for all 10 trust loops + health_monitor + ci_monitor (added in #8390 + #8416). See also: Kill-Switch Convention; DedupStore + Reconcile Pattern.","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:40:54.022902+00:00","updated_at":"2026-04-25T00:40:54.022903+00:00","valid_from":"2026-04-25T00:40:54.022902+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Pydantic field additions without updating serialization tests



When you add a field to any model in `src/models.py` (e.g., `PRListItem`, `StateData`), grep `tests/` for the model name and update ALL exact-match serialization tests.

- `model_dump()` assertions
- Expected key sets in smoke tests
- Any `assert result == {...}` that hard-codes the full model shape

**Why:** HydraFlow has strict exact-match tests that assert on the complete serialized dict. A new field breaks them silently during unrelated refactors, and CI flags it later as a mysterious regression.

**How to check:** After editing `models.py`, run `rg "<ModelName>" tests/` and confirm every match still passes.

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBB","title":"Pydantic field additions without updating serialization tests","content":"When you add a field to any model in `src/models.py` (e.g., `PRListItem`, `StateData`), grep `tests/` for the model name and update ALL exact-match serialization tests.\n\n- `model_dump()` assertions\n- Expected key sets in smoke tests\n- Any `assert result == {...}` that hard-codes the full model shape\n\n**Why:** HydraFlow has strict exact-match tests that assert on the complete serialized dict. A new field breaks them silently during unrelated refactors, and CI flags it later as a mysterious regression.\n\n**How to check:** After editing `models.py`, run `rg \"<ModelName>\" tests/` and confirm every match still passes.","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793211+00:00","updated_at":"2026-04-25T00:47:19.793212+00:00","valid_from":"2026-04-25T00:47:19.793211+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Falsy checks on optional objects



Never write `if not self._hindsight` to test whether an optional object is present. Falsy checks can fire unexpectedly on mock objects, empty collections, and objects that implement `__bool__`.

**Wrong:**

```python
if not self._hindsight:
    return None
```

**Right:**

```python
if self._hindsight is None:
    return None
```

**Why:** `Mock()` objects are truthy by default, but a `Mock()` configured with `spec=SomeClass` that has `__bool__` can be falsy, and ordinary values like empty lists or dicts trigger the wrong branch. Explicit `is None` makes the intent unambiguous and matches the type annotation contract (`X | None`).

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBF","title":"Falsy checks on optional objects","content":"Never write `if not self._hindsight` to test whether an optional object is present. Falsy checks can fire unexpectedly on mock objects, empty collections, and objects that implement `__bool__`.\n\n**Wrong:**\n\n```python\nif not self._hindsight:\n    return None\n```\n\n**Right:**\n\n```python\nif self._hindsight is None:\n    return None\n```\n\n**Why:** `Mock()` objects are truthy by default, but a `Mock()` configured with `spec=SomeClass` that has `__bool__` can be falsy, and ordinary values like empty lists or dicts trigger the wrong branch. Explicit `is None` makes the intent unambiguous and matches the type annotation contract (`X | None`).","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793246+00:00","updated_at":"2026-04-25T00:47:19.793247+00:00","valid_from":"2026-04-25T00:47:19.793246+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Writing a new test helper without checking conftest



Before adding a helper function to a test file, grep `tests/conftest.py` (and any `tests/helpers*.py`) for similar helpers. Shared test fixtures belong in conftest; duplicating a helper locally causes drift when one copy is updated and the other is not.

**Wrong:**

```python
# tests/test_my_feature.py
def _write_fake_skill(cache_root, marketplace, plugin, skill):
    skill_dir = cache_root / marketplace / plugin / "1.0.0" / "skills" / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {skill}\n---\nbody\n")
```

(while `tests/conftest.py:write_plugin_skill` already does exactly this.)

**Right:**

```python
# tests/test_my_feature.py
from tests.conftest import write_plugin_skill
```

**Why:** Duplicated helpers drift silently. If `write_plugin_skill` in conftest gains a new parameter or changes its on-disk layout, the local copy stays stale and tests pass against a fiction.

**How to check:** Before adding any `def _<something>` in a test file, run `rg "def <name>" tests/conftest.py tests/helpers*.py` for semantically-similar helpers.

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBH","title":"Writing a new test helper without checking conftest","content":"Before adding a helper function to a test file, grep `tests/conftest.py` (and any `tests/helpers*.py`) for similar helpers. Shared test fixtures belong in conftest; duplicating a helper locally causes drift when one copy is updated and the other is not.\n\n**Wrong:**\n\n```python\n# tests/test_my_feature.py\ndef _write_fake_skill(cache_root, marketplace, plugin, skill):\n    skill_dir = cache_root / marketplace / plugin / \"1.0.0\" / \"skills\" / skill\n    skill_dir.mkdir(parents=True, exist_ok=True)\n    (skill_dir / \"SKILL.md\").write_text(f\"---\\nname: {skill}\\n---\\nbody\\n\")\n```\n\n(while `tests/conftest.py:write_plugin_skill` already does exactly this.)\n\n**Right:**\n\n```python\n# tests/test_my_feature.py\nfrom tests.conftest import write_plugin_skill\n```\n\n**Why:** Duplicated helpers drift silently. If `write_plugin_skill` in conftest gains a new parameter or changes its on-disk layout, the local copy stays stale and tests pass against a fiction.\n\n**How to check:** Before adding any `def _<something>` in a test file, run `rg \"def <name>\" tests/conftest.py tests/helpers*.py` for semantically-similar helpers.","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793259+00:00","updated_at":"2026-04-25T00:47:19.793260+00:00","valid_from":"2026-04-25T00:47:19.793259+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Test Environment Setup and Scaffolding



```bash
make setup          # Install hooks, assets, config, labels
make prep           # Sync agent assets + run full repo prep (labels, audit, CI/tests)
make scaffold       # Generate baseline tests and CI configuration only (no asset sync)
make ensure-labels  # Create HydraFlow lifecycle labels
make deps           # Sync dependencies via uv
```

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBW","title":"Setup and scaffolding","content":"```bash\nmake setup          # Install hooks, assets, config, labels\nmake prep           # Sync agent assets + run full repo prep (labels, audit, CI/tests)\nmake scaffold       # Generate baseline tests and CI configuration only (no asset sync)\nmake ensure-labels  # Create HydraFlow lifecycle labels\nmake deps           # Sync dependencies via uv\n```","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793459+00:00","updated_at":"2026-04-25T00:47:19.793459+00:00","valid_from":"2026-04-25T00:47:19.793459+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Quick validation loop



```bash
# After small changes
make lint && make test

# Before committing
make quality
```

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PC2","title":"Quick validation loop","content":"```bash\n# After small changes\nmake lint && make test\n\n# Before committing\nmake quality\n```","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793548+00:00","updated_at":"2026-04-25T00:47:19.793549+00:00","valid_from":"2026-04-25T00:47:19.793548+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Quality Gates



**Always run lint and tests before declaring work complete or committing.** Do not present implementation as "done" until quality checks pass.

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PC0","title":"Quality Gates","content":"**Always run lint and tests before declaring work complete or committing.** Do not present implementation as \"done\" until quality checks pass.","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793537+00:00","updated_at":"2026-04-25T00:47:19.793538+00:00","valid_from":"2026-04-25T00:47:19.793537+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Required Testing Coverage and Validation



**ALWAYS write unit tests for code changes before committing.** Every new function, class, or feature modification MUST include comprehensive tests.

- Tests live in `tests/` following the pattern `tests/test_<module>.py`
- New features: Write tests BEFORE committing
- Bug fixes: Add regression tests that reproduce the bug
- Refactoring: Ensure existing tests pass, add tests for new paths
- Never commit untested code
- Coverage threshold: **70%**

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PCB","title":"Testing Is Mandatory","content":"**ALWAYS write unit tests for code changes before committing.** Every new function, class, or feature modification MUST include comprehensive tests.\n\n- Tests live in `tests/` following the pattern `tests/test_<module>.py`\n- New features: Write tests BEFORE committing\n- Bug fixes: Add regression tests that reproduce the bug\n- Refactoring: Ensure existing tests pass, add tests for new paths\n- Never commit untested code\n- Coverage threshold: **70%**","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793713+00:00","updated_at":"2026-04-25T00:47:19.793715+00:00","valid_from":"2026-04-25T00:47:19.793713+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## ADR testing rules



- **Never write tests for ADR markdown content.** ADRs are documentation, not code. Do not create `test_adr_NNNN_*.py` files that assert on markdown headings, status fields, or prose content — these break whenever the document is edited and provide no value. Only test ADR-related *code* (e.g., `test_adr_reviewer.py` tests the reviewer logic).
- **Never include line numbers in ADR source citations.** Throughout ADR documents (Related, Context, Decision, Consequences sections), cite source files by function or class name only (e.g., `src/config.py:_resolve_base_paths`). Do NOT add `(line 42)` or similar anywhere — line numbers drift as the source file is edited and council reviews will flag them as stale.

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PCC","title":"ADR testing rules","content":"- **Never write tests for ADR markdown content.** ADRs are documentation, not code. Do not create `test_adr_NNNN_*.py` files that assert on markdown headings, status fields, or prose content — these break whenever the document is edited and provide no value. Only test ADR-related *code* (e.g., `test_adr_reviewer.py` tests the reviewer logic).\n- **Never include line numbers in ADR source citations.** Throughout ADR documents (Related, Context, Decision, Consequences sections), cite source files by function or class name only (e.g., `src/config.py:_resolve_base_paths`). Do NOT add `(line 42)` or similar anywhere — line numbers drift as the source file is edited and council reviews will flag them as stale.","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793719+00:00","updated_at":"2026-04-25T00:47:19.793720+00:00","valid_from":"2026-04-25T00:47:19.793719+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Related



- [`gotchas.md`](gotchas.md) — recurring test-side mistakes (top-level imports of optional deps, wrong-level mocks, falsy optional checks)
- [`patterns.md`](patterns.md) — the full quality sequence to run before committing
- [`docs/adr/0022-integration-test-architecture-cross-phase.md`](../adr/0022-integration-test-architecture-cross-phase.md) — integration test architecture
- [`docs/adr/0035-tests-must-match-toggle-state-they-assert.md`](../adr/0035-tests-must-match-toggle-state-they-assert.md) — toggle/test alignment

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PCD","title":"Related","content":"- [`avoided-patterns.md`](avoided-patterns.md) — recurring test-side mistakes (top-level imports of optional deps, wrong-level mocks, falsy optional checks)\n- [`quality-gates.md`](quality-gates.md) — the full quality sequence to run before committing\n- [`docs/adr/0022-integration-test-architecture-cross-phase.md`](../adr/0022-integration-test-architecture-cross-phase.md) — integration test architecture\n- [`docs/adr/0035-tests-must-match-toggle-state-they-assert.md`](../adr/0035-tests-must-match-toggle-state-they-assert.md) — toggle/test alignment","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793726+00:00","updated_at":"2026-04-25T00:47:19.793727+00:00","valid_from":"2026-04-25T00:47:19.793726+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Scenario Testing Framework



Release-gating scenario tests that prove the full pipeline and background loops work before shipping.

```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ2491","title":"Scenario Testing Framework","content":"Release-gating scenario tests that prove the full pipeline and background loops work before shipping.","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794030+00:00","updated_at":"2026-04-25T00:47:19.794031+00:00","valid_from":"2026-04-25T00:47:19.794030+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Architecture



Two layers: a **MockWorld** fixture that composes all external fakes into a controllable environment, and **scenario test files** grouped by happy/sad/edge/loop paths.

### MockWorld

A single test fixture that wires up every external service as a stateful fake, builds on top of `PipelineHarness`, and exposes a fluent API for seeding state and running the pipeline.

```
tests/scenarios/
  conftest.py              # MockWorld fixture
  fakes/
    mock_world.py          # MockWorld — composes all fakes
    fake_github.py         # Issues, PRs, labels, CI status, comments
    fake_llm.py            # Scripted triage/plan/implement/review results
    fake_hindsight.py      # Memory bank retain/recall with fail mode
    fake_workspace.py      # Worktree lifecycle tracking
    fake_sentry.py         # Breadcrumb/event capture
    fake_clock.py          # Deterministic time control
    scenario_result.py     # IssueOutcome + ScenarioResult dataclasses
  test_happy.py            # Happy path scenarios (mark: scenario)
  test_sad.py              # Failure + recovery scenarios (mark: scenario)
  test_edge.py             # Race conditions, mid-flight mutations (mark: scenario)
  test_loops.py            # Background loop scenarios (mark: scenario_loops)
```

### Stateful Fakes

Each fake is a real Python class with in-memory state (not `AsyncMock`). Assertions inspect the world's final state directly (e.g. `world.github.issue(1).labels`) rather than checking mock call counts.

| Fake | Replaces | State It Tracks |
|------|----------|----------------|
| `FakeGitHub` | `PRManager`, `IssueFetcher` | Issues, PRs, labels, CI, comments |
| `FakeLLM` | All 4 runners | Per-phase, per-issue scripted results (supports retry sequences) |
| `FakeHindsight` | `HindsightClient` | Per-bank memory entries, fail mode |
| `FakeWorkspace` | `WorkspaceManager` | Created/destroyed worktrees |
| `FakeSentry` | `sentry_sdk` | Breadcrumbs and events |
| `FakeClock` | `time.time` | Controllable time for TTL/staleness |

### MockWorld API

```python
# Seed the world (fluent, returns self)
world.add_issue(number, title, body, labels=...)
world.set_phase_result(phase, issue, result)
world.set_phase_results(phase, issue, [result1, result2])  # retry sequences
world.on_phase(phase, callback)                            # mid-flight hooks
world.fail_service(name)
world.heal_service(name)

# Run
result = await world.run_pipeline()              # pipeline phases
stats  = await world.run_with_loops(["ci_monitor"], cycles=1)  # background loops

# Inspect
world.github.issue(1).labels
world.github.pr_for_issue(1).merged
world.hindsight.bank_entries("learnings")
```

```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ2492","title":"Architecture","content":"Two layers: a **MockWorld** fixture that composes all external fakes into a controllable environment, and **scenario test files** grouped by happy/sad/edge/loop paths.\n\n### MockWorld\n\nA single test fixture that wires up every external service as a stateful fake, builds on top of `PipelineHarness`, and exposes a fluent API for seeding state and running the pipeline.\n\n```\ntests/scenarios/\n  conftest.py              # MockWorld fixture\n  fakes/\n    mock_world.py          # MockWorld — composes all fakes\n    fake_github.py         # Issues, PRs, labels, CI status, comments\n    fake_llm.py            # Scripted triage/plan/implement/review results\n    fake_hindsight.py      # Memory bank retain/recall with fail mode\n    fake_workspace.py      # Worktree lifecycle tracking\n    fake_sentry.py         # Breadcrumb/event capture\n    fake_clock.py          # Deterministic time control\n    scenario_result.py     # IssueOutcome + ScenarioResult dataclasses\n  test_happy.py            # Happy path scenarios (mark: scenario)\n  test_sad.py              # Failure + recovery scenarios (mark: scenario)\n  test_edge.py             # Race conditions, mid-flight mutations (mark: scenario)\n  test_loops.py            # Background loop scenarios (mark: scenario_loops)\n```\n\n### Stateful Fakes\n\nEach fake is a real Python class with in-memory state (not `AsyncMock`). Assertions inspect the world's final state directly (e.g. `world.github.issue(1).labels`) rather than checking mock call counts.\n\n| Fake | Replaces | State It Tracks |\n|------|----------|----------------|\n| `FakeGitHub` | `PRManager`, `IssueFetcher` | Issues, PRs, labels, CI, comments |\n| `FakeLLM` | All 4 runners | Per-phase, per-issue scripted results (supports retry sequences) |\n| `FakeHindsight` | `HindsightClient` | Per-bank memory entries, fail mode |\n| `FakeWorkspace` | `WorkspaceManager` | Created/destroyed worktrees |\n| `FakeSentry` | `sentry_sdk` | Breadcrumbs and events |\n| `FakeClock` | `time.time` | Controllable time for TTL/staleness |\n\n### MockWorld API\n\n```python\n# Seed the world (fluent, returns self)\nworld.add_issue(number, title, body, labels=...)\nworld.set_phase_result(phase, issue, result)\nworld.set_phase_results(phase, issue, [result1, result2])  # retry sequences\nworld.on_phase(phase, callback)                            # mid-flight hooks\nworld.fail_service(name)\nworld.heal_service(name)\n\n# Run\nresult = await world.run_pipeline()              # pipeline phases\nstats  = await world.run_with_loops([\"ci_monitor\"], cycles=1)  # background loops\n\n# Inspect\nworld.github.issue(1).labels\nworld.github.pr_for_issue(1).merged\nworld.hindsight.bank_entries(\"learnings\")\n```","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794036+00:00","updated_at":"2026-04-25T00:47:19.794037+00:00","valid_from":"2026-04-25T00:47:19.794036+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Running



```bash
make scenario          # pipeline scenarios (pytest -m scenario)
make scenario-loops    # background loop scenarios (pytest -m scenario_loops)
make quality           # includes both in the quality gate
```

```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ2493","title":"Running","content":"```bash\nmake scenario          # pipeline scenarios (pytest -m scenario)\nmake scenario-loops    # background loop scenarios (pytest -m scenario_loops)\nmake quality           # includes both in the quality gate\n```","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794041+00:00","updated_at":"2026-04-25T00:47:19.794042+00:00","valid_from":"2026-04-25T00:47:19.794041+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Relationship to Existing Tests



- **Unit tests (9K+):** Unchanged. Test individual functions/methods.
- **Integration tests (`PipelineHarness`):** Unchanged. Test phase wiring with mocked runners.
- **Scenario tests (this):** Test complete flows with stateful fakes. Additive, not replacing.

```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ2495","title":"Relationship to Existing Tests","content":"- **Unit tests (9K+):** Unchanged. Test individual functions/methods.\n- **Integration tests (`PipelineHarness`):** Unchanged. Test phase wiring with mocked runners.\n- **Scenario tests (this):** Test complete flows with stateful fakes. Additive, not replacing.","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794052+00:00","updated_at":"2026-04-25T00:47:19.794052+00:00","valid_from":"2026-04-25T00:47:19.794052+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Future: v2 Observability-Driven Scenarios



Auto-generation from production run traces:
1. Production run recorder captures external interactions
2. Trace-to-scenario converter builds MockWorld seed + assertions
3. Self-improvement loop adds scenarios when production diverges

Out of scope for v1. MockWorld API is designed to support it.

---

```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ2497","title":"Future: v2 Observability-Driven Scenarios","content":"Auto-generation from production run traces:\n1. Production run recorder captures external interactions\n2. Trace-to-scenario converter builds MockWorld seed + assertions\n3. Self-improvement loop adds scenarios when production diverges\n\nOut of scope for v1. MockWorld API is designed to support it.\n\n---","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794062+00:00","updated_at":"2026-04-25T00:47:19.794063+00:00","valid_from":"2026-04-25T00:47:19.794062+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Conventions (Tier 1 / 2 / 3 Helpers)



### Test Helpers

- **`init_test_worktree(path, *, branch="agent/issue-1", origin=None)`** — Helper at `tests/scenarios/helpers/git_worktree_fixture.py`. Initializes a git repo with a bare origin, main branch, and feature branch. Use for any realistic-agent scenario that runs `_count_commits`. Pass `origin=...` when multiple worktrees share a parent directory.

- **`seed_ports(world, **ports)`** — Helper at `tests/scenarios/helpers/loop_port_seeding.py`. Pre-seeds `world._loop_ports` with `AsyncMock` variants before `run_with_loops` runs the catalog builder. Use when a caretaker-loop scenario needs to observe calls on an inner delegate.

### MockWorld Constructor Flags

- **`MockWorld(use_real_agent_runner=True)`** — Opt-in flag that replaces the scripted `FakeLLM.agents` with a real production `AgentRunner` wired to `FakeDocker` via `FakeSubprocessRunner`. Default `False` preserves scripted-mode behavior.

- **`MockWorld(wiki_store=..., beads_manager=...)`** — Thread `RepoWikiStore` and `FakeBeads` into `PlanPhase`/`ImplementPhase`.

### MockWorld Methods

- **`MockWorld.fail_service("docker" | "github" | "hindsight")`** — Arms fault injection on the corresponding fake. Mirrored `heal_service(...)` clears.

### FakeDocker Scripting

- **`FakeDocker.script_run_with_commits(events, commits, cwd)`** — Script agent run events plus one commit to the worktree repo at `cwd`.

- **`FakeDocker.script_run_with_multiple_commits(events, commit_batches, cwd)`** — Script agent run events plus N separate commits, respectively. Use when the scenario must verify multi-commit push behavior.

### FakeGitHub Fault Injection

- **`FakeGitHub.add_alerts(*, branch, alerts)`** — Script code-scanning alerts for a branch. Keys by branch string to match `PRPort.fetch_code_scanning_alerts(branch)`.

### FakeWorkspace Fault Injection

- **`FakeWorkspace.fail_next_create(kind)`** — Single-shot fault: `permission | disk_full | branch_conflict`. The workspace raises on the next `create()` call then resets, so subsequent calls succeed.

---

```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ2498","title":"Conventions (Tier 1 / 2 / 3 Helpers)","content":"### Test Helpers\n\n- **`init_test_worktree(path, *, branch=\"agent/issue-1\", origin=None)`** — Helper at `tests/scenarios/helpers/git_worktree_fixture.py`. Initializes a git repo with a bare origin, main branch, and feature branch. Use for any realistic-agent scenario that runs `_count_commits`. Pass `origin=...` when multiple worktrees share a parent directory.\n\n- **`seed_ports(world, **ports)`** — Helper at `tests/scenarios/helpers/loop_port_seeding.py`. Pre-seeds `world._loop_ports` with `AsyncMock` variants before `run_with_loops` runs the catalog builder. Use when a caretaker-loop scenario needs to observe calls on an inner delegate.\n\n### MockWorld Constructor Flags\n\n- **`MockWorld(use_real_agent_runner=True)`** — Opt-in flag that replaces the scripted `FakeLLM.agents` with a real production `AgentRunner` wired to `FakeDocker` via `FakeSubprocessRunner`. Default `False` preserves scripted-mode behavior.\n\n- **`MockWorld(wiki_store=..., beads_manager=...)`** — Thread `RepoWikiStore` and `FakeBeads` into `PlanPhase`/`ImplementPhase`.\n\n### MockWorld Methods\n\n- **`MockWorld.fail_service(\"docker\" | \"github\" | \"hindsight\")`** — Arms fault injection on the corresponding fake. Mirrored `heal_service(...)` clears.\n\n### FakeDocker Scripting\n\n- **`FakeDocker.script_run_with_commits(events, commits, cwd)`** — Script agent run events plus one commit to the worktree repo at `cwd`.\n\n- **`FakeDocker.script_run_with_multiple_commits(events, commit_batches, cwd)`** — Script agent run events plus N separate commits, respectively. Use when the scenario must verify multi-commit push behavior.\n\n### FakeGitHub Fault Injection\n\n- **`FakeGitHub.add_alerts(*, branch, alerts)`** — Script code-scanning alerts for a branch. Keys by branch string to match `PRPort.fetch_code_scanning_alerts(branch)`.\n\n### FakeWorkspace Fault Injection\n\n- **`FakeWorkspace.fail_next_create(kind)`** — Single-shot fault: `permission | disk_full | branch_conflict`. The workspace raises on the next `create()` call then resets, so subsequent calls succeed.\n\n---","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794067+00:00","updated_at":"2026-04-25T00:47:19.794068+00:00","valid_from":"2026-04-25T00:47:19.794067+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Caretaker-Loop Authoring Patterns



### Pattern A — Catalog-Driven (preferred)

Use `await world.run_with_loops(["loop_name"], cycles=1)`. Works when the loop is registered in `tests/scenarios/catalog/loop_registrations.py`. Minimal boilerplate.

```python
stats = await world.run_with_loops(["ci_monitor"], cycles=1)
assert stats["ci_monitor"]["cycles_completed"] == 1
```

### Pattern B — Direct Instantiation

Use `_make_loop_deps` from `tests/helpers.py` and construct the loop class directly. Required when:
- Config flags differ from catalog defaults, or
- The loop is not yet registered in the catalog (e.g. `staging_promotion_loop` as of this writing).

```python
from tests.helpers import _make_loop_deps
from src.loops.staging_promotion import StagingPromotionLoop

deps = _make_loop_deps(world, config_overrides={"staging_branch": "staging"})
loop = StagingPromotionLoop(**deps)
await loop.run_once()
```

Pattern A is simpler; use Pattern B only when Pattern A cannot accommodate the scenario.

```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249A","title":"Caretaker-Loop Authoring Patterns","content":"### Pattern A — Catalog-Driven (preferred)\n\nUse `await world.run_with_loops([\"loop_name\"], cycles=1)`. Works when the loop is registered in `tests/scenarios/catalog/loop_registrations.py`. Minimal boilerplate.\n\n```python\nstats = await world.run_with_loops([\"ci_monitor\"], cycles=1)\nassert stats[\"ci_monitor\"][\"cycles_completed\"] == 1\n```\n\n### Pattern B — Direct Instantiation\n\nUse `_make_loop_deps` from `tests/helpers.py` and construct the loop class directly. Required when:\n- Config flags differ from catalog defaults, or\n- The loop is not yet registered in the catalog (e.g. `staging_promotion_loop` as of this writing).\n\n```python\nfrom tests.helpers import _make_loop_deps\nfrom src.loops.staging_promotion import StagingPromotionLoop\n\ndeps = _make_loop_deps(world, config_overrides={\"staging_branch\": \"staging\"})\nloop = StagingPromotionLoop(**deps)\nawait loop.run_once()\n```\n\nPattern A is simpler; use Pattern B only when Pattern A cannot accommodate the scenario.","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794077+00:00","updated_at":"2026-04-25T00:47:19.794078+00:00","valid_from":"2026-04-25T00:47:19.794077+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## `make audit` runtime benchmark



Captured: 2026-04-22
Runs: 5
Host: Darwin mac.lan 25.3.0 Darwin Kernel Version 25.3.0: Wed Jan 28 20:56:34 PST 2026; root:xnu-12377.91.3~2/RELEASE_ARM64_T8112 arm64

| Run | Wall-clock (s) |
|---|---|
| 1 | 3.66 |
| 2 | 3.52 |
| 3 | 3.52 |
| 4 | 3.80 |
| 5 | 3.68 |

**p50:** 3.66s
**p95:** 3.80s

**Budget:** 30s (spec §4.4 "Runtime budget for the CI gate").

**Decision:**
- p95 ≤ 30s → add `audit` job to `.github/workflows/ci.yml` (Task 17a).
- p95 > 30s → add `audit` job to `.github/workflows/rc-promotion-scenario.yml` instead (Task 17b).

**Selected:** ci.yml

**Rationale:** Measured p95 of 3.80s is ~8x under the 30s per-PR budget. Running `make audit` on every PR gives fastest feedback with negligible CI cost. Task 17a applies.

```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249K","title":"`make audit` runtime benchmark","content":"Captured: 2026-04-22\nRuns: 5\nHost: Darwin mac.lan 25.3.0 Darwin Kernel Version 25.3.0: Wed Jan 28 20:56:34 PST 2026; root:xnu-12377.91.3~2/RELEASE_ARM64_T8112 arm64\n\n| Run | Wall-clock (s) |\n|---|---|\n| 1 | 3.66 |\n| 2 | 3.52 |\n| 3 | 3.52 |\n| 4 | 3.80 |\n| 5 | 3.68 |\n\n**p50:** 3.66s\n**p95:** 3.80s\n\n**Budget:** 30s (spec §4.4 \"Runtime budget for the CI gate\").\n\n**Decision:**\n- p95 ≤ 30s → add `audit` job to `.github/workflows/ci.yml` (Task 17a).\n- p95 > 30s → add `audit` job to `.github/workflows/rc-promotion-scenario.yml` instead (Task 17b).\n\n**Selected:** ci.yml\n\n**Rationale:** Measured p95 of 3.80s is ~8x under the 30s per-PR budget. Running `make audit` on every PR gives fastest feedback with negligible CI cost. Task 17a applies.","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794272+00:00","updated_at":"2026-04-25T00:47:19.794273+00:00","valid_from":"2026-04-25T00:47:19.794272+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Usage



1. Use HydraFlow normally.
2. At session end, inspect latest retro:
   - `.claude/state/self-improve/session-retros/<timestamp>-<session>.md`
3. Promote durable learnings using:
   - `/hf.memory`
4. Run structured quality checks when suggested:
   - `verification-loop` skill
   - `eval-harness` skill

```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249V","title":"Usage","content":"1. Use HydraFlow normally.\n2. At session end, inspect latest retro:\n   - `.claude/state/self-improve/session-retros/<timestamp>-<session>.md`\n3. Promote durable learnings using:\n   - `/hf.memory`\n4. Run structured quality checks when suggested:\n   - `verification-loop` skill\n   - `eval-harness` skill","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794408+00:00","updated_at":"2026-04-25T00:47:19.794409+00:00","valid_from":"2026-04-25T00:47:19.794408+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
