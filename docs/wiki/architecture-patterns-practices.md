# Architecture-Patterns-Practices


## Testing Patterns: Mocking, Parametrized Assertions, and Test Helpers

For test isolation with sys.modules manipulation, use pytest's monkeypatch.delitem() with raising=False to handle both existing and missing keys, and monkeypatch guarantees cleanup on teardown. Save original module state via `had = k in sys.modules; original = sys.modules.get(k)`, then restore with monkeypatch. Use parametrized tests with dual lists (_REQUIRED_METHODS, _SIGNED_METHODS) to validate interface conformance via set subtraction. Tests should check presence via content assertion, not just structure (verify specific module names, not just that labels exist). Follow existing test class patterns (TestBuildStage, TestEdgeCases, TestPartialTimelines) when adding similar validators. Conftest at session scope handles sys.path setup, making explicit sys.path.insert calls in test modules redundant. For deferred imports in tests, see Deferred Imports, Type Checking, and Testing.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W0","title":"Testing Patterns: Mocking, Parametrized Assertions, and Test Helpers","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849559+00:00","updated_at":"2026-04-10T03:41:18.849561+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dynamic Discovery with Convention-Based Naming

Avoid import-time registry population; instead call discovery functions on-demand (e.g., `discover_skills(repo_root)` per call without caching). Discovery must happen at runtime not import-time to stay fresh and avoid blocking startup. Establish reversible naming conventions: hf.diff-sanity command → diff_sanity module with `build_diff_sanity_prompt()` and `parse_diff_sanity_result()` functions. This eliminates need for separate registry mapping files. Lightweight frontmatter parsing (split on `---` delimiters) avoids adding parser dependencies. Catch broad exceptions during module imports (not just ImportError) to handle syntax errors, missing dependencies, and other runtime errors. Dynamic skill definitions in JSONL use generic templated builders (functools.partial) + result markers. Multiple registration mechanisms (bg_loop_registry dict, loop_factories tuple) require unified discovery via set union. See also: Workspace Isolation for command discovery patterns, Background Loops for registration.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W1","title":"Dynamic Discovery with Convention-Based Naming","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849563+00:00","updated_at":"2026-04-10T03:41:18.849564+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Coordinator pattern with call-order sensitivity

When extracting sub-methods from a large method, the original method becomes a thin orchestrator calling extracted methods in sequence. Execution order is critical—e.g., builder.record_history() must happen before builder.build_stats(). Preserve exact call order in the coordinator; tests should verify this order is maintained after extraction.

_Source: #6330 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X9","title":"Coordinator pattern with call-order sensitivity","topic":null,"source_type":"plan","source_issue":6330,"source_repo":null,"created_at":"2026-04-10T05:17:59.124008+00:00","updated_at":"2026-04-10T05:17:59.124009+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## NamedTuple for multi-return extracted methods

When an extracted method returns multiple related values (like _build_context_sections returning multiple section strings), use a lightweight NamedTuple instead of creating a dataclass or new class. This avoids test infrastructure breakage while providing named access and self-documenting return types.

_Source: #6330 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XA","title":"NamedTuple for multi-return extracted methods","topic":null,"source_type":"plan","source_issue":6330,"source_repo":null,"created_at":"2026-04-10T05:17:59.124011+00:00","updated_at":"2026-04-10T05:17:59.124012+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Parameter threading across extracted methods

Some parameters (like bead_mapping) appear as arguments to multiple extracted methods across different extraction phases. Watch for these cross-cutting parameters during design—they indicate a concern that spans multiple extracted methods and should be threaded consistently through the coordinator to avoid silent bugs from missing arguments.

_Source: #6330 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XB","title":"Parameter threading across extracted methods","topic":null,"source_type":"plan","source_issue":6330,"source_repo":null,"created_at":"2026-04-10T05:17:59.124014+00:00","updated_at":"2026-04-10T05:17:59.124016+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Structured transcript parsing: markers, summaries, and item lists

Transcripts can be parsed via three markers: result key (OK/RETRY status), summary section (captured text), and item list (extracted from bullet points). Case-insensitive matching and whitespace-tolerant list parsing make this pattern robust across variations in formatting and capitalization.

_Source: #6349 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPH","title":"Structured transcript parsing: markers, summaries, and item lists","topic":null,"source_type":"plan","source_issue":6349,"source_repo":null,"created_at":"2026-04-10T06:47:04.972424+00:00","updated_at":"2026-04-10T06:47:04.972425+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Separate parsing utilities from subprocess and streaming concerns

Create new utility modules with clear, single responsibilities. Transcript parsing belongs in its own module, distinct from runner_utils which handles subprocess/streaming. This boundary prevents utility modules from becoming dumping grounds and keeps dependencies focused.

_Source: #6349 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPJ","title":"Separate parsing utilities from subprocess and streaming concerns","topic":null,"source_type":"plan","source_issue":6349,"source_repo":null,"created_at":"2026-04-10T06:47:04.972432+00:00","updated_at":"2026-04-10T06:47:04.972433+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Thin public wrappers replace private method access

