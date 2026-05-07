# Architecture-Patterns-Practices


## Use monkeypatch.delitem(raising=False) for sys.modules cleanup

Use pytest's monkeypatch.delitem() with raising=False to handle both existing and missing keys in sys.modules manipulation. Save original state via `had = k in sys.modules; original = sys.modules.get(k)`, then restore with monkeypatch.

**Why:** monkeypatch guarantees cleanup on teardown, preventing test isolation issues from lingering module imports.


```json:entry
{"id":"01KQP0R436FFWVR0NXQKFRYR0V","title":"Use monkeypatch.delitem(raising=False) for sys.modules cleanup","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:15:06.854778+00:00","updated_at":"2026-05-03T04:15:06.855119+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Parametrized tests with dual lists for interface conformance

Use parametrized tests with dual lists (_REQUIRED_METHODS, _SIGNED_METHODS) to validate interface conformance via set subtraction across multiple implementations. Verify specific module names in assertions, not just structure.

**Why:** Interface validation at scale without repeating assertions; specific module names catch refactorings that structural checks miss.


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZP0","title":"Parametrized tests with dual lists for interface conformance","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:15:06.855175+00:00","updated_at":"2026-05-03T04:15:06.855178+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use conftest session-scope setup for deferred imports in tests

Use conftest session-scope setup to avoid redundant sys.path.insert calls across test files. Configure path manipulation once at session scope rather than per-test.

**Why:** Reduces test startup time and prevents repeated path manipulation that can hide module resolution issues.


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZP1","title":"Use conftest session-scope setup for deferred imports in tests","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:15:06.855220+00:00","updated_at":"2026-05-03T04:15:06.855222+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Call discovery functions on-demand at runtime

Call discovery functions on-demand at runtime (e.g., `discover_skills(repo_root)` per call without caching) rather than populating registries at import-time.

**Why:** Discovery must happen at runtime to stay fresh and avoid blocking startup; import-time registration risks cache staleness and startup delays.


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZP2","title":"Call discovery functions on-demand at runtime","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:15:06.855237+00:00","updated_at":"2026-05-03T04:15:06.855239+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use reversible naming conventions to eliminate registry files

Establish reversible naming conventions that map command names to modules and functions without separate registry files. Example: hf.diff-sanity command maps to diff_sanity module with `build_diff_sanity_prompt()` and `parse_diff_sanity_result()` functions.

**Why:** Self-documenting discovery patterns eliminate manual registry mapping files and reduce coupling between naming and registration logic.


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZP3","title":"Use reversible naming conventions to eliminate registry files","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:15:06.855251+00:00","updated_at":"2026-05-03T04:15:06.855253+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Catch broad exceptions during module discovery

Catch broad exceptions (not just ImportError) during module imports in discovery functions to handle syntax errors and missing dependencies. Use lightweight frontmatter parsing (split on `---` delimiters) for dynamic definitions.

**Why:** Prevents discovery from failing on transient import issues, syntax errors in modules, or missing optional dependencies; broad catching is safer than selective.


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZP4","title":"Catch broad exceptions during module discovery","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:15:06.855264+00:00","updated_at":"2026-05-03T04:15:06.855266+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Coordinator pattern with call-order sensitivity

When extracting sub-methods from a large method, the original becomes a thin orchestrator calling extracted methods in sequence. Preserve exact call order; execution order is critical—e.g., builder.record_history() must precede builder.build_stats().

**Why:** Method reordering breaks assumptions about prior state or side effects; tests should verify order is maintained after extraction.

_Source: #6330 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZP5","title":"Coordinator pattern with call-order sensitivity","topic":null,"source_type":"plan","source_issue":6330,"source_repo":null,"created_at":"2026-05-03T04:15:06.855279+00:00","updated_at":"2026-05-03T04:15:06.855281+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## NamedTuple for multi-return extracted methods

When an extracted method returns multiple related values (e.g., _build_context_sections returning multiple section strings), use a lightweight NamedTuple instead of creating a dataclass. This provides named access and self-documenting return types.

**Why:** NamedTuple avoids test infrastructure breakage while enabling named access; keeps the extracted method's interface simple and testable.

_Source: #6330 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZP6","title":"NamedTuple for multi-return extracted methods","topic":null,"source_type":"plan","source_issue":6330,"source_repo":null,"created_at":"2026-05-03T04:15:06.855312+00:00","updated_at":"2026-05-03T04:15:06.855314+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Parameter threading across extracted methods

Watch for parameters (like bead_mapping) that appear as arguments to multiple extracted methods across different extraction phases. Thread these cross-cutting parameters consistently through the coordinator to avoid silent bugs from missing arguments.

**Why:** Cross-cutting parameters indicate a concern spanning multiple methods; tracking parameter dependencies during design ensures completeness.

_Source: #6330 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZP7","title":"Parameter threading across extracted methods","topic":null,"source_type":"plan","source_issue":6330,"source_repo":null,"created_at":"2026-05-03T04:15:06.855328+00:00","updated_at":"2026-05-03T04:15:06.855330+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Structured transcript parsing: markers and lists

Parse transcripts via three markers: result key (OK/RETRY status), summary section (captured text), and item list (extracted from bullet points). Use case-insensitive matching and whitespace-tolerant list parsing to handle formatting variations.

**Why:** This approach handles variability in capitalization and indentation without requiring rigid formatting contracts from callers.

_Source: #6349 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZP8","title":"Structured transcript parsing: markers and lists","topic":null,"source_type":"plan","source_issue":6349,"source_repo":null,"created_at":"2026-05-03T04:15:06.855341+00:00","updated_at":"2026-05-03T04:15:06.855343+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Separate parsing utilities from subprocess concerns

Create parsing utility modules with clear, single responsibilities, distinct from runner_utils which handles subprocess/streaming. Transcript parsing belongs in its own module with its own test file.

**Why:** This boundary prevents utility modules from becoming dumping grounds; each concern evolves independently with focused dependencies.

_Source: #6349 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZP9","title":"Separate parsing utilities from subprocess concerns","topic":null,"source_type":"plan","source_issue":6349,"source_repo":null,"created_at":"2026-05-03T04:15:06.855356+00:00","updated_at":"2026-05-03T04:15:06.855357+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Thin public wrappers replace private method access

When internal callers (e.g., stale_issue_loop, sentry_loop) access private methods on a façaded class (_run_gh, _repo), add thin public wrapper methods on appropriate sub-clients instead. Example: add list_open_issues_raw() to IssueClient rather than exposing _run_gh.

**Why:** This maintains encapsulation boundaries while serving legitimate internal dependencies; preserves the façade contract.

_Source: #6348 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPA","title":"Thin public wrappers replace private method access","topic":null,"source_type":"plan","source_issue":6348,"source_repo":null,"created_at":"2026-05-03T04:15:06.855370+00:00","updated_at":"2026-05-03T04:15:06.855372+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Line/method budgets force better decomposition

Hard constraints (≤200 lines, ~7 public methods per class) push better architectural decisions than soft targets. During large refactors, line budgets force splits that reveal natural subdomain boundaries. Example: a bloated query client naturally splits into PRQueryClient and DashboardQueryClient.

**Why:** Budget prevents architectural shortcuts; constraints reveal natural boundaries better than iterative design decisions.

_Source: #6348 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPB","title":"Line/method budgets force better decomposition","topic":null,"source_type":"plan","source_issue":6348,"source_repo":null,"created_at":"2026-05-03T04:15:06.855382+00:00","updated_at":"2026-05-03T04:15:06.855384+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Selective EventBus threading by behavioral intent

Only thread EventBus to sub-clients with behavioral side effects (publishing events: PRLifecycle, IssueClient, CIStatusClient). Pure query clients (PRQueryClient, MetricsClient) omit EventBus. Dependency presence signals behavioral responsibilities.

**Why:** Avoids threading unnecessary dependencies through constructors; selective injection prevents silent coupling creep.

_Source: #6348 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPC","title":"Selective EventBus threading by behavioral intent","topic":null,"source_type":"plan","source_issue":6348,"source_repo":null,"created_at":"2026-05-03T04:15:06.855393+00:00","updated_at":"2026-05-03T04:15:06.855395+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Never-raise contract uses broad exception catching

Health checks and diagnostic functions should catch Exception (not specific types like httpx.HTTPError) and return False/safe default rather than propagate. Matches the *_safe pattern for functions that must not raise (e.g., retain_safe, recall_safe).

**Why:** Broad catching prevents cascading failures when diagnostics themselves encounter issues; "never raise" is stronger than handling specific exceptions.

_Source: #6362 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPD","title":"Never-raise contract uses broad exception catching","topic":null,"source_type":"plan","source_issue":6362,"source_repo":null,"created_at":"2026-05-03T04:15:06.855403+00:00","updated_at":"2026-05-03T04:15:06.855405+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use exc_info=True to preserve full exception tracebacks

Use logger.warning(..., exc_info=True) to capture full exception traceback in logs (visible in structured logs and observability tools) while downgrading severity level. Enables post-incident debugging without triggering alerting systems.

**Why:** Full traceback visibility at WARNING level helps debugging without paging oncall; useful for expected failures warranting investigation but not immediate alerting.

_Source: #6363 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPE","title":"Use exc_info=True to preserve full exception tracebacks","topic":null,"source_type":"plan","source_issue":6363,"source_repo":null,"created_at":"2026-05-03T04:15:06.855414+00:00","updated_at":"2026-05-03T04:15:06.855416+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Test class names describe scenarios, not subjects

Test class names like TestGCLoopNoCircuitBreaker describe the scenario being tested (GC loop behavior without circuit breaking) rather than the code under test. When removing a module, check whether test classes with that name actually import it or document test scenario.

**Why:** Scenario names survive refactoring better than code-reference names; intent-based naming helps other developers understand test organization.

_Source: #6365 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPF","title":"Test class names describe scenarios, not subjects","topic":null,"source_type":"plan","source_issue":6365,"source_repo":null,"created_at":"2026-05-03T04:15:06.855424+00:00","updated_at":"2026-05-03T04:15:06.855426+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Inline implementations preferred over extracted utilities

Implement simple patterns (circuit-breaking, retry logic) inline in orchestrators rather than extracting to reusable utility classes. Example: implement circuit-breaking logic inline rather than using an extracted CircuitBreaker class.

**Why:** Inline implementations reduce coupling and import complexity; reserve extraction for patterns used across multiple modules.

_Source: #6365 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPG","title":"Inline implementations preferred over extracted utilities","topic":null,"source_type":"plan","source_issue":6365,"source_repo":null,"created_at":"2026-05-03T04:15:06.855435+00:00","updated_at":"2026-05-03T04:15:06.855437+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Multi-bank memory deduplication via PromptDeduplicator

Pool items from all Hindsight banks via exact-text matching with character counts. Deduplicate using PromptDeduplicator.dedup_bank_items() to merge duplicates and track contributing banks. Rebuild per-bank strings from dedup results instead of set-rebuilding, which loses merged item metadata.

**Why:** Prevents memory injection bloat from multi-bank recall while maintaining recall quality across banks; respects display modifications like **AVOID:** prefixes.


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPH","title":"Multi-bank memory deduplication via PromptDeduplicator","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:15:06.855446+00:00","updated_at":"2026-05-03T04:15:06.855447+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Multi-tier context capping for memory injection

Cap memory injection using three tiers after deduplication: max_recall_thread_items_per_phase (5), max_inherited_memory_chars (2000), max_memory_prompt_chars (4000). Enforce each tier in sequence during context assembly for graduated cutoff.

**Why:** Prevents context explosion while preserving signal from multiple memory banks; tiered limits provide fallback cutoffs at different scales.


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPJ","title":"Multi-tier context capping for memory injection","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:15:06.855456+00:00","updated_at":"2026-05-03T04:15:06.855457+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Strategy dispatcher pattern for conditional behavior

For methods with conditional logic based on an enum (e.g., release strategy: BUNDLED vs ORDERED vs HITL), create a single dispatcher method (handle_ready(strategy)) that routes to private strategy handlers. Centralizes branching logic and makes it testable.

**Why:** Cleaner than nested if/elif chains; dispatcher pattern makes test coverage explicit for each strategy path.

_Source: #6339 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPK","title":"Strategy dispatcher pattern for conditional behavior","topic":null,"source_type":"plan","source_issue":6339,"source_repo":null,"created_at":"2026-05-03T04:15:06.855466+00:00","updated_at":"2026-05-03T04:15:06.855468+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Export widely-reused constants without underscore prefix

Time duration constants imported across multiple modules (config.py, _common.py, tests/) should use public names without underscore prefix (ONE_DAY_SECS, not _ONE_DAY_SECS). Reserve underscore prefix for file-local-only constants.

**Why:** Clear public API signals safe re-export; underscore convention makes internal-only scope explicit for future readers.

_Source: #6341 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPM","title":"Export widely-reused constants without underscore prefix","topic":null,"source_type":"plan","source_issue":6341,"source_repo":null,"created_at":"2026-05-03T04:15:06.855476+00:00","updated_at":"2026-05-03T04:15:06.855478+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Document variant patterns; defer premature parameterization

When similar patterns use different implementations (e.g., triage.py uses space separator while another uses newline for memory context), keep scope narrow and document the variant for future follow-up rather than force parameterization. Unify if a third variant appears.

**Why:** Over-parameterizing early adds complexity without immediate need; documentation lets variants coexist safely until convergence signals a real abstraction.

_Source: #6340 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPN","title":"Document variant patterns; defer premature parameterization","topic":null,"source_type":"plan","source_issue":6340,"source_repo":null,"created_at":"2026-05-03T04:15:06.855486+00:00","updated_at":"2026-05-03T04:15:06.855488+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dependency injection + re-export for backward-compatible splits

When splitting a large class into focused subclasses, inject the new dependencies into the parent constructor and re-export the new classes from the original module. Example: from epic import EpicStatusReporter works post-split. Wiring happens in ServiceRegistry.

**Why:** Maintains API compatibility while separating concerns; gradual migration of callers avoids forced refactoring downstream.

_Source: #6339 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPP","title":"Dependency injection + re-export for backward-compatible splits","topic":null,"source_type":"plan","source_issue":6339,"source_repo":null,"created_at":"2026-05-03T04:15:06.855496+00:00","updated_at":"2026-05-03T04:15:06.855501+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Sub-factory coordination via frozen dataclass

When decomposing a large factory function, bundle frequently-shared infrastructure (10+) into a frozen dataclass (e.g., _CoreDeps) and pass it to downstream sub-factories. Pattern inherited from LoopDeps in base_background_loop.py.

**Why:** Reduces parameter explosion and makes dependency ownership explicit without requiring typed classes for every service group.

_Source: #6334 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPQ","title":"Sub-factory coordination via frozen dataclass","topic":null,"source_type":"plan","source_issue":6334,"source_repo":null,"created_at":"2026-05-03T04:15:06.855512+00:00","updated_at":"2026-05-03T04:15:06.855514+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Distinguish local from cross-group wiring at architecture boundary

Post-construction mutations fall into two categories: local (both objects in same sub-factory, e.g., `shape_phase._council = ExpertCouncil(...)`) and cross-group (objects from different sub-factories, e.g., `agents._insights = review_insights`). Local wiring stays in sub-factory; cross-group moves to orchestrator.

**Why:** This boundary clarifies dependency coupling and prevents wiring logic from drifting into wrong layers. See also: Sub-factory coordination via frozen dataclass.

_Source: #6334 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPR","title":"Distinguish local from cross-group wiring at architecture boundary","topic":null,"source_type":"plan","source_issue":6334,"source_repo":null,"created_at":"2026-05-03T04:15:06.855522+00:00","updated_at":"2026-05-03T04:15:06.855524+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## AST-based regression tests are fragile to refactoring

Tests that walk the AST looking for specific function/variable names and nesting patterns break if code is renamed, wrapped, or restructured. Keep cleanup calls simple and direct—no indirection, no renaming, no extra nesting. Fragility is a tradeoff for regression coverage.

**Why:** AST patterns couple tightly to implementation; accept fragility as cost of catching accidental refactorings.

_Source: #6362 (plan)_


```json:entry
{"id":"01KQP0R43781VJFJ9HZRWQCZPS","title":"AST-based regression tests are fragile to refactoring","topic":null,"source_type":"plan","source_issue":6362,"source_repo":null,"created_at":"2026-05-03T04:15:06.855532+00:00","updated_at":"2026-05-03T04:15:06.855534+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