When internal callers (e.g., `stale_issue_loop`, `sentry_loop`) access private methods on a façaded class (`_run_gh`, `_repo`), add thin public wrapper methods on the appropriate sub-client rather than exposing infrastructure. Example: add `list_open_issues_raw()` to `IssueClient` for `stale_issue_loop` to call instead of `_run_gh`. This maintains encapsulation boundaries while serving legitimate internal dependencies.

_Source: #6348 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPK","title":"Thin public wrappers replace private method access","topic":null,"source_type":"plan","source_issue":6348,"source_repo":null,"created_at":"2026-04-10T06:49:24.638890+00:00","updated_at":"2026-04-10T06:49:24.638891+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Line/method budgets force better decomposition

Hard constraints (≤200 lines, ~7 public methods per class) push better architectural decisions than soft targets. During this refactor, the large query methods didn't fit in a single 200-line `PRQueryClient`, forcing a split into `PRQueryClient` and `DashboardQueryClient`. The constraint prevented a bloated compromise class and revealed natural subdomain boundaries.

_Source: #6348 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPM","title":"Line/method budgets force better decomposition","topic":null,"source_type":"plan","source_issue":6348,"source_repo":null,"created_at":"2026-04-10T06:49:24.638893+00:00","updated_at":"2026-04-10T06:49:24.638894+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Selective EventBus threading by behavioral side effects

Not all sub-clients need the same dependencies. Only sub-clients with behavioral side effects (publishing events: `PRLifecycle`, `IssueClient`, `CIStatusClient`) receive `EventBus` in `__init__`. Pure query clients (`PRQueryClient`, `MetricsClient`) don't. This selective dependency injection pattern avoids threading unnecessary dependencies through constructors and signals intent about what each component does.

_Source: #6348 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPN","title":"Selective EventBus threading by behavioral side effects","topic":null,"source_type":"plan","source_issue":6348,"source_repo":null,"created_at":"2026-04-10T06:49:24.638897+00:00","updated_at":"2026-04-10T06:49:24.638897+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Never-raise contract uses broad exception catching

Health checks and diagnostic functions should catch `Exception` (not specific types like `httpx.HTTPError`) and return False/safe default rather than propagate. Matches the `*_safe` pattern used for functions that must not raise (e.g., `retain_safe`, `recall_safe`).

_Source: #6362 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ6","title":"Never-raise contract uses broad exception catching","topic":null,"source_type":"plan","source_issue":6362,"source_repo":null,"created_at":"2026-04-10T07:44:23.400476+00:00","updated_at":"2026-04-10T07:44:23.400479+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## exc_info=True parameter preserves full tracebacks at lower levels

logger.warning(..., exc_info=True) captures the full exception traceback in logs (visible in structured logs and observability tools) while downgrading the severity level. This enables post-incident debugging without triggering alerting systems designed for ERROR-level events.

_Source: #6363 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ8","title":"exc_info=True parameter preserves full tracebacks at lower levels","topic":null,"source_type":"plan","source_issue":6363,"source_repo":null,"created_at":"2026-04-10T07:48:21.129667+00:00","updated_at":"2026-04-10T07:48:21.129669+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Test class names describe scenarios, not test subjects

Test class names like `TestGCLoopNoCircuitBreaker` describe the scenario being tested (GC loop behavior without circuit breaking) rather than the code under test. When removing a module, check whether test classes with that name actually import or test it, or are simply documenting a test scenario.

_Source: #6365 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQA","title":"Test class names describe scenarios, not test subjects","topic":null,"source_type":"plan","source_issue":6365,"source_repo":null,"created_at":"2026-04-10T07:59:04.461043+00:00","updated_at":"2026-04-10T07:59:04.461045+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Inline implementations preferred over extracted utility classes

The orchestrator implements its own circuit-breaking logic (consecutive-failure counter at :926-1026) rather than using the extracted `CircuitBreaker` class. This suggests the project favors inline implementations for simple patterns over shared utility classes, reducing coupling and import complexity.

_Source: #6365 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQB","title":"Inline implementations preferred over extracted utility classes","topic":null,"source_type":"plan","source_issue":6365,"source_repo":null,"created_at":"2026-04-10T07:59:04.461047+00:00","updated_at":"2026-04-10T07:59:04.461048+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Prompt Deduplication and Memory Context Capping

Multi-bank Hindsight recall causes duplicate or overlapping memories in prompts. Deduplication strategy: (1) Pool items from all banks, track via exact-text matching with character counts; (2) Deduplicate via PromptDeduplicator.dedup_bank_items() which merges duplicate text and tracks which banks contributed; (3) Rebuild per-bank strings avoiding exact-string set-rebuilding (which fails for merged items)—instead return per-bank surviving items directly from dedup; (4) Cap memory injection with multi-tier limits: max_recall_thread_items_per_phase (5), max_inherited_memory_chars (2000), max_memory_prompt_chars (4000). Semantic vs exact matching: dedup removes exact duplicates while preserving content overlap between banks (acceptable). Text-based dedup respects display modifications (e.g., prefixes like **AVOID:**). Antipatterns use 1.15x boost multiplier for recall priority, but must be tuned if antipatterns dominate results. See also: Optional Dependencies for Hindsight service handling, Side Effect Consumption for context threading.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WC","title":"Prompt Deduplication and Memory Context Capping","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.852310+00:00","updated_at":"2026-04-10T03:41:18.852312+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Strategy dispatcher pattern for conditional behavior branches

For methods with conditional logic based on an enum (e.g., release strategy: BUNDLED vs ORDERED vs HITL), create a single dispatcher method (`handle_ready(strategy)`) that routes to private strategy handlers. This centralizes the branching logic and makes it testable without exposing individual handlers.

_Source: #6339 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP6","title":"Strategy dispatcher pattern for conditional behavior branches","topic":null,"source_type":"plan","source_issue":6339,"source_repo":null,"created_at":"2026-04-10T06:19:03.788199+00:00","updated_at":"2026-04-10T06:19:03.788202+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Export widely-reused constants without underscore prefix

Time duration constants imported across multiple modules (config.py, _common.py, tests/) should use public names without underscore prefix (ONE_DAY_SECS, not _ONE_DAY_SECS). Reserve underscore prefix for file-local-only constants to signal scope.

_Source: #6341 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP8","title":"Export widely-reused constants without underscore prefix","topic":null,"source_type":"plan","source_issue":6341,"source_repo":null,"created_at":"2026-04-10T06:22:03.281145+00:00","updated_at":"2026-04-10T06:22:03.281148+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Document variant patterns; resist premature parameterization

The plan notes that `triage.py` uses a similar memory context pattern but with space separator instead of newline. Rather than force parameterization to handle both, the plan keeps scope narrow and documents the variant for future follow-up. Over-parameterizing early adds complexity without immediate need.

_Source: #6340 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP4","title":"Document variant patterns; resist premature parameterization","topic":null,"source_type":"plan","source_issue":6340,"source_repo":null,"created_at":"2026-04-10T06:11:06.699170+00:00","updated_at":"2026-04-10T06:11:06.699173+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dependency injection + re-export for backward-compatible class splits

When splitting a large class into focused subclasses, inject the new dependencies into the parent constructor and re-export the new classes from the original module. This maintains API compatibility (`from epic import EpicStatusReporter` works) while separating concerns. Wiring happens in `ServiceRegistry`, not in the class constructors.

_Source: #6339 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP5","title":"Dependency injection + re-export for backward-compatible class splits","topic":null,"source_type":"plan","source_issue":6339,"source_repo":null,"created_at":"2026-04-10T06:19:03.788137+00:00","updated_at":"2026-04-10T06:19:03.788154+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Sub-factory coordination via intermediate frozen dataclass

When decomposing a large factory function, bundle frequently-shared infrastructure (10+) into a frozen dataclass (e.g., `_CoreDeps`) and pass it to downstream sub-factories. This pattern, inherited from `LoopDeps` in `base_background_loop.py`, reduces parameter explosion and makes dependency ownership explicit without requiring typed classes for every service group.

_Source: #6334 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XN","title":"Sub-factory coordination via intermediate frozen dataclass","topic":null,"source_type":"plan","source_issue":6334,"source_repo":null,"created_at":"2026-04-10T05:40:10.652297+00:00","updated_at":"2026-04-10T05:40:10.652309+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Distinguish local wiring from cross-group wiring at architecture boundary

Post-construction mutations fall into two categories: local (both objects created in same sub-factory, e.g., `shape_phase._council = ExpertCouncil(...)`) and cross-group (objects from different sub-factories, e.g., `agents._insights = review_insights`). Local wiring stays in the sub-factory; cross-group wiring moves to the thin orchestrator. This boundary clarifies dependency coupling.

_Source: #6334 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XP","title":"Distinguish local wiring from cross-group wiring at architecture boundary","topic":null,"source_type":"plan","source_issue":6334,"source_repo":null,"created_at":"2026-04-10T05:40:10.652318+00:00","updated_at":"2026-04-10T05:40:10.652320+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## AST-based regression tests are fragile to refactoring

Tests that walk the AST looking for specific function/variable names and nesting patterns break if code is renamed, wrapped, or restructured. Keep cleanup calls simple and direct—no indirection, no renaming, no extra nesting. Fragility is the cost of catching accidental refactorings.

_Source: #6362 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ5","title":"AST-based regression tests are fragile to refactoring","topic":null,"source_type":"plan","source_issue":6362,"source_repo":null,"created_at":"2026-04-10T07:44:23.400467+00:00","updated_at":"2026-04-10T07:44:23.400470+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
