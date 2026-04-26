# Architecture


## Deferred Imports, Type Checking, and Testing

Import optional or circular-dependent modules inside function bodies rather than at module level to break circular import chains. Use `from __future__ import annotations` globally to enable TYPE_CHECKING guards for import-time-only types without runtime overhead. Use Protocol types in TYPE_CHECKING blocks while concrete implementations are imported normally. Keep deferred imports inside the specific method that uses them—do not hoist to module level, even if multiple methods use the same import (annotate with `# noqa: PLC0415` to suppress linting). Exception classification functions import specific exception types in the function body to prevent circular imports while keeping type-checking available. In tests, patch at the source module level where the deferred import happens. Use pytest monkeypatch.delitem() with raising=False for sys.modules manipulation to handle both existing and missing keys safely. Never import optional dependencies at test module level; use deferred imports inside test methods. Critical for optional services (hindsight, docker, file_util) and cross-module utilities, avoiding import-time side effects and enabling graceful degradation. See also: Layer Architecture for module organization, Optional Dependencies for service handling.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VP","title":"Deferred Imports, Type Checking, and Testing","content":"Import optional or circular-dependent modules inside function bodies rather than at module level to break circular import chains. Use `from __future__ import annotations` globally to enable TYPE_CHECKING guards for import-time-only types without runtime overhead. Use Protocol types in TYPE_CHECKING blocks while concrete implementations are imported normally. Keep deferred imports inside the specific method that uses them—do not hoist to module level, even if multiple methods use the same import (annotate with `# noqa: PLC0415` to suppress linting). Exception classification functions import specific exception types in the function body to prevent circular imports while keeping type-checking available. In tests, patch at the source module level where the deferred import happens. Use pytest monkeypatch.delitem() with raising=False for sys.modules manipulation to handle both existing and missing keys safely. Never import optional dependencies at test module level; use deferred imports inside test methods. Critical for optional services (hindsight, docker, file_util) and cross-module utilities, avoiding import-time side effects and enabling graceful degradation. See also: Layer Architecture for module organization, Optional Dependencies for service handling.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849500+00:00","updated_at":"2026-04-10T03:41:18.849508+00:00","valid_from":"2026-04-10T03:41:18.849500+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Optional Dependencies: Graceful Degradation and Safe Handling

Services like Hindsight, Docker, and others may be unavailable or disabled. Design via: (1) **Never-raise pattern**: wrap all calls to optional features in try/except blocks that return safe defaults rather than raising. Catch broad exception types (Exception, OSError, ConnectionError) instead of importing optional module exception types. (2) **Graceful degradation**: when unavailable, fall back to JSONL file storage or no-op behavior; use dual-write pattern during migration. (3) **Explicit None checks**: guard with `if hindsight is not None:` (never falsy checks, as MagicMock can be falsy-but-not-None). (4) **Fire-and-forget async variants**: wrap blocking I/O without blocking callers. (5) **Property-based access**: expose optional services via properties rather than constructor parameters. Core principle: failures in non-critical or optional features must never crash the pipeline. See also: Feature Gates for feature flags that gate incomplete features, Deferred Imports for import-time handling.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VQ","title":"Optional Dependencies: Graceful Degradation and Safe Handling","content":"Services like Hindsight, Docker, and others may be unavailable or disabled. Design via: (1) **Never-raise pattern**: wrap all calls to optional features in try/except blocks that return safe defaults rather than raising. Catch broad exception types (Exception, OSError, ConnectionError) instead of importing optional module exception types. (2) **Graceful degradation**: when unavailable, fall back to JSONL file storage or no-op behavior; use dual-write pattern during migration. (3) **Explicit None checks**: guard with `if hindsight is not None:` (never falsy checks, as MagicMock can be falsy-but-not-None). (4) **Fire-and-forget async variants**: wrap blocking I/O without blocking callers. (5) **Property-based access**: expose optional services via properties rather than constructor parameters. Core principle: failures in non-critical or optional features must never crash the pipeline. See also: Feature Gates for feature flags that gate incomplete features, Deferred Imports for import-time handling.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849518+00:00","updated_at":"2026-04-10T03:41:18.849521+00:00","valid_from":"2026-04-10T03:41:18.849518+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Layer Architecture: Four-Layer Model with Structural Typing

HydraFlow uses a 4-layer architecture with strict downward-only import direction: L1 (Utilities: subprocess_util, file_util, state) → L2 (Application: phases, runners, background loops) → L3 (Agents: specialized LLM runners) → L4 (Infrastructure: HTTP routes, FastAPI, CLI). TYPE_CHECKING imports and protocol abstractions enable type safety without runtime layer violations. Use @runtime_checkable Protocol abstractions (AgentPort, PRPort, IssueStorePort, OrchestratorPort) to decouple layers via structural typing—concrete implementations automatically satisfy protocols via duck typing. Service registry (service_registry.py) is the single architecturally-exempt composition root: instantiate dependencies in correct order, annotate fields with port types for abstraction but instantiate with concrete classes, thread shared dependencies through all consumers. Background loops require 5-point wiring synchronization: config fields, service_registry imports, instantiation, orchestrator bg_loop_registry dict, and dashboard constants. Layer assignments tracked in arch_compliance.py MODULE_LAYERS and validated via static checkers (check_layer_imports.py) and LLM-based compliance skills. Pattern-based inference: *_loop.py→L2, *_runner.py→L3, *_scaffold.py→L4. Bidirectional cross-cutting modules (state, events, ports) can be imported by any layer but must only import from L1. See also: Architecture Compliance for validation, Orchestrator/Sequencer Design for L2 patterns.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VR","title":"Layer Architecture: Four-Layer Model with Structural Typing","content":"HydraFlow uses a 4-layer architecture with strict downward-only import direction: L1 (Utilities: subprocess_util, file_util, state) → L2 (Application: phases, runners, background loops) → L3 (Agents: specialized LLM runners) → L4 (Infrastructure: HTTP routes, FastAPI, CLI). TYPE_CHECKING imports and protocol abstractions enable type safety without runtime layer violations. Use @runtime_checkable Protocol abstractions (AgentPort, PRPort, IssueStorePort, OrchestratorPort) to decouple layers via structural typing—concrete implementations automatically satisfy protocols via duck typing. Service registry (service_registry.py) is the single architecturally-exempt composition root: instantiate dependencies in correct order, annotate fields with port types for abstraction but instantiate with concrete classes, thread shared dependencies through all consumers. Background loops require 5-point wiring synchronization: config fields, service_registry imports, instantiation, orchestrator bg_loop_registry dict, and dashboard constants. Layer assignments tracked in arch_compliance.py MODULE_LAYERS and validated via static checkers (check_layer_imports.py) and LLM-based compliance skills. Pattern-based inference: *_loop.py→L2, *_runner.py→L3, *_scaffold.py→L4. Bidirectional cross-cutting modules (state, events, ports) can be imported by any layer but must only import from L1. See also: Architecture Compliance for validation, Orchestrator/Sequencer Design for L2 patterns.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849524+00:00","updated_at":"2026-04-10T03:41:18.849525+00:00","valid_from":"2026-04-10T03:41:18.849524+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## State Persistence: Atomic Writes and Backup Recovery

All critical file operations use atomic write patterns to prevent partial corruption on crash: write to temp file, fsync for durability, then os.replace() for atomic swap. Use centralized utilities: `file_util.atomic_write()` for entire file rewrites (e.g., JSONL rotations) and `file_util.append_jsonl()` for crash-safe appends with automatic mkdir, flush, and fsync. For JSONL rotation/trimming: read, filter, write atomically; acquire exclusive file lock (.{filename}.lock) for the entire read-filter-write cycle to prevent TOCTOU bugs. Cache JSONL parsing results with TTL patterns for HTTP handlers. StateTracker uses backup pattern: save .bak backup before overwriting; restore from backup if main file corrupts. Single-writer assumption (async orchestrator) eliminates need for write-ahead logging. Applies to WAL files, state snapshots, JSONL stores, and configuration.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VS","title":"State Persistence: Atomic Writes and Backup Recovery","content":"All critical file operations use atomic write patterns to prevent partial corruption on crash: write to temp file, fsync for durability, then os.replace() for atomic swap. Use centralized utilities: `file_util.atomic_write()` for entire file rewrites (e.g., JSONL rotations) and `file_util.append_jsonl()` for crash-safe appends with automatic mkdir, flush, and fsync. For JSONL rotation/trimming: read, filter, write atomically; acquire exclusive file lock (.{filename}.lock) for the entire read-filter-write cycle to prevent TOCTOU bugs. Cache JSONL parsing results with TTL patterns for HTTP handlers. StateTracker uses backup pattern: save .bak backup before overwriting; restore from backup if main file corrupts. Single-writer assumption (async orchestrator) eliminates need for write-ahead logging. Applies to WAL files, state snapshots, JSONL stores, and configuration.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849528+00:00","updated_at":"2026-04-10T03:41:18.849529+00:00","valid_from":"2026-04-10T03:41:18.849528+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Backward Compatibility and Refactoring via Facades and Re-Exports

When splitting large classes or moving code, preserve backward compatibility using three strategies: (1) **Re-exports**: move implementation to canonical location, re-export from original module, ensuring `isinstance()` checks and existing imports work unchanged. Test re-exports with identity checks (`assert Class1 is Class2`). (2) **Optional parameters with None defaults**: add new functionality as optional kwargs, allowing callers to omit them with fallback behavior matching the old implementation. (3) **Facade + composition for large classes**: when splitting classes with 20+ importing modules and 50+ test mock targets, keep delegation stubs on original class so all existing import paths, isinstance checks, and mock targets continue working. Extract to sub-clients inheriting a shared base class. Fix encapsulation violations by defining proper public API methods on the base class. These patterns enable incremental migration and prevent breaking 40+ existing import sites across the codebase. See also: Consolidation Patterns for handling multiple refactoring scenarios.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VT","title":"Backward Compatibility and Refactoring via Facades and Re-Exports","content":"When splitting large classes or moving code, preserve backward compatibility using three strategies: (1) **Re-exports**: move implementation to canonical location, re-export from original module, ensuring `isinstance()` checks and existing imports work unchanged. Test re-exports with identity checks (`assert Class1 is Class2`). (2) **Optional parameters with None defaults**: add new functionality as optional kwargs, allowing callers to omit them with fallback behavior matching the old implementation. (3) **Facade + composition for large classes**: when splitting classes with 20+ importing modules and 50+ test mock targets, keep delegation stubs on original class so all existing import paths, isinstance checks, and mock targets continue working. Extract to sub-clients inheriting a shared base class. Fix encapsulation violations by defining proper public API methods on the base class. These patterns enable incremental migration and prevent breaking 40+ existing import sites across the codebase. See also: Consolidation Patterns for handling multiple refactoring scenarios.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849534+00:00","updated_at":"2026-04-10T03:41:18.849536+00:00","valid_from":"2026-04-10T03:41:18.849534+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Functional Design: Pure Functions and Module-Level Utilities

Extract pure functions (taking primitives, returning primitives or tuples) for reusable business logic that should be independently testable. Pattern: classify_merge_outcome(verdict_score, comment_count, ...) → (outcome, confidence). Pure functions isolate rules from service coupling, enable unit testing without mocks, and clarify logic intent. Pass config objects as parameters to access configuration-dependent values. When scoring classification logic is split across modules, consolidate by creating a pure function in the domain module with named threshold constants. Simple tuple returns (3 elements) are preferable to new dataclasses. Prefer module-level utility functions (e.g., retain_safe(client, bank, content, metadata=...)) over instance methods. This pattern is more testable, avoids tight coupling, and provides cleaner APIs. Module-level functions accept the object as first argument. When converting a closure to a standalone function, convert each `nonlocal` variable to either a function parameter (input) or a field in a returned NamedTuple (output). This eliminates implicit state sharing and makes the function's dependencies explicit—critical for testing and reasoning about behavior.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VV","title":"Functional Design: Pure Functions and Module-Level Utilities","content":"Extract pure functions (taking primitives, returning primitives or tuples) for reusable business logic that should be independently testable. Pattern: classify_merge_outcome(verdict_score, comment_count, ...) → (outcome, confidence). Pure functions isolate rules from service coupling, enable unit testing without mocks, and clarify logic intent. Pass config objects as parameters to access configuration-dependent values. When scoring classification logic is split across modules, consolidate by creating a pure function in the domain module with named threshold constants. Simple tuple returns (3 elements) are preferable to new dataclasses. Prefer module-level utility functions (e.g., retain_safe(client, bank, content, metadata=...)) over instance methods. This pattern is more testable, avoids tight coupling, and provides cleaner APIs. Module-level functions accept the object as first argument. When converting a closure to a standalone function, convert each `nonlocal` variable to either a function parameter (input) or a field in a returned NamedTuple (output). This eliminates implicit state sharing and makes the function's dependencies explicit—critical for testing and reasoning about behavior.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849538+00:00","updated_at":"2026-04-10T03:41:18.849540+00:00","valid_from":"2026-04-10T03:41:18.849538+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Background Loops and Skill Infrastructure: Audit Patterns and Wiring

Background loops (BaseBackgroundLoop subclasses) follow a standard pattern established by CodeGroomingLoop: (1) _run_audit() invokes a slash command; (2) parse severity-headed output into findings; (3) deduplicate via DedupStore per loop type (e.g., architecture_audit_dedup.json, test_audit_dedup.json); (4) file GitHub issues for Critical/High findings. Discovery via class definition pattern (BaseBackgroundLoop subclass with worker_name kwarg). Wiring requires 5 synchronized locations: config (interval + env override), service_registry (instantiation), orchestrator (bg_loop_registry dict), dashboard UI (_INTERVAL_BOUNDS and BACKGROUND_WORKERS), and constants.js. Omitting any location causes incomplete registration. Test discovery via test_loop_wiring_completeness.py. Skip sets track intentional deviations. Distinguish from per-PR skills: per-PR skills (architecture_compliance.py, test_quality.py) are lightweight single-prompt diff reviews focused on clear violations. Background loops invoke full multi-agent slash commands. Phase-filtered skill injection separates via registry (TOOL_PHASE_MAP data), injection (base runner coordination), execution unchanged. Tool presentation to LLM is filtered by phase but execution remains unchanged. Skills in multiple backends handled via marker-based checks (substring matching for '## Output') rather than exact structure enforcement. Two-file consolidation: Pydantic model definition for structure validation and dynamic JSONL writing for persistence must stay synchronized. Operator review gates dynamic skills due to prompt injection risk. See also: Layer Architecture for placement, Dynamic Discovery for command discovery.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VW","title":"Background Loops and Skill Infrastructure: Audit Patterns and Wiring","content":"Background loops (BaseBackgroundLoop subclasses) follow a standard pattern established by CodeGroomingLoop: (1) _run_audit() invokes a slash command; (2) parse severity-headed output into findings; (3) deduplicate via DedupStore per loop type (e.g., architecture_audit_dedup.json, test_audit_dedup.json); (4) file GitHub issues for Critical/High findings. Discovery via class definition pattern (BaseBackgroundLoop subclass with worker_name kwarg). Wiring requires 5 synchronized locations: config (interval + env override), service_registry (instantiation), orchestrator (bg_loop_registry dict), dashboard UI (_INTERVAL_BOUNDS and BACKGROUND_WORKERS), and constants.js. Omitting any location causes incomplete registration. Test discovery via test_loop_wiring_completeness.py. Skip sets track intentional deviations. Distinguish from per-PR skills: per-PR skills (architecture_compliance.py, test_quality.py) are lightweight single-prompt diff reviews focused on clear violations. Background loops invoke full multi-agent slash commands. Phase-filtered skill injection separates via registry (TOOL_PHASE_MAP data), injection (base runner coordination), execution unchanged. Tool presentation to LLM is filtered by phase but execution remains unchanged. Skills in multiple backends handled via marker-based checks (substring matching for '## Output') rather than exact structure enforcement. Two-file consolidation: Pydantic model definition for structure validation and dynamic JSONL writing for persistence must stay synchronized. Operator review gates dynamic skills due to prompt injection risk. See also: Layer Architecture for placement, Dynamic Discovery for command discovery.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849543+00:00","updated_at":"2026-04-10T03:41:18.849544+00:00","valid_from":"2026-04-10T03:41:18.849543+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Label-Based Async Loop Routing via GitHub Labels

The system routes work through distinct concurrent async polling loops via GitHub issue labels (hydraflow-plan, hydraflow-discover, hydraflow-shape, etc.). Each loop: fetches issues with its label, processes them, swaps the label to route to the next phase. This pattern avoids persistent state management by leveraging GitHub as the queue and label transitions as the state machine. Event types (triage_routed, discover_complete, etc.) publish to EventLog and trigger state transitions. Source fields in events (discover, shape, plan) establish cross-references for worker creation and transcript routing. New event types require multi-layer synchronization: reducer event handlers (worker creation), EVENT_TO_STAGE mapping, SOURCE_TO_STAGE routing, and transcript routing logic. See also: Orchestrator/Sequencer Design for coordination patterns, Layer Architecture for event handling placement.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VX","title":"Label-Based Async Loop Routing via GitHub Labels","content":"The system routes work through distinct concurrent async polling loops via GitHub issue labels (hydraflow-plan, hydraflow-discover, hydraflow-shape, etc.). Each loop: fetches issues with its label, processes them, swaps the label to route to the next phase. This pattern avoids persistent state management by leveraging GitHub as the queue and label transitions as the state machine. Event types (triage_routed, discover_complete, etc.) publish to EventLog and trigger state transitions. Source fields in events (discover, shape, plan) establish cross-references for worker creation and transcript routing. New event types require multi-layer synchronization: reducer event handlers (worker creation), EVENT_TO_STAGE mapping, SOURCE_TO_STAGE routing, and transcript routing logic. See also: Orchestrator/Sequencer Design for coordination patterns, Layer Architecture for event handling placement.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849547+00:00","updated_at":"2026-04-10T03:41:18.849548+00:00","valid_from":"2026-04-10T03:41:18.849547+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Idempotency Guards Prevent Redundant Side Effects

Add idempotency guards by checking outcome state at handler entry: `if state.get_outcome(issue_number) == MERGED: return`. This prevents redundant side effects (label swaps, counter increments, hook re-execution) from race conditions or retries. Log at info level when guard triggers for observability. Test three cases: (1) outcome already exists—side effects don't execute, (2) no prior outcome—normal flow, (3) non-MERGED outcome—normal flow. Use test helper pattern: `_setup_*()` method returning setup object with `.call()` method for test invocation. This pattern ensures idempotent handlers don't over-suppress valid operations. See also: Pre-Flight Validation for related validation patterns, State Persistence for outcome storage.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VY","title":"Idempotency Guards Prevent Redundant Side Effects","content":"Add idempotency guards by checking outcome state at handler entry: `if state.get_outcome(issue_number) == MERGED: return`. This prevents redundant side effects (label swaps, counter increments, hook re-execution) from race conditions or retries. Log at info level when guard triggers for observability. Test three cases: (1) outcome already exists—side effects don't execute, (2) no prior outcome—normal flow, (3) non-MERGED outcome—normal flow. Use test helper pattern: `_setup_*()` method returning setup object with `.call()` method for test invocation. This pattern ensures idempotent handlers don't over-suppress valid operations. See also: Pre-Flight Validation for related validation patterns, State Persistence for outcome storage.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849551+00:00","updated_at":"2026-04-10T03:41:18.849552+00:00","valid_from":"2026-04-10T03:41:18.849551+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Clarity Score Routing: Fast Path vs Multi-Stage Maturation

The discovery phase routes issues in two tracks based on clarity_score: (1) clarity_score >= 7: skip Discover and Shape, go directly from Triage to Plan (fast path); (2) clarity_score < 7: route through Discover → Shape pipeline for multi-turn maturation (slow path). Three-stage pipeline design: Discover gathers product research context, Shape runs multi-turn design conversation and presents options for human selection, Plan begins after direction is chosen. This staged approach separates research, synthesis, and planning concerns with human decision points between stages.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VZ","title":"Clarity Score Routing: Fast Path vs Multi-Stage Maturation","content":"The discovery phase routes issues in two tracks based on clarity_score: (1) clarity_score >= 7: skip Discover and Shape, go directly from Triage to Plan (fast path); (2) clarity_score < 7: route through Discover → Shape pipeline for multi-turn maturation (slow path). Three-stage pipeline design: Discover gathers product research context, Shape runs multi-turn design conversation and presents options for human selection, Plan begins after direction is chosen. This staged approach separates research, synthesis, and planning concerns with human decision points between stages.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849555+00:00","updated_at":"2026-04-10T03:41:18.849557+00:00","valid_from":"2026-04-10T03:41:18.849555+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Testing Patterns: Mocking, Parametrized Assertions, and Test Helpers

For test isolation with sys.modules manipulation, use pytest's monkeypatch.delitem() with raising=False to handle both existing and missing keys, and monkeypatch guarantees cleanup on teardown. Save original module state via `had = k in sys.modules; original = sys.modules.get(k)`, then restore with monkeypatch. Use parametrized tests with dual lists (_REQUIRED_METHODS, _SIGNED_METHODS) to validate interface conformance via set subtraction. Tests should check presence via content assertion, not just structure (verify specific module names, not just that labels exist). Follow existing test class patterns (TestBuildStage, TestEdgeCases, TestPartialTimelines) when adding similar validators. Conftest at session scope handles sys.path setup, making explicit sys.path.insert calls in test modules redundant. For deferred imports in tests, see Deferred Imports, Type Checking, and Testing.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W0","title":"Testing Patterns: Mocking, Parametrized Assertions, and Test Helpers","content":"For test isolation with sys.modules manipulation, use pytest's monkeypatch.delitem() with raising=False to handle both existing and missing keys, and monkeypatch guarantees cleanup on teardown. Save original module state via `had = k in sys.modules; original = sys.modules.get(k)`, then restore with monkeypatch. Use parametrized tests with dual lists (_REQUIRED_METHODS, _SIGNED_METHODS) to validate interface conformance via set subtraction. Tests should check presence via content assertion, not just structure (verify specific module names, not just that labels exist). Follow existing test class patterns (TestBuildStage, TestEdgeCases, TestPartialTimelines) when adding similar validators. Conftest at session scope handles sys.path setup, making explicit sys.path.insert calls in test modules redundant. For deferred imports in tests, see Deferred Imports, Type Checking, and Testing.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849559+00:00","updated_at":"2026-04-10T03:41:18.849561+00:00","valid_from":"2026-04-10T03:41:18.849559+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dynamic Discovery with Convention-Based Naming

Avoid import-time registry population; instead call discovery functions on-demand (e.g., `discover_skills(repo_root)` per call without caching). Discovery must happen at runtime not import-time to stay fresh and avoid blocking startup. Establish reversible naming conventions: hf.diff-sanity command → diff_sanity module with `build_diff_sanity_prompt()` and `parse_diff_sanity_result()` functions. This eliminates need for separate registry mapping files. Lightweight frontmatter parsing (split on `---` delimiters) avoids adding parser dependencies. Catch broad exceptions during module imports (not just ImportError) to handle syntax errors, missing dependencies, and other runtime errors. Dynamic skill definitions in JSONL use generic templated builders (functools.partial) + result markers. Multiple registration mechanisms (bg_loop_registry dict, loop_factories tuple) require unified discovery via set union. See also: Workspace Isolation for command discovery patterns, Background Loops for registration.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W1","title":"Dynamic Discovery with Convention-Based Naming","content":"Avoid import-time registry population; instead call discovery functions on-demand (e.g., `discover_skills(repo_root)` per call without caching). Discovery must happen at runtime not import-time to stay fresh and avoid blocking startup. Establish reversible naming conventions: hf.diff-sanity command → diff_sanity module with `build_diff_sanity_prompt()` and `parse_diff_sanity_result()` functions. This eliminates need for separate registry mapping files. Lightweight frontmatter parsing (split on `---` delimiters) avoids adding parser dependencies. Catch broad exceptions during module imports (not just ImportError) to handle syntax errors, missing dependencies, and other runtime errors. Dynamic skill definitions in JSONL use generic templated builders (functools.partial) + result markers. Multiple registration mechanisms (bg_loop_registry dict, loop_factories tuple) require unified discovery via set union. See also: Workspace Isolation for command discovery patterns, Background Loops for registration.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849563+00:00","updated_at":"2026-04-10T03:41:18.849564+00:00","valid_from":"2026-04-10T03:41:18.849563+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Feature Gates and Configuration-Driven Behavior

When a feature depends on unimplemented prerequisites, gate the entire feature behind a config flag (default False) rather than attempting runtime degradation. This isolates incomplete work, prevents confusing partial-state behavior, and makes the feature truly opt-in until dependencies land. Example: `post_acceptance_tracking_enabled` in config. Test both enabled and disabled paths separately. For optional allocations, add feature functionality via `get_allocation(label, fallback_cap)` method that returns config-defined caps when feature enabled, falling back to fallback_cap when no budget set. This ensures zero behavioral change when feature disabled and allows safe feature rollout without regressions. Individual section caps serve as `max_chars` overrides, preserving existing guardrails. Backward compatibility is preserved: old code paths continue unchanged when feature is disabled. See also: Optional Dependencies for runtime service handling.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W2","title":"Feature Gates and Configuration-Driven Behavior","content":"When a feature depends on unimplemented prerequisites, gate the entire feature behind a config flag (default False) rather than attempting runtime degradation. This isolates incomplete work, prevents confusing partial-state behavior, and makes the feature truly opt-in until dependencies land. Example: `post_acceptance_tracking_enabled` in config. Test both enabled and disabled paths separately. For optional allocations, add feature functionality via `get_allocation(label, fallback_cap)` method that returns config-defined caps when feature enabled, falling back to fallback_cap when no budget set. This ensures zero behavioral change when feature disabled and allows safe feature rollout without regressions. Individual section caps serve as `max_chars` overrides, preserving existing guardrails. Backward compatibility is preserved: old code paths continue unchanged when feature is disabled. See also: Optional Dependencies for runtime service handling.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849567+00:00","updated_at":"2026-04-10T03:41:18.849568+00:00","valid_from":"2026-04-10T03:41:18.849567+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dataclass Design for Schema Evolution and Backward Compatibility

Use TypedDict with total=False or Pydantic dataclasses with optional fields for backward-compatible schema evolution. Missing fields handled gracefully with .get(key, default). Use frozen dataclasses (`@dataclass(frozen=True, slots=True)`) to bundle context parameters that won't change at runtime. Include optional fields with empty string defaults for fields not yet populated, preventing accidental mutation and making contracts explicit. Placeholder fields anticipate feature extension points: add fields for planned features even if data sources don't exist yet, defaulting to empty strings with docstring notes. Model fields should include optional metadata that can be populated opportunistically, avoiding breaking changes later. Ensure all fields have non-empty defaults if parametrized tests override individual fields. String annotations and `from __future__ import annotations` enable Literal and forward references without runtime overhead. For JSONL records, add new fields as optional with sensible defaults; existing consumers tolerate extra keys automatically. Legacy records without new fields remain valid via fallback logic.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W3","title":"Dataclass Design for Schema Evolution and Backward Compatibility","content":"Use TypedDict with total=False or Pydantic dataclasses with optional fields for backward-compatible schema evolution. Missing fields handled gracefully with .get(key, default). Use frozen dataclasses (`@dataclass(frozen=True, slots=True)`) to bundle context parameters that won't change at runtime. Include optional fields with empty string defaults for fields not yet populated, preventing accidental mutation and making contracts explicit. Placeholder fields anticipate feature extension points: add fields for planned features even if data sources don't exist yet, defaulting to empty strings with docstring notes. Model fields should include optional metadata that can be populated opportunistically, avoiding breaking changes later. Ensure all fields have non-empty defaults if parametrized tests override individual fields. String annotations and `from __future__ import annotations` enable Literal and forward references without runtime overhead. For JSONL records, add new fields as optional with sensible defaults; existing consumers tolerate extra keys automatically. Legacy records without new fields remain valid via fallback logic.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849570+00:00","updated_at":"2026-04-10T03:41:18.849572+00:00","valid_from":"2026-04-10T03:41:18.849570+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Consolidation Patterns for Duplicate Code

Three similar items (e.g., Handlers, Runners, Loops) warrant consolidation if the same pattern exists elsewhere (e.g., 8 runners total vs 3 currently refactored). Partial migrations create maintenance burden. Extract duplicated path patterns into module-level constants and shared helper functions. Consolidate label field lists via module-level constants (ALL_LIFECYCLE_LABEL_FIELDS) to allow cross-module imports without circular dependencies. When extracting methods from large classes, preserve original public API via thin delegation methods to avoid cascading changes across callers. Backward-compatible JSONL schema evolution: add optional fields with sensible defaults that existing consumers handle automatically. Example: fixing one missing label field requires fixing all missing label fields at once, not just the mentioned ones, to prevent latent bugs. See also: Backward Compatibility for preservation strategies, Dead Code Removal for cleanup verification.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W4","title":"Consolidation Patterns for Duplicate Code","content":"Three similar items (e.g., Handlers, Runners, Loops) warrant consolidation if the same pattern exists elsewhere (e.g., 8 runners total vs 3 currently refactored). Partial migrations create maintenance burden. Extract duplicated path patterns into module-level constants and shared helper functions. Consolidate label field lists via module-level constants (ALL_LIFECYCLE_LABEL_FIELDS) to allow cross-module imports without circular dependencies. When extracting methods from large classes, preserve original public API via thin delegation methods to avoid cascading changes across callers. Backward-compatible JSONL schema evolution: add optional fields with sensible defaults that existing consumers handle automatically. Example: fixing one missing label field requires fixing all missing label fields at once, not just the mentioned ones, to prevent latent bugs. See also: Backward Compatibility for preservation strategies, Dead Code Removal for cleanup verification.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849574+00:00","updated_at":"2026-04-10T03:41:18.849575+00:00","valid_from":"2026-04-10T03:41:18.849574+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dead Code Removal Verification and Code Cleanup

Verify dead code removal via: (1) `make test` confirms no hidden dependencies, (2) `make quality-lite` for lint/type/security, (3) `make layer-check` validates layer boundaries, (4) comprehensive grep -r across src/ and tests/ for remaining references. When removing modules: update scripts/check_layer_imports.py MODULE_LAYERS dict, verify all imports are removed, delete entire files not stubs. Empty files create ambiguity—delete them entirely. Layer checker warns about nonexistent modules if entries aren't removed from MODULE_LAYERS. When deleting code from a subsection, preserve section heading comments (e.g., '# --- Structured Return Types ---') if other items in that section remain. The comment applies to all remaining members and improves navigation for future readers. ADR Superseding Pattern: when a planned feature documented in an ADR is removed as dead code (never implemented), update the ADR status to 'Superseded by removal' and cross-reference the removal issue. This preserves architectural decision history and clarifies for future reimplementation attempts.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W5","title":"Dead Code Removal Verification and Code Cleanup","content":"Verify dead code removal via: (1) `make test` confirms no hidden dependencies, (2) `make quality-lite` for lint/type/security, (3) `make layer-check` validates layer boundaries, (4) comprehensive grep -r across src/ and tests/ for remaining references. When removing modules: update scripts/check_layer_imports.py MODULE_LAYERS dict, verify all imports are removed, delete entire files not stubs. Empty files create ambiguity—delete them entirely. Layer checker warns about nonexistent modules if entries aren't removed from MODULE_LAYERS. When deleting code from a subsection, preserve section heading comments (e.g., '# --- Structured Return Types ---') if other items in that section remain. The comment applies to all remaining members and improves navigation for future readers. ADR Superseding Pattern: when a planned feature documented in an ADR is removed as dead code (never implemented), update the ADR status to 'Superseded by removal' and cross-reference the removal issue. This preserves architectural decision history and clarifies for future reimplementation attempts.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849578+00:00","updated_at":"2026-04-10T03:41:18.849579+00:00","valid_from":"2026-04-10T03:41:18.849578+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## ADR Documentation: Format, Citations, Validation, and Superseding

ADRs use markdown with structured sections: Date, Status, Title, Context, Decision, Rationale, Consequences. Validation checklist: structural checks first (missing sections, status format), then semantic checks (scope significance, contradiction audit). Source citations use module:function format without line numbers per CLAUDE.md. Set status to Accepted for documenting existing implicit patterns, not just new proposals. Reference authoritative runtime sources (e.g., src/config.py:all_pipeline_labels) instead of copying definitions to avoid drift. Skip TYPE_CHECKING imports in citations since they're compile-time-only. Ghost entries (README listing files that don't exist) indicate stale migrations—validate documentation against filesystem reality. ADR Superseding Pattern: when a planned feature documented in an ADR is removed as dead code (never implemented), update the ADR status to 'Superseded by removal' and cross-reference the removal issue. This preserves architectural decision history and clarifies for future reimplementation attempts without duplicating work.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W6","title":"ADR Documentation: Format, Citations, Validation, and Superseding","content":"ADRs use markdown with structured sections: Date, Status, Title, Context, Decision, Rationale, Consequences. Validation checklist: structural checks first (missing sections, status format), then semantic checks (scope significance, contradiction audit). Source citations use module:function format without line numbers per CLAUDE.md. Set status to Accepted for documenting existing implicit patterns, not just new proposals. Reference authoritative runtime sources (e.g., src/config.py:all_pipeline_labels) instead of copying definitions to avoid drift. Skip TYPE_CHECKING imports in citations since they're compile-time-only. Ghost entries (README listing files that don't exist) indicate stale migrations—validate documentation against filesystem reality. ADR Superseding Pattern: when a planned feature documented in an ADR is removed as dead code (never implemented), update the ADR status to 'Superseded by removal' and cross-reference the removal issue. This preserves architectural decision history and clarifies for future reimplementation attempts without duplicating work.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849581+00:00","updated_at":"2026-04-10T03:41:18.849582+00:00","valid_from":"2026-04-10T03:41:18.849581+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Architecture Compliance and Quality Enforcement

LLM-based architecture checks (arch_compliance.py, hf.audit-architecture skill) risk blocking every PR if prompts are too aggressive. Mitigations: (1) use conservative language ('only flag clear violations'); (2) default disable-friendly config (max_attempts=1); (3) exempt composition root (service_registry.py) explicitly; (4) focus on judgment-based checks that static tools cannot detect. Deferred imports are intentional per CLAUDE.md and should never be flagged. Async read-then-write patterns (fetch state, modify, write back) are a pre-existing limitation from original _run_gh calls and acceptable as known-constraint. Tests checking presence must assert content, not just structure (e.g., verify module names in layer assignments, not just that layer labels exist). Complement with defense-in-depth enforcement via three layers: linter rules (ruff T20/T10 for debug code), AST-based validation scripts (per-function test coverage), git hooks (commit message format). Pre-commit hook runs only make lint-check (intentional gap—agent pipeline and pre-push hook cover push path). This progressive hardening pattern prevents enforcement from blocking developers while maintaining quality standards. See also: Layer Architecture for compliance targets.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W7","title":"Architecture Compliance and Quality Enforcement","content":"LLM-based architecture checks (arch_compliance.py, hf.audit-architecture skill) risk blocking every PR if prompts are too aggressive. Mitigations: (1) use conservative language ('only flag clear violations'); (2) default disable-friendly config (max_attempts=1); (3) exempt composition root (service_registry.py) explicitly; (4) focus on judgment-based checks that static tools cannot detect. Deferred imports are intentional per CLAUDE.md and should never be flagged. Async read-then-write patterns (fetch state, modify, write back) are a pre-existing limitation from original _run_gh calls and acceptable as known-constraint. Tests checking presence must assert content, not just structure (e.g., verify module names in layer assignments, not just that layer labels exist). Complement with defense-in-depth enforcement via three layers: linter rules (ruff T20/T10 for debug code), AST-based validation scripts (per-function test coverage), git hooks (commit message format). Pre-commit hook runs only make lint-check (intentional gap—agent pipeline and pre-push hook cover push path). This progressive hardening pattern prevents enforcement from blocking developers while maintaining quality standards. See also: Layer Architecture for compliance targets.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849585+00:00","updated_at":"2026-04-10T03:41:18.849586+00:00","valid_from":"2026-04-10T03:41:18.849585+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Workspace Isolation and Command Discovery via CWD

Claude Code discovers commands from subprocess cwd's .claude/commands/, not from invoking process. Commands must be installed into every workspace, not just source repo. Pre-flight validation (before subprocess launch) catches stale commands due to external state changes. Defense-in-depth prevents agent commits to target repos: combine .gitignore hf.*.md entries + hf.* prefix namespace isolation. Built-in hf.* patterns always take priority over extra patterns in deduplication. Multiple registration mechanisms (bg_loop_registry dict, loop_factories tuple) require unified discovery via set union. Path traversal guard required for extra_tool_dirs to verify they don't escape repo boundary. See also: Dynamic Discovery for convention patterns.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W8","title":"Workspace Isolation and Command Discovery via CWD","content":"Claude Code discovers commands from subprocess cwd's .claude/commands/, not from invoking process. Commands must be installed into every workspace, not just source repo. Pre-flight validation (before subprocess launch) catches stale commands due to external state changes. Defense-in-depth prevents agent commits to target repos: combine .gitignore hf.*.md entries + hf.* prefix namespace isolation. Built-in hf.* patterns always take priority over extra patterns in deduplication. Multiple registration mechanisms (bg_loop_registry dict, loop_factories tuple) require unified discovery via set union. Path traversal guard required for extra_tool_dirs to verify they don't escape repo boundary. See also: Dynamic Discovery for convention patterns.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849589+00:00","updated_at":"2026-04-10T03:41:18.849590+00:00","valid_from":"2026-04-10T03:41:18.849589+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Pre-Flight Validation and Escalation Pattern

Insert validation checks after environment setup but before main work. Return early with WorkerResult(success=False) on failure and escalate to HITL via escalator. This pattern cleanly separates precondition checking from implementation logic without entangling them. See also: Idempotency Guards for post-execution validation, Prevent Scope Creep for validation as design constraint.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W9","title":"Pre-Flight Validation and Escalation Pattern","content":"Insert validation checks after environment setup but before main work. Return early with WorkerResult(success=False) on failure and escalate to HITL via escalator. This pattern cleanly separates precondition checking from implementation logic without entangling them. See also: Idempotency Guards for post-execution validation, Prevent Scope Creep for validation as design constraint.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849593+00:00","updated_at":"2026-04-10T03:41:18.849594+00:00","valid_from":"2026-04-10T03:41:18.849593+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Prevent Scope Creep While Maintaining Correctness

Implementation plans are guidelines, not barriers. If necessary correctness fixes fall outside plan scope, document the deviation and rationale. Scope deferral with tracking issues prevents scope creep: defer separate problems to future issues rather than expanding current scope. However, never defer fixes when partial/incomplete fixes leave latent bugs. Example: fixing one missing label field requires fixing all missing label fields at once, not just the mentioned ones. Pre-mortem identification of failure modes helps design mitigations upfront and prevents rework.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WA","title":"Prevent Scope Creep While Maintaining Correctness","content":"Implementation plans are guidelines, not barriers. If necessary correctness fixes fall outside plan scope, document the deviation and rationale. Scope deferral with tracking issues prevents scope creep: defer separate problems to future issues rather than expanding current scope. However, never defer fixes when partial/incomplete fixes leave latent bugs. Example: fixing one missing label field requires fixing all missing label fields at once, not just the mentioned ones. Pre-mortem identification of failure modes helps design mitigations upfront and prevents rework.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849596+00:00","updated_at":"2026-04-10T03:41:18.849597+00:00","valid_from":"2026-04-10T03:41:18.849596+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Async Patterns: Wrappers, Context Managers, Callbacks, and Resource Lifecycle

When adding async support to sync I/O code, keep all sync methods unchanged and add a-prefixed async wrappers that delegate to sync methods via asyncio.to_thread(). This pattern (established in events.py) centralizes blocking-operation wrapping and preserves backward compatibility—existing sync callers continue unchanged while new async callers gradually migrate. Implement async context managers by adding `__aenter__` (return self), `__aexit__` (call close()), and `_closed: bool` flag in `__init__`. This pattern (established in DockerRunner) ensures clean resource shutdown semantics when wrapping clients that need guaranteed cleanup. When extracting async helpers, shared resources (like background tasks) may be awaited on the happy path but must be cancelled in the coordinator's error handler. Design the helper to handle its portion cleanly; keep lifecycle cleanup in the coordinator's `finally` block to ensure it runs regardless of how the helper exits. For done callbacks, follow the events.py pattern of defining module-level callback functions (e.g., _log_task_failure) rather than methods. This keeps callback logic portable, testable in isolation, and consistent across the codebase. Document expected signature and side effects clearly. See also: Orchestrator/Sequencer Design for coordinating async stages.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WB","title":"Async Patterns: Wrappers, Context Managers, Callbacks, and Resource Lifecycle","content":"When adding async support to sync I/O code, keep all sync methods unchanged and add a-prefixed async wrappers that delegate to sync methods via asyncio.to_thread(). This pattern (established in events.py) centralizes blocking-operation wrapping and preserves backward compatibility—existing sync callers continue unchanged while new async callers gradually migrate. Implement async context managers by adding `__aenter__` (return self), `__aexit__` (call close()), and `_closed: bool` flag in `__init__`. This pattern (established in DockerRunner) ensures clean resource shutdown semantics when wrapping clients that need guaranteed cleanup. When extracting async helpers, shared resources (like background tasks) may be awaited on the happy path but must be cancelled in the coordinator's error handler. Design the helper to handle its portion cleanly; keep lifecycle cleanup in the coordinator's `finally` block to ensure it runs regardless of how the helper exits. For done callbacks, follow the events.py pattern of defining module-level callback functions (e.g., _log_task_failure) rather than methods. This keeps callback logic portable, testable in isolation, and consistent across the codebase. Document expected signature and side effects clearly. See also: Orchestrator/Sequencer Design for coordinating async stages.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.852290+00:00","updated_at":"2026-04-10T03:41:18.852298+00:00","valid_from":"2026-04-10T03:41:18.852290+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Prompt Deduplication and Memory Context Capping

Multi-bank Hindsight recall causes duplicate or overlapping memories in prompts. Deduplication strategy: (1) Pool items from all banks, track via exact-text matching with character counts; (2) Deduplicate via PromptDeduplicator.dedup_bank_items() which merges duplicate text and tracks which banks contributed; (3) Rebuild per-bank strings avoiding exact-string set-rebuilding (which fails for merged items)—instead return per-bank surviving items directly from dedup; (4) Cap memory injection with multi-tier limits: max_recall_thread_items_per_phase (5), max_inherited_memory_chars (2000), max_memory_prompt_chars (4000). Semantic vs exact matching: dedup removes exact duplicates while preserving content overlap between banks (acceptable). Text-based dedup respects display modifications (e.g., prefixes like **AVOID:**). Antipatterns use 1.15x boost multiplier for recall priority, but must be tuned if antipatterns dominate results. See also: Optional Dependencies for Hindsight service handling, Side Effect Consumption for context threading.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WC","title":"Prompt Deduplication and Memory Context Capping","content":"Multi-bank Hindsight recall causes duplicate or overlapping memories in prompts. Deduplication strategy: (1) Pool items from all banks, track via exact-text matching with character counts; (2) Deduplicate via PromptDeduplicator.dedup_bank_items() which merges duplicate text and tracks which banks contributed; (3) Rebuild per-bank strings avoiding exact-string set-rebuilding (which fails for merged items)—instead return per-bank surviving items directly from dedup; (4) Cap memory injection with multi-tier limits: max_recall_thread_items_per_phase (5), max_inherited_memory_chars (2000), max_memory_prompt_chars (4000). Semantic vs exact matching: dedup removes exact duplicates while preserving content overlap between banks (acceptable). Text-based dedup respects display modifications (e.g., prefixes like **AVOID:**). Antipatterns use 1.15x boost multiplier for recall priority, but must be tuned if antipatterns dominate results. See also: Optional Dependencies for Hindsight service handling, Side Effect Consumption for context threading.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.852310+00:00","updated_at":"2026-04-10T03:41:18.852312+00:00","valid_from":"2026-04-10T03:41:18.852310+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Side Effect Consumption Pattern for Context Threading

Runners capture mutable side effects (e.g., `_last_recalled_items`, `_last_context_stats`) that must be explicitly consumed via getter methods after execution and cleared at method entry. This pattern prevents item leakage when runner instances are reused concurrently across issues. Pattern: (1) initialize side-effect variable in __init__ or at method entry; (2) populate during execution; (3) expose via `_consume_*()` method returning the value; (4) clear state after consumption in caller. Phases consume runner outputs, convert to domain models, and persist. This separates data production (runners) from I/O (phases) while threading context between stages via explicit consumption. See also: Functional Design for pure data threading, State Persistence for persistence patterns.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WD","title":"Side Effect Consumption Pattern for Context Threading","content":"Runners capture mutable side effects (e.g., `_last_recalled_items`, `_last_context_stats`) that must be explicitly consumed via getter methods after execution and cleared at method entry. This pattern prevents item leakage when runner instances are reused concurrently across issues. Pattern: (1) initialize side-effect variable in __init__ or at method entry; (2) populate during execution; (3) expose via `_consume_*()` method returning the value; (4) clear state after consumption in caller. Phases consume runner outputs, convert to domain models, and persist. This separates data production (runners) from I/O (phases) while threading context between stages via explicit consumption. See also: Functional Design for pure data threading, State Persistence for persistence patterns.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.852318+00:00","updated_at":"2026-04-10T03:41:18.852320+00:00","valid_from":"2026-04-10T03:41:18.852318+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Environment Override Validation via get_args() for Literal Types

The `_ENV_LITERAL_OVERRIDES` table and its validation handler use `get_args()` to extract allowed values from Literal types and validate environment variable inputs at startup. This pattern decouples override validation from field defaults, enabling a cleaner separation between string overrides (with defaults) and literal overrides (options only). Enables dynamic validation of environment overrides without hardcoding literal values in validation code.

_Source: #6310 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WE","title":"Environment Override Validation via get_args() for Literal Types","content":"The `_ENV_LITERAL_OVERRIDES` table and its validation handler use `get_args()` to extract allowed values from Literal types and validate environment variable inputs at startup. This pattern decouples override validation from field defaults, enabling a cleaner separation between string overrides (with defaults) and literal overrides (options only). Enables dynamic validation of environment overrides without hardcoding literal values in validation code.","topic":null,"source_type":"plan","source_issue":6310,"source_repo":null,"created_at":"2026-04-10T03:41:18.852325+00:00","updated_at":"2026-04-10T03:41:18.852328+00:00","valid_from":"2026-04-10T03:41:18.852325+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Model Duplication Across Codebase Suggests Ownership Clarity Issue

Duplicate Pydantic/dataclass versions exist in separate files (adr_pre_validator.py, precheck.py) with canonical dataclasses in models.py. This pattern suggests either missing consolidation or unclear model ownership. Technical debt observation: future work should establish which file owns each model and whether duplicates indicate technical debt or deliberate isolation boundaries. Consider this during next refactoring pass or architectural review.

_Source: #6312 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WF","title":"Model Duplication Across Codebase Suggests Ownership Clarity Issue","content":"Duplicate Pydantic/dataclass versions exist in separate files (adr_pre_validator.py, precheck.py) with canonical dataclasses in models.py. This pattern suggests either missing consolidation or unclear model ownership. Technical debt observation: future work should establish which file owns each model and whether duplicates indicate technical debt or deliberate isolation boundaries. Consider this during next refactoring pass or architectural review.","topic":null,"source_type":"plan","source_issue":6312,"source_repo":null,"created_at":"2026-04-10T03:41:18.852333+00:00","updated_at":"2026-04-10T03:41:18.852336+00:00","valid_from":"2026-04-10T03:41:18.852333+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dead-code removal: three-phase decomposition pattern

Systematic approach: P1 removes core methods and constructor plumbing; P2 removes dependent tests and updates helpers; P3 verifies via grep and type checking. This phased structure prevents partial removals and ensures all callers are updated before verification.

_Source: #6315 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WG","title":"Dead-code removal: three-phase decomposition pattern","content":"Systematic approach: P1 removes core methods and constructor plumbing; P2 removes dependent tests and updates helpers; P3 verifies via grep and type checking. This phased structure prevents partial removals and ensures all callers are updated before verification.","topic":null,"source_type":"plan","source_issue":6315,"source_repo":null,"created_at":"2026-04-10T03:43:46.872729+00:00","updated_at":"2026-04-10T03:43:46.872755+00:00","valid_from":"2026-04-10T03:43:46.872729+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Wire unconnected config parameters to existing consumers

When a consumer (e.g., StateTracker) already accepts constructor parameters matching config fields, but the wiring is missing from the service builder, this is a low-risk one-line fix. Check StateTracker's signature before assuming the parameter doesn't exist; it often does with sensible defaults.

_Source: #6314 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WH","title":"Wire unconnected config parameters to existing consumers","content":"When a consumer (e.g., StateTracker) already accepts constructor parameters matching config fields, but the wiring is missing from the service builder, this is a low-risk one-line fix. Check StateTracker's signature before assuming the parameter doesn't exist; it often does with sensible defaults.","topic":null,"source_type":"plan","source_issue":6314,"source_repo":null,"created_at":"2026-04-10T03:45:26.654545+00:00","updated_at":"2026-04-10T03:45:26.654546+00:00","valid_from":"2026-04-10T03:45:26.654545+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Layer 1 assignment for pure data constants

Pure string/data constants with no imports can safely be assigned to Layer 1 (runner_constants module). This avoids circular dependencies while keeping data-only definitions accessible. Layer assignment is architecturally sound when the module has no external dependencies.

_Source: #6295 (review)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WJ","title":"Layer 1 assignment for pure data constants","content":"Pure string/data constants with no imports can safely be assigned to Layer 1 (runner_constants module). This avoids circular dependencies while keeping data-only definitions accessible. Layer assignment is architecturally sound when the module has no external dependencies.","topic":null,"source_type":"review","source_issue":6295,"source_repo":null,"created_at":"2026-04-10T03:47:50.097407+00:00","updated_at":"2026-04-10T03:47:50.097411+00:00","valid_from":"2026-04-10T03:47:50.097407+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Visual consistency outweighs functional correctness

Code dict entries should visually align with their layer assignment comment blocks, not with the layer they logically belong to. Even when functionally harmless, misalignment is visually misleading and reduces code clarity for future maintainers.

_Source: #6295 (review)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WK","title":"Visual consistency outweighs functional correctness","content":"Code dict entries should visually align with their layer assignment comment blocks, not with the layer they logically belong to. Even when functionally harmless, misalignment is visually misleading and reduces code clarity for future maintainers.","topic":null,"source_type":"review","source_issue":6295,"source_repo":null,"created_at":"2026-04-10T03:47:50.097416+00:00","updated_at":"2026-04-10T03:47:50.097419+00:00","valid_from":"2026-04-10T03:47:50.097416+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Define explicit scope for extraction refactors

Extraction issues should explicitly name the target files/functions in scope. This prevents scope creep and clarifies what duplicates are intentionally excluded (e.g., similar patterns in other modules). Scope clarity prevents false-positive review flags.

_Source: #6295 (review)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WM","title":"Define explicit scope for extraction refactors","content":"Extraction issues should explicitly name the target files/functions in scope. This prevents scope creep and clarifies what duplicates are intentionally excluded (e.g., similar patterns in other modules). Scope clarity prevents false-positive review flags.","topic":null,"source_type":"review","source_issue":6295,"source_repo":null,"created_at":"2026-04-10T03:47:50.097424+00:00","updated_at":"2026-04-10T03:47:50.097427+00:00","valid_from":"2026-04-10T03:47:50.097424+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Layer checker must track newly added data modules

When creating new constant/data modules at a given layer, update the layer import checker to recognize them. This prevents false positives and ensures the layer checker stays current as the codebase grows.

_Source: #6295 (review)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WN","title":"Layer checker must track newly added data modules","content":"When creating new constant/data modules at a given layer, update the layer import checker to recognize them. This prevents false positives and ensures the layer checker stays current as the codebase grows.","topic":null,"source_type":"review","source_issue":6295,"source_repo":null,"created_at":"2026-04-10T03:47:50.097432+00:00","updated_at":"2026-04-10T03:47:50.097438+00:00","valid_from":"2026-04-10T03:47:50.097432+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Plan line numbers become stale; search by pattern instead

When implementing a plan generated in a prior session, files may have been modified since the plan was written. Prefer searching for method signature patterns rather than relying on exact line numbers provided in the plan.

_Source: #6317 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WP","title":"Plan line numbers become stale; search by pattern instead","content":"When implementing a plan generated in a prior session, files may have been modified since the plan was written. Prefer searching for method signature patterns rather than relying on exact line numbers provided in the plan.","topic":null,"source_type":"plan","source_issue":6317,"source_repo":null,"created_at":"2026-04-10T03:55:35.397280+00:00","updated_at":"2026-04-10T03:55:35.397281+00:00","valid_from":"2026-04-10T03:55:35.397280+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Annotated[str, Validator] pattern for backward-compatible type narrowing

Use `Annotated[str, AfterValidator(...)]` to add runtime validation to string fields while maintaining serialization compatibility. This pattern serializes identically to bare `str` in JSON output, enabling strict validation at construction time without breaking existing JSON schema or client contracts. Useful for retrofitting validation onto existing fields across Pydantic models.

_Source: #6318 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WQ","title":"Annotated[str, Validator] pattern for backward-compatible type narrowing","content":"Use `Annotated[str, AfterValidator(...)]` to add runtime validation to string fields while maintaining serialization compatibility. This pattern serializes identically to bare `str` in JSON output, enabling strict validation at construction time without breaking existing JSON schema or client contracts. Useful for retrofitting validation onto existing fields across Pydantic models.","topic":null,"source_type":"plan","source_issue":6318,"source_repo":null,"created_at":"2026-04-10T04:05:05.202950+00:00","updated_at":"2026-04-10T04:05:05.202964+00:00","valid_from":"2026-04-10T04:05:05.202950+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Parametrized validation rejection tests follow annotated-type pattern

Test annotated types by extending existing validation test classes with parametrized tests covering malformed inputs (rejection) and valid inputs (acceptance). This pattern isolates validation logic testing and reuses test infrastructure for new validators across multiple models.

_Source: #6318 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WR","title":"Parametrized validation rejection tests follow annotated-type pattern","content":"Test annotated types by extending existing validation test classes with parametrized tests covering malformed inputs (rejection) and valid inputs (acceptance). This pattern isolates validation logic testing and reuses test infrastructure for new validators across multiple models.","topic":null,"source_type":"plan","source_issue":6318,"source_repo":null,"created_at":"2026-04-10T04:05:05.202985+00:00","updated_at":"2026-04-10T04:05:05.202986+00:00","valid_from":"2026-04-10T04:05:05.202985+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use Literal types for bounded enum-like fields

Model fields with known bounded values should use Literal types rather than bare str. The codebase establishes this pattern (VisualEvidenceItem.status, Release.status). This provides compile-time validation and IDE autocomplete, catching invalid values at construction rather than runtime.

_Source: #6320 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WS","title":"Use Literal types for bounded enum-like fields","content":"Model fields with known bounded values should use Literal types rather than bare str. The codebase establishes this pattern (VisualEvidenceItem.status, Release.status). This provides compile-time validation and IDE autocomplete, catching invalid values at construction rather than runtime.","topic":null,"source_type":"plan","source_issue":6320,"source_repo":null,"created_at":"2026-04-10T04:14:20.752849+00:00","updated_at":"2026-04-10T04:14:20.752855+00:00","valid_from":"2026-04-10T04:14:20.752849+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Cross-cutting methods as callbacks, not new classes

Methods called by 4+ concerns (like `_escalate_to_hitl` and `_publish_review_status`) should stay on the origin class and be passed as bound-method callbacks to extracted coordinators. This avoids creating yet another coordinator just for common operations and matches the established PostMergeHandler/MergeApprovalContext callback pattern.

_Source: #6321 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WT","title":"Cross-cutting methods as callbacks, not new classes","content":"Methods called by 4+ concerns (like `_escalate_to_hitl` and `_publish_review_status`) should stay on the origin class and be passed as bound-method callbacks to extracted coordinators. This avoids creating yet another coordinator just for common operations and matches the established PostMergeHandler/MergeApprovalContext callback pattern.","topic":null,"source_type":"plan","source_issue":6321,"source_repo":null,"created_at":"2026-04-10T04:19:28.375208+00:00","updated_at":"2026-04-10T04:19:28.375220+00:00","valid_from":"2026-04-10T04:19:28.375208+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Import-site patch targets must migrate with extracted functions

When tests patch functions at import sites (e.g., `patch('review_phase.analyze_patterns')`), extracting those functions to new modules breaks the patch. Update test patches to target the new module where the function is now imported: `patch('review_insight_recorder.analyze_patterns')`. Attribute mocking via instance assignment (e.g., `phase.attr = Mock()`) continues to work unchanged.

_Source: #6321 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WV","title":"Import-site patch targets must migrate with extracted functions","content":"When tests patch functions at import sites (e.g., `patch('review_phase.analyze_patterns')`), extracting those functions to new modules breaks the patch. Update test patches to target the new module where the function is now imported: `patch('review_insight_recorder.analyze_patterns')`. Attribute mocking via instance assignment (e.g., `phase.attr = Mock()`) continues to work unchanged.","topic":null,"source_type":"plan","source_issue":6321,"source_repo":null,"created_at":"2026-04-10T04:19:28.375232+00:00","updated_at":"2026-04-10T04:19:28.375235+00:00","valid_from":"2026-04-10T04:19:28.375232+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Strict no-circular-import rule for extracted coordinators

Extracted coordinator classes must never import the original ReviewPhase class. Coordinators should only import domain modules, models, config, and phase_utils. Back-references to ReviewPhase methods must flow through callback parameters passed at construction time. Violating this creates circular imports that break the extraction.

_Source: #6321 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WW","title":"Strict no-circular-import rule for extracted coordinators","content":"Extracted coordinator classes must never import the original ReviewPhase class. Coordinators should only import domain modules, models, config, and phase_utils. Back-references to ReviewPhase methods must flow through callback parameters passed at construction time. Violating this creates circular imports that break the extraction.","topic":null,"source_type":"plan","source_issue":6321,"source_repo":null,"created_at":"2026-04-10T04:19:28.375241+00:00","updated_at":"2026-04-10T04:19:28.375243+00:00","valid_from":"2026-04-10T04:19:28.375241+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dict-to-Model Conversion Pattern for Type Safety

When callers use `.get()` on return values, convert the return type from `list[dict[str, Any]]` to a typed Pydantic model like `list[GitHubIssue]`. This eliminates fragile dict access and enables type checking. Update all callers together—avoid partial migrations where some code uses attributes and some uses `.get()`.

_Source: #6322 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WX","title":"Dict-to-Model Conversion Pattern for Type Safety","content":"When callers use `.get()` on return values, convert the return type from `list[dict[str, Any]]` to a typed Pydantic model like `list[GitHubIssue]`. This eliminates fragile dict access and enables type checking. Update all callers together—avoid partial migrations where some code uses attributes and some uses `.get()`.","topic":null,"source_type":"plan","source_issue":6322,"source_repo":null,"created_at":"2026-04-10T04:31:05.960687+00:00","updated_at":"2026-04-10T04:31:05.960695+00:00","valid_from":"2026-04-10T04:31:05.960687+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Move generic utilities to module-level functions to keep classes small

Rather than making `polling_loop` an instance method of LoopSupervisor, extract it as a module-level async function (~80 lines). This keeps the supervisor class under 200 lines while keeping polling logic independently testable. Orchestrator retains `_polling_loop()` as a thin wrapper for backward compatibility with existing mocks. This pattern aligns with codebase wiki guidance: 'Prefer module-level utility functions over instance methods.'

_Source: #6323 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WY","title":"Move generic utilities to module-level functions to keep classes small","content":"Rather than making `polling_loop` an instance method of LoopSupervisor, extract it as a module-level async function (~80 lines). This keeps the supervisor class under 200 lines while keeping polling logic independently testable. Orchestrator retains `_polling_loop()` as a thin wrapper for backward compatibility with existing mocks. This pattern aligns with codebase wiki guidance: 'Prefer module-level utility functions over instance methods.'","topic":null,"source_type":"plan","source_issue":6323,"source_repo":null,"created_at":"2026-04-10T04:47:03.630680+00:00","updated_at":"2026-04-10T04:47:03.630683+00:00","valid_from":"2026-04-10T04:47:03.630680+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Regex-based test parsing creates hard constraints on source structure

`test_loop_wiring_completeness.py` uses regex to parse `orchestrator.py` source for patterns like `('triage', self._triage_loop)` in loop_factories. Refactoring must preserve both the physical location and format of these definitions in orchestrator.py, not just the functionality. Any change to how loop_factories is defined will break the regex match and cause test failures, making this a critical constraint.

_Source: #6323 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WZ","title":"Regex-based test parsing creates hard constraints on source structure","content":"`test_loop_wiring_completeness.py` uses regex to parse `orchestrator.py` source for patterns like `('triage', self._triage_loop)` in loop_factories. Refactoring must preserve both the physical location and format of these definitions in orchestrator.py, not just the functionality. Any change to how loop_factories is defined will break the regex match and cause test failures, making this a critical constraint.","topic":null,"source_type":"plan","source_issue":6323,"source_repo":null,"created_at":"2026-04-10T04:47:03.630689+00:00","updated_at":"2026-04-10T04:47:03.630691+00:00","valid_from":"2026-04-10T04:47:03.630689+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use callbacks to decouple isolated components from orchestrator state

CreditPauseManager accepts `cancel_fn` and `resume_fn` callbacks instead of directly accessing loop task dicts. This avoids circular dependencies between manager and supervisor while allowing the manager to trigger orchestration actions (pause all loops, recreate them on resume). Apply this pattern whenever an extracted component needs to coordinate with the orchestration layer.

_Source: #6323 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X0","title":"Use callbacks to decouple isolated components from orchestrator state","content":"CreditPauseManager accepts `cancel_fn` and `resume_fn` callbacks instead of directly accessing loop task dicts. This avoids circular dependencies between manager and supervisor while allowing the manager to trigger orchestration actions (pause all loops, recreate them on resume). Apply this pattern whenever an extracted component needs to coordinate with the orchestration layer.","topic":null,"source_type":"plan","source_issue":6323,"source_repo":null,"created_at":"2026-04-10T04:47:03.630696+00:00","updated_at":"2026-04-10T04:47:03.630699+00:00","valid_from":"2026-04-10T04:47:03.630696+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Restrict extracted component imports to prevent circular dependencies

Extracted modules (PipelineStatsBuilder, CreditPauseManager, LoopSupervisor) must only import from a safe set: config, events, models, subprocess_util, service_registry, bg_worker_manager. Never import from orchestrator.py, even transitively. This strict boundary prevents import-time deadlocks and keeps extracted components independently testable and reusable.

_Source: #6323 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X1","title":"Restrict extracted component imports to prevent circular dependencies","content":"Extracted modules (PipelineStatsBuilder, CreditPauseManager, LoopSupervisor) must only import from a safe set: config, events, models, subprocess_util, service_registry, bg_worker_manager. Never import from orchestrator.py, even transitively. This strict boundary prevents import-time deadlocks and keeps extracted components independently testable and reusable.","topic":null,"source_type":"plan","source_issue":6323,"source_repo":null,"created_at":"2026-04-10T04:47:03.630704+00:00","updated_at":"2026-04-10T04:47:03.630706+00:00","valid_from":"2026-04-10T04:47:03.630704+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Logger names resolve to full module path from __name__

Modules using logging.getLogger(__name__) resolve to the full dotted module path (e.g., hydraflow.shape_phase), not just the filename (shape_phase). Tests that capture logs must use the full module path or logger name matchers will fail to find the expected logs.

_Source: #6325 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X2","title":"Logger names resolve to full module path from __name__","content":"Modules using logging.getLogger(__name__) resolve to the full dotted module path (e.g., hydraflow.shape_phase), not just the filename (shape_phase). Tests that capture logs must use the full module path or logger name matchers will fail to find the expected logs.","topic":null,"source_type":"plan","source_issue":6325,"source_repo":null,"created_at":"2026-04-10T04:51:52.058659+00:00","updated_at":"2026-04-10T04:51:52.058666+00:00","valid_from":"2026-04-10T04:51:52.058659+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## TYPE_CHECKING guard pattern for type-only imports

Use TYPE_CHECKING-guarded imports to avoid circular dependencies and runtime costs for type annotations. When a type is only needed for annotations (enabled by PEP 563 via `from __future__ import annotations`), import it under `if TYPE_CHECKING:` to prevent runtime import. This pattern is used consistently across 8+ files in the codebase and prevents the annotated name from triggering an actual import at runtime.

_Source: #6326 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X3","title":"TYPE_CHECKING guard pattern for type-only imports","content":"Use TYPE_CHECKING-guarded imports to avoid circular dependencies and runtime costs for type annotations. When a type is only needed for annotations (enabled by PEP 563 via `from __future__ import annotations`), import it under `if TYPE_CHECKING:` to prevent runtime import. This pattern is used consistently across 8+ files in the codebase and prevents the annotated name from triggering an actual import at runtime.","topic":null,"source_type":"plan","source_issue":6326,"source_repo":null,"created_at":"2026-04-10T04:56:50.953037+00:00","updated_at":"2026-04-10T04:56:50.953047+00:00","valid_from":"2026-04-10T04:56:50.953037+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## noqa: TCH004 required for TYPE_CHECKING imports

When using TYPE_CHECKING imports, always append `# noqa: TCH004` to suppress ruff's rule about imports appearing only in type checking. This is intentional and required for the pattern to work correctly. Omitting this comment will cause lint failures in the quality gates.

_Source: #6326 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X4","title":"noqa: TCH004 required for TYPE_CHECKING imports","content":"When using TYPE_CHECKING imports, always append `# noqa: TCH004` to suppress ruff's rule about imports appearing only in type checking. This is intentional and required for the pattern to work correctly. Omitting this comment will cause lint failures in the quality gates.","topic":null,"source_type":"plan","source_issue":6326,"source_repo":null,"created_at":"2026-04-10T04:56:50.953061+00:00","updated_at":"2026-04-10T04:56:50.953062+00:00","valid_from":"2026-04-10T04:56:50.953061+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## In-Place Mutation Requirement for Shared Dicts

If any sub-component reassigns a dict (e.g., `self._queues = {}`) instead of mutating in-place (e.g., `self._queues[stage].clear()`), the shared reference breaks and mutations become invisible to other components. This is the central risk — all state mutations in extracted classes must be in-place, not reassignment.

_Source: #6327 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X5","title":"In-Place Mutation Requirement for Shared Dicts","content":"If any sub-component reassigns a dict (e.g., `self._queues = {}`) instead of mutating in-place (e.g., `self._queues[stage].clear()`), the shared reference breaks and mutations become invisible to other components. This is the central risk — all state mutations in extracted classes must be in-place, not reassignment.","topic":null,"source_type":"plan","source_issue":6327,"source_repo":null,"created_at":"2026-04-10T05:07:55.384588+00:00","updated_at":"2026-04-10T05:07:55.384589+00:00","valid_from":"2026-04-10T05:07:55.384588+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Callback Construction Order: State → Snapshot → Router → Tracker

`_publish_queue_update_nowait` callback invokes `self._snapshot.get_queue_stats()`. Sub-components are constructed in order of dependency: state dicts first, then snapshot (used by publish_fn), then router and tracker (which receive publish_fn as a callback). Reordering breaks with AttributeError.

_Source: #6327 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X6","title":"Callback Construction Order: State → Snapshot → Router → Tracker","content":"`_publish_queue_update_nowait` callback invokes `self._snapshot.get_queue_stats()`. Sub-components are constructed in order of dependency: state dicts first, then snapshot (used by publish_fn), then router and tracker (which receive publish_fn as a callback). Reordering breaks with AttributeError.","topic":null,"source_type":"plan","source_issue":6327,"source_repo":null,"created_at":"2026-04-10T05:07:55.384592+00:00","updated_at":"2026-04-10T05:07:55.384593+00:00","valid_from":"2026-04-10T05:07:55.384592+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Immutable Scalars in Shared State Pattern

`_last_poll_ts` (a string) cannot be shared by reference like dicts — reassignment on the facade doesn't propagate to sub-components. Solution: snapshot's `get_queue_stats()` accepts `last_poll_ts` as a parameter; the facade passes `self._last_poll_ts` at call time. This pattern applies to any immutable scalar in shared state.

_Source: #6327 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X7","title":"Immutable Scalars in Shared State Pattern","content":"`_last_poll_ts` (a string) cannot be shared by reference like dicts — reassignment on the facade doesn't propagate to sub-components. Solution: snapshot's `get_queue_stats()` accepts `last_poll_ts` as a parameter; the facade passes `self._last_poll_ts` at call time. This pattern applies to any immutable scalar in shared state.","topic":null,"source_type":"plan","source_issue":6327,"source_repo":null,"created_at":"2026-04-10T05:07:55.384597+00:00","updated_at":"2026-04-10T05:07:55.384598+00:00","valid_from":"2026-04-10T05:07:55.384597+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Facade Exception: Public Method Limits for Behavioral Classes

The ≤7 public method / ≤200 line constraints apply to extracted behavioral classes (ActiveIssueTracker, IssueSnapshotBuilder, IssueQueueRouter). The facade necessarily retains 25 delegation stubs for backward compatibility per the documented pattern — this is not a violation of the rule, but a documented exception to preserve import paths and external consumers.

_Source: #6327 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X8","title":"Facade Exception: Public Method Limits for Behavioral Classes","content":"The ≤7 public method / ≤200 line constraints apply to extracted behavioral classes (ActiveIssueTracker, IssueSnapshotBuilder, IssueQueueRouter). The facade necessarily retains 25 delegation stubs for backward compatibility per the documented pattern — this is not a violation of the rule, but a documented exception to preserve import paths and external consumers.","topic":null,"source_type":"plan","source_issue":6327,"source_repo":null,"created_at":"2026-04-10T05:07:55.384601+00:00","updated_at":"2026-04-10T05:07:55.384602+00:00","valid_from":"2026-04-10T05:07:55.384601+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Coordinator pattern with call-order sensitivity

When extracting sub-methods from a large method, the original method becomes a thin orchestrator calling extracted methods in sequence. Execution order is critical—e.g., builder.record_history() must happen before builder.build_stats(). Preserve exact call order in the coordinator; tests should verify this order is maintained after extraction.

_Source: #6330 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X9","title":"Coordinator pattern with call-order sensitivity","content":"When extracting sub-methods from a large method, the original method becomes a thin orchestrator calling extracted methods in sequence. Execution order is critical—e.g., builder.record_history() must happen before builder.build_stats(). Preserve exact call order in the coordinator; tests should verify this order is maintained after extraction.","topic":null,"source_type":"plan","source_issue":6330,"source_repo":null,"created_at":"2026-04-10T05:17:59.124008+00:00","updated_at":"2026-04-10T05:17:59.124009+00:00","valid_from":"2026-04-10T05:17:59.124008+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## NamedTuple for multi-return extracted methods

When an extracted method returns multiple related values (like _build_context_sections returning multiple section strings), use a lightweight NamedTuple instead of creating a dataclass or new class. This avoids test infrastructure breakage while providing named access and self-documenting return types.

_Source: #6330 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XA","title":"NamedTuple for multi-return extracted methods","content":"When an extracted method returns multiple related values (like _build_context_sections returning multiple section strings), use a lightweight NamedTuple instead of creating a dataclass or new class. This avoids test infrastructure breakage while providing named access and self-documenting return types.","topic":null,"source_type":"plan","source_issue":6330,"source_repo":null,"created_at":"2026-04-10T05:17:59.124011+00:00","updated_at":"2026-04-10T05:17:59.124012+00:00","valid_from":"2026-04-10T05:17:59.124011+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Parameter threading across extracted methods

Some parameters (like bead_mapping) appear as arguments to multiple extracted methods across different extraction phases. Watch for these cross-cutting parameters during design—they indicate a concern that spans multiple extracted methods and should be threaded consistently through the coordinator to avoid silent bugs from missing arguments.

_Source: #6330 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XB","title":"Parameter threading across extracted methods","content":"Some parameters (like bead_mapping) appear as arguments to multiple extracted methods across different extraction phases. Watch for these cross-cutting parameters during design—they indicate a concern that spans multiple extracted methods and should be threaded consistently through the coordinator to avoid silent bugs from missing arguments.","topic":null,"source_type":"plan","source_issue":6330,"source_repo":null,"created_at":"2026-04-10T05:17:59.124014+00:00","updated_at":"2026-04-10T05:17:59.124016+00:00","valid_from":"2026-04-10T05:17:59.124014+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## TYPE_CHECKING prevents circular imports on cross-module TypedDicts

When a TypedDict is shared between a loop module and service module (ADRReviewResult in adr_reviewer_loop.py used by adr_reviewer.py), import under TYPE_CHECKING guard to avoid circular imports while preserving type information for static analysis. Codebase already uses this pattern extensively.

_Source: #6331 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XC","title":"TYPE_CHECKING prevents circular imports on cross-module TypedDicts","content":"When a TypedDict is shared between a loop module and service module (ADRReviewResult in adr_reviewer_loop.py used by adr_reviewer.py), import under TYPE_CHECKING guard to avoid circular imports while preserving type information for static analysis. Codebase already uses this pattern extensively.","topic":null,"source_type":"plan","source_issue":6331,"source_repo":null,"created_at":"2026-04-10T05:23:05.143432+00:00","updated_at":"2026-04-10T05:23:05.143433+00:00","valid_from":"2026-04-10T05:23:05.143432+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use sibling file patterns as architectural reference for consistency

When implementing a change, reference similar patterns in sibling files (e.g., _control_routes.py) to ensure consistency. This provides evidence that the pattern is established and approved in the codebase, reducing design ambiguity and potential review friction.

_Source: #6333 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XD","title":"Use sibling file patterns as architectural reference for consistency","content":"When implementing a change, reference similar patterns in sibling files (e.g., _control_routes.py) to ensure consistency. This provides evidence that the pattern is established and approved in the codebase, reducing design ambiguity and potential review friction.","topic":null,"source_type":"plan","source_issue":6333,"source_repo":null,"created_at":"2026-04-10T05:32:01.385950+00:00","updated_at":"2026-04-10T05:32:01.385951+00:00","valid_from":"2026-04-10T05:32:01.385950+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Template method exception to 50-line logic limit

Methods containing static prompt templates or configuration strings can exceed 50 lines of text while maintaining good design if the logic content is minimal (<5 lines). `_assemble_plan_prompt` will be ~110 lines but acceptable because it's an f-string template with variable interpolation only. Splitting such templates across multiple methods reduces readability of the full prompt.

_Source: #6332 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XE","title":"Template method exception to 50-line logic limit","content":"Methods containing static prompt templates or configuration strings can exceed 50 lines of text while maintaining good design if the logic content is minimal (<5 lines). `_assemble_plan_prompt` will be ~110 lines but acceptable because it's an f-string template with variable interpolation only. Splitting such templates across multiple methods reduces readability of the full prompt.","topic":null,"source_type":"plan","source_issue":6332,"source_repo":null,"created_at":"2026-04-10T05:33:08.098270+00:00","updated_at":"2026-04-10T05:33:08.098279+00:00","valid_from":"2026-04-10T05:33:08.098270+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Coordinator + focused helpers decomposition pattern

Decompose oversized methods by creating a lean coordinator (30-50 lines) that delegates to focused single-concern helpers (12-45 lines each). This pattern applies when a method mixes concerns like prompt assembly, retry coordination, and validation. Each helper encapsulates one concern; the coordinator orchestrates them without duplicating logic.

_Source: #6332 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XF","title":"Coordinator + focused helpers decomposition pattern","content":"Decompose oversized methods by creating a lean coordinator (30-50 lines) that delegates to focused single-concern helpers (12-45 lines each). This pattern applies when a method mixes concerns like prompt assembly, retry coordination, and validation. Each helper encapsulates one concern; the coordinator orchestrates them without duplicating logic.","topic":null,"source_type":"plan","source_issue":6332,"source_repo":null,"created_at":"2026-04-10T05:33:08.098291+00:00","updated_at":"2026-04-10T05:33:08.098292+00:00","valid_from":"2026-04-10T05:33:08.098291+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve deferred imports for optional dependencies

Use deferred imports (import inside method body, not module-level) for optional or infrequently-used dependencies like `prompt_dedup`. This avoids startup cost and avoids hard dependency failures in unrelated code paths. When refactoring such code, preserve the deferred import pattern.

_Source: #6332 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XG","title":"Preserve deferred imports for optional dependencies","content":"Use deferred imports (import inside method body, not module-level) for optional or infrequently-used dependencies like `prompt_dedup`. This avoids startup cost and avoids hard dependency failures in unrelated code paths. When refactoring such code, preserve the deferred import pattern.","topic":null,"source_type":"plan","source_issue":6332,"source_repo":null,"created_at":"2026-04-10T05:33:08.098298+00:00","updated_at":"2026-04-10T05:33:08.098299+00:00","valid_from":"2026-04-10T05:33:08.098298+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Validate diagram references point to existing code

Architecture diagrams (e.g., .likec4 files) can reference non-existent test files or code paths, creating confusion about implementation status. Before merging diagram changes, validate that all references (test files, classes, modules) actually exist in the codebase. This caught tests referenced but never created.

_Source: #6296 (review)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XH","title":"Validate diagram references point to existing code","content":"Architecture diagrams (e.g., .likec4 files) can reference non-existent test files or code paths, creating confusion about implementation status. Before merging diagram changes, validate that all references (test files, classes, modules) actually exist in the codebase. This caught tests referenced but never created.","topic":null,"source_type":"review","source_issue":6296,"source_repo":null,"created_at":"2026-04-10T05:36:08.671687+00:00","updated_at":"2026-04-10T05:36:08.671694+00:00","valid_from":"2026-04-10T05:36:08.671687+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Hindsight client cleanup ownership must be explicit

HindsightClient instances used in server modules need clear ownership semantics and cleanup paths. Resource leaks in clients compound across request lifecycles. Scope clients tightly and ensure they're explicitly closed, don't rely on GC.

_Source: #6296 (review)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XJ","title":"Hindsight client cleanup ownership must be explicit","content":"HindsightClient instances used in server modules need clear ownership semantics and cleanup paths. Resource leaks in clients compound across request lifecycles. Scope clients tightly and ensure they're explicitly closed, don't rely on GC.","topic":null,"source_type":"review","source_issue":6296,"source_repo":null,"created_at":"2026-04-10T05:36:08.671709+00:00","updated_at":"2026-04-10T05:36:08.671710+00:00","valid_from":"2026-04-10T05:36:08.671709+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Create regression test files before documentation reference

Don't reference regression test files in architecture documentation before they exist. Create the actual test file first, then reference it. Dangling references in diagrams signal incomplete implementation and confuse future maintainers.

_Source: #6296 (review)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XK","title":"Create regression test files before documentation reference","content":"Don't reference regression test files in architecture documentation before they exist. Create the actual test file first, then reference it. Dangling references in diagrams signal incomplete implementation and confuse future maintainers.","topic":null,"source_type":"review","source_issue":6296,"source_repo":null,"created_at":"2026-04-10T05:36:08.671712+00:00","updated_at":"2026-04-10T05:36:08.671713+00:00","valid_from":"2026-04-10T05:36:08.671712+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Architecture diagram scope can exceed implementation plan

Diagrams may be updated during implementation (e.g., adding .likec4 files) without being listed in the original plan. This is acceptable but should be tracked as documentation scope, not core implementation. Separate architectural updates from feature code in review.

_Source: #6296 (review)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XM","title":"Architecture diagram scope can exceed implementation plan","content":"Diagrams may be updated during implementation (e.g., adding .likec4 files) without being listed in the original plan. This is acceptable but should be tracked as documentation scope, not core implementation. Separate architectural updates from feature code in review.","topic":null,"source_type":"review","source_issue":6296,"source_repo":null,"created_at":"2026-04-10T05:36:08.671715+00:00","updated_at":"2026-04-10T05:36:08.671716+00:00","valid_from":"2026-04-10T05:36:08.671715+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Sub-factory coordination via intermediate frozen dataclass

When decomposing a large factory function, bundle frequently-shared infrastructure (10+) into a frozen dataclass (e.g., `_CoreDeps`) and pass it to downstream sub-factories. This pattern, inherited from `LoopDeps` in `base_background_loop.py`, reduces parameter explosion and makes dependency ownership explicit without requiring typed classes for every service group.

_Source: #6334 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XN","title":"Sub-factory coordination via intermediate frozen dataclass","content":"When decomposing a large factory function, bundle frequently-shared infrastructure (10+) into a frozen dataclass (e.g., `_CoreDeps`) and pass it to downstream sub-factories. This pattern, inherited from `LoopDeps` in `base_background_loop.py`, reduces parameter explosion and makes dependency ownership explicit without requiring typed classes for every service group.","topic":null,"source_type":"plan","source_issue":6334,"source_repo":null,"created_at":"2026-04-10T05:40:10.652297+00:00","updated_at":"2026-04-10T05:40:10.652309+00:00","valid_from":"2026-04-10T05:40:10.652297+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Distinguish local wiring from cross-group wiring at architecture boundary

Post-construction mutations fall into two categories: local (both objects created in same sub-factory, e.g., `shape_phase._council = ExpertCouncil(...)`) and cross-group (objects from different sub-factories, e.g., `agents._insights = review_insights`). Local wiring stays in the sub-factory; cross-group wiring moves to the thin orchestrator. This boundary clarifies dependency coupling.

_Source: #6334 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XP","title":"Distinguish local wiring from cross-group wiring at architecture boundary","content":"Post-construction mutations fall into two categories: local (both objects created in same sub-factory, e.g., `shape_phase._council = ExpertCouncil(...)`) and cross-group (objects from different sub-factories, e.g., `agents._insights = review_insights`). Local wiring stays in the sub-factory; cross-group wiring moves to the thin orchestrator. This boundary clarifies dependency coupling.","topic":null,"source_type":"plan","source_issue":6334,"source_repo":null,"created_at":"2026-04-10T05:40:10.652318+00:00","updated_at":"2026-04-10T05:40:10.652320+00:00","valid_from":"2026-04-10T05:40:10.652318+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Empty String Sentinel with Union Type Annotation

To allow a default empty string while maintaining type safety for valid values, use `FieldType | Literal[""]`. This pattern enables optional/unset states in strongly-typed fields without sacrificing validation of non-empty values.

_Source: #6335 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNQ","title":"Empty String Sentinel with Union Type Annotation","content":"To allow a default empty string while maintaining type safety for valid values, use `FieldType | Literal[\"\"]`. This pattern enables optional/unset states in strongly-typed fields without sacrificing validation of non-empty values.","topic":null,"source_type":"plan","source_issue":6335,"source_repo":null,"created_at":"2026-04-10T05:43:58.108257+00:00","updated_at":"2026-04-10T05:43:58.108261+00:00","valid_from":"2026-04-10T05:43:58.108257+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## StrEnum Fields Serialize Without Migration

StrEnum fields serialize to the same string values already persisted in storage (state.json, etc.). Converting a bare `str` field to StrEnum is schema-additive and requires no data migration per ADR-0021 (persistence architecture).

_Source: #6335 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNR","title":"StrEnum Fields Serialize Without Migration","content":"StrEnum fields serialize to the same string values already persisted in storage (state.json, etc.). Converting a bare `str` field to StrEnum is schema-additive and requires no data migration per ADR-0021 (persistence architecture).","topic":null,"source_type":"plan","source_issue":6335,"source_repo":null,"created_at":"2026-04-10T05:43:58.108275+00:00","updated_at":"2026-04-10T05:43:58.108277+00:00","valid_from":"2026-04-10T05:43:58.108275+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Naming conventions are pipeline-layer scoped

The GitHub-issue pipeline layer uses `issue_number` naming convention, but other domains (caching, memory scoring, review) intentionally keep `issue_id`. Don't over-generalize renames across modules—respect domain boundaries and only align naming where architectural layers actually overlap.

_Source: #6337 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNS","title":"Naming conventions are pipeline-layer scoped","content":"The GitHub-issue pipeline layer uses `issue_number` naming convention, but other domains (caching, memory scoring, review) intentionally keep `issue_id`. Don't over-generalize renames across modules—respect domain boundaries and only align naming where architectural layers actually overlap.","topic":null,"source_type":"plan","source_issue":6337,"source_repo":null,"created_at":"2026-04-10T05:49:11.253569+00:00","updated_at":"2026-04-10T05:49:11.253573+00:00","valid_from":"2026-04-10T05:49:11.253569+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## f-string output decoupled from parameter naming

Directory path format `issue-{N}` comes from f-string template, not the parameter name. Renaming the parameter doesn't affect directory structure, making the rename purely cosmetic at the output level.

_Source: #6337 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNT","title":"f-string output decoupled from parameter naming","content":"Directory path format `issue-{N}` comes from f-string template, not the parameter name. Renaming the parameter doesn't affect directory structure, making the rename purely cosmetic at the output level.","topic":null,"source_type":"plan","source_issue":6337,"source_repo":null,"created_at":"2026-04-10T05:49:11.253590+00:00","updated_at":"2026-04-10T05:49:11.253591+00:00","valid_from":"2026-04-10T05:49:11.253590+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Facade + Composition for Large Class Refactoring

When decomposing a large class (e.g., 947 lines, 37 methods) into focused sub-modules, use a facade + composition pattern: keep the original class as a thin public-facing facade with delegation stubs, move implementation to stateless or single-concern sub-modules. This preserves all import paths, isinstance checks, and mock targets, enabling zero-test-breakage refactors. All existing callers continue working unchanged.

_Source: #6338 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNV","title":"Facade + Composition for Large Class Refactoring","content":"When decomposing a large class (e.g., 947 lines, 37 methods) into focused sub-modules, use a facade + composition pattern: keep the original class as a thin public-facing facade with delegation stubs, move implementation to stateless or single-concern sub-modules. This preserves all import paths, isinstance checks, and mock targets, enabling zero-test-breakage refactors. All existing callers continue working unchanged.","topic":null,"source_type":"plan","source_issue":6338,"source_repo":null,"created_at":"2026-04-10T05:56:11.037220+00:00","updated_at":"2026-04-10T05:56:11.037230+00:00","valid_from":"2026-04-10T05:56:11.037220+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Acceptance Criteria: Distinguish Public Facades from Implementation

When refactoring with a facade pattern, acceptance criteria like "no class exceeds N public methods" should apply to *implementation classes*, not the facade. The facade may have many public methods (e.g., 12+) as delegation stubs—each stub is 1-2 lines. Implementation classes extracted into sub-modules stay under 7-8 public methods and 230 lines. Clarify this distinction upfront to avoid criteria conflicts.

_Source: #6338 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNW","title":"Acceptance Criteria: Distinguish Public Facades from Implementation","content":"When refactoring with a facade pattern, acceptance criteria like \"no class exceeds N public methods\" should apply to *implementation classes*, not the facade. The facade may have many public methods (e.g., 12+) as delegation stubs—each stub is 1-2 lines. Implementation classes extracted into sub-modules stay under 7-8 public methods and 230 lines. Clarify this distinction upfront to avoid criteria conflicts.","topic":null,"source_type":"plan","source_issue":6338,"source_repo":null,"created_at":"2026-04-10T05:56:11.037241+00:00","updated_at":"2026-04-10T05:56:11.037242+00:00","valid_from":"2026-04-10T05:56:11.037241+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Module-Level State via Constructor Injection

When extracted classes need access to module-level state (e.g., `_FETCH_LOCKS` dict for regression test patching), pass it via constructor injection (e.g., `fetch_lock_fn: Callable[[], asyncio.Lock]`) rather than direct imports. This avoids circular dependencies between the facade and extracted modules while preserving the ability to patch module-level state in tests.

_Source: #6338 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNX","title":"Module-Level State via Constructor Injection","content":"When extracted classes need access to module-level state (e.g., `_FETCH_LOCKS` dict for regression test patching), pass it via constructor injection (e.g., `fetch_lock_fn: Callable[[], asyncio.Lock]`) rather than direct imports. This avoids circular dependencies between the facade and extracted modules while preserving the ability to patch module-level state in tests.","topic":null,"source_type":"plan","source_issue":6338,"source_repo":null,"created_at":"2026-04-10T05:56:11.037248+00:00","updated_at":"2026-04-10T05:56:11.037249+00:00","valid_from":"2026-04-10T05:56:11.037248+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## FastAPI route registration order affects specificity matching

In FastAPI, routes are matched in registration order. Generic routes like `/{path:path}` (SPA catch-all) must be registered last or they shadow more specific routes. When decomposing monolithic route handlers into sub-modules, document the required registration order and verify catch-all placement during refactoring.

_Source: #6336 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNY","title":"FastAPI route registration order affects specificity matching","content":"In FastAPI, routes are matched in registration order. Generic routes like `/{path:path}` (SPA catch-all) must be registered last or they shadow more specific routes. When decomposing monolithic route handlers into sub-modules, document the required registration order and verify catch-all placement during refactoring.","topic":null,"source_type":"plan","source_issue":6336,"source_repo":null,"created_at":"2026-04-10T05:57:03.732493+00:00","updated_at":"2026-04-10T05:57:03.732510+00:00","valid_from":"2026-04-10T05:57:03.732493+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Convert closure mutable state to class-based encapsulation

When extracting stateful closures (e.g., cache dicts, timestamp lists, file paths) into separate modules, convert them into a class that encapsulates mutable state and provides methods. This replaces closure-scoped variables with instance state and makes cache invalidation logic explicit and testable rather than implicit in helper functions.

_Source: #6336 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNZ","title":"Convert closure mutable state to class-based encapsulation","content":"When extracting stateful closures (e.g., cache dicts, timestamp lists, file paths) into separate modules, convert them into a class that encapsulates mutable state and provides methods. This replaces closure-scoped variables with instance state and makes cache invalidation logic explicit and testable rather than implicit in helper functions.","topic":null,"source_type":"plan","source_issue":6336,"source_repo":null,"created_at":"2026-04-10T05:57:03.732527+00:00","updated_at":"2026-04-10T05:57:03.732530+00:00","valid_from":"2026-04-10T05:57:03.732527+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Endpoint path preservation enables test reuse across refactors

When refactoring monolithic route handlers into sub-modules, if endpoint paths remain unchanged, existing test files need no modification—they match endpoints by HTTP path, not by internal function structure. This allows high-confidence refactoring with zero test churn, since `make test` validates the entire endpoint surface area automatically.

_Source: #6336 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP0","title":"Endpoint path preservation enables test reuse across refactors","content":"When refactoring monolithic route handlers into sub-modules, if endpoint paths remain unchanged, existing test files need no modification—they match endpoints by HTTP path, not by internal function structure. This allows high-confidence refactoring with zero test churn, since `make test` validates the entire endpoint surface area automatically.","topic":null,"source_type":"plan","source_issue":6336,"source_repo":null,"created_at":"2026-04-10T05:57:03.732536+00:00","updated_at":"2026-04-10T05:57:03.732539+00:00","valid_from":"2026-04-10T05:57:03.732536+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Orchestrator pattern composes modules via deferred registration calls

A factory function can become a thin orchestrator (~80 lines) that creates a shared context object and delegates route registration to ~12 sub-modules via a consistent `register(router, ctx)` signature. Each sub-module owns 50–200 lines; the factory merely composes them. This pattern decouples endpoint logic from factory complexity and enables parallel implementation.

_Source: #6336 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP1","title":"Orchestrator pattern composes modules via deferred registration calls","content":"A factory function can become a thin orchestrator (~80 lines) that creates a shared context object and delegates route registration to ~12 sub-modules via a consistent `register(router, ctx)` signature. Each sub-module owns 50–200 lines; the factory merely composes them. This pattern decouples endpoint logic from factory complexity and enables parallel implementation.","topic":null,"source_type":"plan","source_issue":6336,"source_repo":null,"created_at":"2026-04-10T05:57:03.732554+00:00","updated_at":"2026-04-10T05:57:03.732557+00:00","valid_from":"2026-04-10T05:57:03.732554+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Avoid thin-wrapper abstractions—target concrete duplication

Rejected a `_build_base_prompt_context()` wrapper returning a tuple, noting it would create coupling without eliminating real duplication. Instead, target specific repeated code: only 4 runners share the memory query context string, only 2 share the dedup pattern. Extract only where there is genuine repeated code, not perceived similarity.

_Source: #6340 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP2","title":"Avoid thin-wrapper abstractions—target concrete duplication","content":"Rejected a `_build_base_prompt_context()` wrapper returning a tuple, noting it would create coupling without eliminating real duplication. Instead, target specific repeated code: only 4 runners share the memory query context string, only 2 share the dedup pattern. Extract only where there is genuine repeated code, not perceived similarity.","topic":null,"source_type":"plan","source_issue":6340,"source_repo":null,"created_at":"2026-04-10T06:11:06.699114+00:00","updated_at":"2026-04-10T06:11:06.699131+00:00","valid_from":"2026-04-10T06:11:06.699114+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve lazy imports to avoid module-level coupling

When extracting a helper that imports heavy or optional dependencies like `PromptDeduplicator`, keep the import lazy inside the method body, not at module level. This matches existing patterns in the codebase and avoids import-time coupling to utilities that may not be needed on every execution path.

_Source: #6340 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP3","title":"Preserve lazy imports to avoid module-level coupling","content":"When extracting a helper that imports heavy or optional dependencies like `PromptDeduplicator`, keep the import lazy inside the method body, not at module level. This matches existing patterns in the codebase and avoids import-time coupling to utilities that may not be needed on every execution path.","topic":null,"source_type":"plan","source_issue":6340,"source_repo":null,"created_at":"2026-04-10T06:11:06.699159+00:00","updated_at":"2026-04-10T06:11:06.699162+00:00","valid_from":"2026-04-10T06:11:06.699159+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Document variant patterns; resist premature parameterization

The plan notes that `triage.py` uses a similar memory context pattern but with space separator instead of newline. Rather than force parameterization to handle both, the plan keeps scope narrow and documents the variant for future follow-up. Over-parameterizing early adds complexity without immediate need.

_Source: #6340 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP4","title":"Document variant patterns; resist premature parameterization","content":"The plan notes that `triage.py` uses a similar memory context pattern but with space separator instead of newline. Rather than force parameterization to handle both, the plan keeps scope narrow and documents the variant for future follow-up. Over-parameterizing early adds complexity without immediate need.","topic":null,"source_type":"plan","source_issue":6340,"source_repo":null,"created_at":"2026-04-10T06:11:06.699170+00:00","updated_at":"2026-04-10T06:11:06.699173+00:00","valid_from":"2026-04-10T06:11:06.699170+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dependency injection + re-export for backward-compatible class splits

When splitting a large class into focused subclasses, inject the new dependencies into the parent constructor and re-export the new classes from the original module. This maintains API compatibility (`from epic import EpicStatusReporter` works) while separating concerns. Wiring happens in `ServiceRegistry`, not in the class constructors.

_Source: #6339 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP5","title":"Dependency injection + re-export for backward-compatible class splits","content":"When splitting a large class into focused subclasses, inject the new dependencies into the parent constructor and re-export the new classes from the original module. This maintains API compatibility (`from epic import EpicStatusReporter` works) while separating concerns. Wiring happens in `ServiceRegistry`, not in the class constructors.","topic":null,"source_type":"plan","source_issue":6339,"source_repo":null,"created_at":"2026-04-10T06:19:03.788137+00:00","updated_at":"2026-04-10T06:19:03.788154+00:00","valid_from":"2026-04-10T06:19:03.788137+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Strategy dispatcher pattern for conditional behavior branches

For methods with conditional logic based on an enum (e.g., release strategy: BUNDLED vs ORDERED vs HITL), create a single dispatcher method (`handle_ready(strategy)`) that routes to private strategy handlers. This centralizes the branching logic and makes it testable without exposing individual handlers.

_Source: #6339 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP6","title":"Strategy dispatcher pattern for conditional behavior branches","content":"For methods with conditional logic based on an enum (e.g., release strategy: BUNDLED vs ORDERED vs HITL), create a single dispatcher method (`handle_ready(strategy)`) that routes to private strategy handlers. This centralizes the branching logic and makes it testable without exposing individual handlers.","topic":null,"source_type":"plan","source_issue":6339,"source_repo":null,"created_at":"2026-04-10T06:19:03.788199+00:00","updated_at":"2026-04-10T06:19:03.788202+00:00","valid_from":"2026-04-10T06:19:03.788199+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Pydantic Field() accepts module-level int constants safely

Pydantic Field(le=...), Field(default=...), and Field(ge=...) accept plain int constants identically to literals. When extracting magic numbers into module-level constants for config classes, substitution is type-correct and requires no Pydantic-specific handling or adaptation.

_Source: #6341 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP7","title":"Pydantic Field() accepts module-level int constants safely","content":"Pydantic Field(le=...), Field(default=...), and Field(ge=...) accept plain int constants identically to literals. When extracting magic numbers into module-level constants for config classes, substitution is type-correct and requires no Pydantic-specific handling or adaptation.","topic":null,"source_type":"plan","source_issue":6341,"source_repo":null,"created_at":"2026-04-10T06:22:03.281124+00:00","updated_at":"2026-04-10T06:22:03.281131+00:00","valid_from":"2026-04-10T06:22:03.281124+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Export widely-reused constants without underscore prefix

Time duration constants imported across multiple modules (config.py, _common.py, tests/) should use public names without underscore prefix (ONE_DAY_SECS, not _ONE_DAY_SECS). Reserve underscore prefix for file-local-only constants to signal scope.

_Source: #6341 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP8","title":"Export widely-reused constants without underscore prefix","content":"Time duration constants imported across multiple modules (config.py, _common.py, tests/) should use public names without underscore prefix (ONE_DAY_SECS, not _ONE_DAY_SECS). Reserve underscore prefix for file-local-only constants to signal scope.","topic":null,"source_type":"plan","source_issue":6341,"source_repo":null,"created_at":"2026-04-10T06:22:03.281145+00:00","updated_at":"2026-04-10T06:22:03.281148+00:00","valid_from":"2026-04-10T06:22:03.281145+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Grep word-boundary verification for constant extraction refactors

After extracting magic numbers, verify completeness using grep word-boundary searches: grep -rn '\\b<literal>\\b' src/ tests/ should return exactly 1 match (the constant definition). Catches incomplete replacements and is language-agnostic, working across files and modules.

_Source: #6341 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP9","title":"Grep word-boundary verification for constant extraction refactors","content":"After extracting magic numbers, verify completeness using grep word-boundary searches: grep -rn '\\\\b<literal>\\\\b' src/ tests/ should return exactly 1 match (the constant definition). Catches incomplete replacements and is language-agnostic, working across files and modules.","topic":null,"source_type":"plan","source_issue":6341,"source_repo":null,"created_at":"2026-04-10T06:22:03.281162+00:00","updated_at":"2026-04-10T06:22:03.281163+00:00","valid_from":"2026-04-10T06:22:03.281162+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Design extracted methods for future integration without implementing it

Accept parameters that aren't currently used (e.g., `release_url` in `_build_close_comment()` is always passed as empty string) if they enable future feature work without forcing changes later. This is the inverse of premature abstraction: you're adding a seam, not a full feature.

_Source: #6342 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPA","title":"Design extracted methods for future integration without implementing it","content":"Accept parameters that aren't currently used (e.g., `release_url` in `_build_close_comment()` is always passed as empty string) if they enable future feature work without forcing changes later. This is the inverse of premature abstraction: you're adding a seam, not a full feature.","topic":null,"source_type":"plan","source_issue":6342,"source_repo":null,"created_at":"2026-04-10T06:32:57.301525+00:00","updated_at":"2026-04-10T06:32:57.301526+00:00","valid_from":"2026-04-10T06:32:57.301525+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve organizational comments during dead code removal

Section heading comments (e.g., '# --- reset ---', '# --- threshold tracking ---') and blank-line separators maintain code structure and readability. Preserve these markers even when adjacent dead methods are removed. They signal logical grouping to future readers and should survive refactoring.

_Source: #6345 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPB","title":"Preserve organizational comments during dead code removal","content":"Section heading comments (e.g., '# --- reset ---', '# --- threshold tracking ---') and blank-line separators maintain code structure and readability. Preserve these markers even when adjacent dead methods are removed. They signal logical grouping to future readers and should survive refactoring.","topic":null,"source_type":"plan","source_issue":6345,"source_repo":null,"created_at":"2026-04-10T06:35:05.468491+00:00","updated_at":"2026-04-10T06:35:05.468493+00:00","valid_from":"2026-04-10T06:35:05.468491+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Backward-compat layers require individual liveness evaluation

Backward-compatibility property collections may contain both live and dead items that cannot be blanket-evaluated. Example: review_phase.py has active _run_post_merge_hooks alongside dead _save_conflict_transcript. Verify each property individually rather than assuming a layer is wholly live or wholly dead.

_Source: #6345 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPC","title":"Backward-compat layers require individual liveness evaluation","content":"Backward-compatibility property collections may contain both live and dead items that cannot be blanket-evaluated. Example: review_phase.py has active _run_post_merge_hooks alongside dead _save_conflict_transcript. Verify each property individually rather than assuming a layer is wholly live or wholly dead.","topic":null,"source_type":"plan","source_issue":6345,"source_repo":null,"created_at":"2026-04-10T06:35:05.468495+00:00","updated_at":"2026-04-10T06:35:05.468496+00:00","valid_from":"2026-04-10T06:35:05.468495+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use method names not line numbers for refactoring plans

Identify code to remove by symbol name (def method_name) rather than line numbers. Files drift; methods remain stable. This reduces off-by-N errors and makes plans self-correcting when file structure changes.

_Source: #6346 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPD","title":"Use method names not line numbers for refactoring plans","content":"Identify code to remove by symbol name (def method_name) rather than line numbers. Files drift; methods remain stable. This reduces off-by-N errors and makes plans self-correcting when file structure changes.","topic":null,"source_type":"plan","source_issue":6346,"source_repo":null,"created_at":"2026-04-10T06:38:22.369945+00:00","updated_at":"2026-04-10T06:38:22.369947+00:00","valid_from":"2026-04-10T06:38:22.369945+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Document trade-off when removing implicit documentation

When a method like invalidate() serves as implicit documentation (its list of attributes documents cache structure), note that removal trades explicitness for simplicity. The data structure remains self-documenting through __init__ and usage patterns.

_Source: #6346 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPE","title":"Document trade-off when removing implicit documentation","content":"When a method like invalidate() serves as implicit documentation (its list of attributes documents cache structure), note that removal trades explicitness for simplicity. The data structure remains self-documenting through __init__ and usage patterns.","topic":null,"source_type":"plan","source_issue":6346,"source_repo":null,"created_at":"2026-04-10T06:38:22.369952+00:00","updated_at":"2026-04-10T06:38:22.369953+00:00","valid_from":"2026-04-10T06:38:22.369952+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Line number shifts in multi-PR merges break implementation plans

When a plan specifies exact line numbers for edits, document the search pattern (e.g., `def approve_count`) as a fallback. If other PRs merge first, line numbers shift—search-based edits remain valid and reduce merge conflicts.

_Source: #6347 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPF","title":"Line number shifts in multi-PR merges break implementation plans","content":"When a plan specifies exact line numbers for edits, document the search pattern (e.g., `def approve_count`) as a fallback. If other PRs merge first, line numbers shift—search-based edits remain valid and reduce merge conflicts.","topic":null,"source_type":"plan","source_issue":6347,"source_repo":null,"created_at":"2026-04-10T06:40:05.820990+00:00","updated_at":"2026-04-10T06:40:05.820992+00:00","valid_from":"2026-04-10T06:40:05.820990+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve module-specific guards when extracting duplicated logic

When consolidating duplicated parsing patterns, keep module-specific behavior (e.g., empty-transcript guards) outside the shared helper. In plan_compliance.py, the early-return guard precedes the shared pattern and must not be folded into the helper function. Extract only the common logic, leaving module-specific pre- or post-conditions in place.

_Source: #6349 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPG","title":"Preserve module-specific guards when extracting duplicated logic","content":"When consolidating duplicated parsing patterns, keep module-specific behavior (e.g., empty-transcript guards) outside the shared helper. In plan_compliance.py, the early-return guard precedes the shared pattern and must not be folded into the helper function. Extract only the common logic, leaving module-specific pre- or post-conditions in place.","topic":null,"source_type":"plan","source_issue":6349,"source_repo":null,"created_at":"2026-04-10T06:47:04.972401+00:00","updated_at":"2026-04-10T06:47:04.972412+00:00","valid_from":"2026-04-10T06:47:04.972401+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Structured transcript parsing: markers, summaries, and item lists

Transcripts can be parsed via three markers: result key (OK/RETRY status), summary section (captured text), and item list (extracted from bullet points). Case-insensitive matching and whitespace-tolerant list parsing make this pattern robust across variations in formatting and capitalization.

_Source: #6349 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPH","title":"Structured transcript parsing: markers, summaries, and item lists","content":"Transcripts can be parsed via three markers: result key (OK/RETRY status), summary section (captured text), and item list (extracted from bullet points). Case-insensitive matching and whitespace-tolerant list parsing make this pattern robust across variations in formatting and capitalization.","topic":null,"source_type":"plan","source_issue":6349,"source_repo":null,"created_at":"2026-04-10T06:47:04.972424+00:00","updated_at":"2026-04-10T06:47:04.972425+00:00","valid_from":"2026-04-10T06:47:04.972424+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Separate parsing utilities from subprocess and streaming concerns

Create new utility modules with clear, single responsibilities. Transcript parsing belongs in its own module, distinct from runner_utils which handles subprocess/streaming. This boundary prevents utility modules from becoming dumping grounds and keeps dependencies focused.

_Source: #6349 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPJ","title":"Separate parsing utilities from subprocess and streaming concerns","content":"Create new utility modules with clear, single responsibilities. Transcript parsing belongs in its own module, distinct from runner_utils which handles subprocess/streaming. This boundary prevents utility modules from becoming dumping grounds and keeps dependencies focused.","topic":null,"source_type":"plan","source_issue":6349,"source_repo":null,"created_at":"2026-04-10T06:47:04.972432+00:00","updated_at":"2026-04-10T06:47:04.972433+00:00","valid_from":"2026-04-10T06:47:04.972432+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Thin public wrappers replace private method access

When internal callers (e.g., `stale_issue_loop`, `sentry_loop`) access private methods on a façaded class (`_run_gh`, `_repo`), add thin public wrapper methods on the appropriate sub-client rather than exposing infrastructure. Example: add `list_open_issues_raw()` to `IssueClient` for `stale_issue_loop` to call instead of `_run_gh`. This maintains encapsulation boundaries while serving legitimate internal dependencies.

_Source: #6348 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPK","title":"Thin public wrappers replace private method access","content":"When internal callers (e.g., `stale_issue_loop`, `sentry_loop`) access private methods on a façaded class (`_run_gh`, `_repo`), add thin public wrapper methods on the appropriate sub-client rather than exposing infrastructure. Example: add `list_open_issues_raw()` to `IssueClient` for `stale_issue_loop` to call instead of `_run_gh`. This maintains encapsulation boundaries while serving legitimate internal dependencies.","topic":null,"source_type":"plan","source_issue":6348,"source_repo":null,"created_at":"2026-04-10T06:49:24.638890+00:00","updated_at":"2026-04-10T06:49:24.638891+00:00","valid_from":"2026-04-10T06:49:24.638890+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Line/method budgets force better decomposition

Hard constraints (≤200 lines, ~7 public methods per class) push better architectural decisions than soft targets. During this refactor, the large query methods didn't fit in a single 200-line `PRQueryClient`, forcing a split into `PRQueryClient` and `DashboardQueryClient`. The constraint prevented a bloated compromise class and revealed natural subdomain boundaries.

_Source: #6348 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPM","title":"Line/method budgets force better decomposition","content":"Hard constraints (≤200 lines, ~7 public methods per class) push better architectural decisions than soft targets. During this refactor, the large query methods didn't fit in a single 200-line `PRQueryClient`, forcing a split into `PRQueryClient` and `DashboardQueryClient`. The constraint prevented a bloated compromise class and revealed natural subdomain boundaries.","topic":null,"source_type":"plan","source_issue":6348,"source_repo":null,"created_at":"2026-04-10T06:49:24.638893+00:00","updated_at":"2026-04-10T06:49:24.638894+00:00","valid_from":"2026-04-10T06:49:24.638893+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Selective EventBus threading by behavioral side effects

Not all sub-clients need the same dependencies. Only sub-clients with behavioral side effects (publishing events: `PRLifecycle`, `IssueClient`, `CIStatusClient`) receive `EventBus` in `__init__`. Pure query clients (`PRQueryClient`, `MetricsClient`) don't. This selective dependency injection pattern avoids threading unnecessary dependencies through constructors and signals intent about what each component does.

_Source: #6348 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPN","title":"Selective EventBus threading by behavioral side effects","content":"Not all sub-clients need the same dependencies. Only sub-clients with behavioral side effects (publishing events: `PRLifecycle`, `IssueClient`, `CIStatusClient`) receive `EventBus` in `__init__`. Pure query clients (`PRQueryClient`, `MetricsClient`) don't. This selective dependency injection pattern avoids threading unnecessary dependencies through constructors and signals intent about what each component does.","topic":null,"source_type":"plan","source_issue":6348,"source_repo":null,"created_at":"2026-04-10T06:49:24.638897+00:00","updated_at":"2026-04-10T06:49:24.638897+00:00","valid_from":"2026-04-10T06:49:24.638897+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Deferred imports preserve test mocking patterns

Import hindsight and recall_tracker inside method bodies (not module-level) to allow `patch("hindsight.recall_safe", ...)` to intercept calls correctly. When imports are at the top of the file, patches may not apply to the actual import binding used by the method. This pattern is critical for testing async helpers that depend on external services.

_Source: #6350 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPP","title":"Deferred imports preserve test mocking patterns","content":"Import hindsight and recall_tracker inside method bodies (not module-level) to allow `patch(\"hindsight.recall_safe\", ...)` to intercept calls correctly. When imports are at the top of the file, patches may not apply to the actual import binding used by the method. This pattern is critical for testing async helpers that depend on external services.","topic":null,"source_type":"plan","source_issue":6350,"source_repo":null,"created_at":"2026-04-10T06:55:39.084035+00:00","updated_at":"2026-04-10T06:55:39.084043+00:00","valid_from":"2026-04-10T06:55:39.084035+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Config tuples enable clean parameterized loops

Replace copy-paste blocks with a list-of-tuples configuration like `[(Bank.TRIBAL, "learnings", "memory"), ...]` where each tuple drives one loop iteration. Each position in the tuple holds enum value, display label, and dict key. This pattern scales to N similar blocks and makes the parameterization explicit and maintainable.

_Source: #6350 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPQ","title":"Config tuples enable clean parameterized loops","content":"Replace copy-paste blocks with a list-of-tuples configuration like `[(Bank.TRIBAL, \"learnings\", \"memory\"), ...]` where each tuple drives one loop iteration. Each position in the tuple holds enum value, display label, and dict key. This pattern scales to N similar blocks and makes the parameterization explicit and maintainable.","topic":null,"source_type":"plan","source_issue":6350,"source_repo":null,"created_at":"2026-04-10T06:55:39.084060+00:00","updated_at":"2026-04-10T06:55:39.084061+00:00","valid_from":"2026-04-10T06:55:39.084060+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Accept typed enums, call .value internally

Helper methods should accept typed enums (ReviewerStatus, ReviewVerdict) at the signature level for caller type safety, then call `.value` internally when building string-keyed payloads. This pattern improves type checking at call sites without forcing callers to extract enum values manually.

_Source: #6351 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPR","title":"Accept typed enums, call .value internally","content":"Helper methods should accept typed enums (ReviewerStatus, ReviewVerdict) at the signature level for caller type safety, then call `.value` internally when building string-keyed payloads. This pattern improves type checking at call sites without forcing callers to extract enum values manually.","topic":null,"source_type":"plan","source_issue":6351,"source_repo":null,"created_at":"2026-04-10T06:58:24.321769+00:00","updated_at":"2026-04-10T06:58:24.321771+00:00","valid_from":"2026-04-10T06:58:24.321769+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Path prefix pattern for hierarchical object keys

When building dotted paths for nested objects, use `f"{path_prefix}.{key}" if path_prefix else key` to correctly handle both root-level (`key`) and nested (`parent.key`) cases. This avoids leading dots and false positives in path matching.

_Source: #6352 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPS","title":"Path prefix pattern for hierarchical object keys","content":"When building dotted paths for nested objects, use `f\"{path_prefix}.{key}\" if path_prefix else key` to correctly handle both root-level (`key`) and nested (`parent.key`) cases. This avoids leading dots and false positives in path matching.","topic":null,"source_type":"plan","source_issue":6352,"source_repo":null,"created_at":"2026-04-10T07:02:55.409396+00:00","updated_at":"2026-04-10T07:02:55.409404+00:00","valid_from":"2026-04-10T07:02:55.409396+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Partial migrations of similar components create maintenance burden

When multiple similar classes share the same pattern (e.g., 8 runner instantiations with identical kwargs), refactoring only some of them creates future maintenance risk. Always refactor all instances together, even if some seem unnecessary. Use explicit line-number lists to catch all occurrences and prevent partial migrations.

_Source: #6354 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPT","title":"Partial migrations of similar components create maintenance burden","content":"When multiple similar classes share the same pattern (e.g., 8 runner instantiations with identical kwargs), refactoring only some of them creates future maintenance risk. Always refactor all instances together, even if some seem unnecessary. Use explicit line-number lists to catch all occurrences and prevent partial migrations.","topic":null,"source_type":"plan","source_issue":6354,"source_repo":null,"created_at":"2026-04-10T07:09:55.773107+00:00","updated_at":"2026-04-10T07:09:55.773111+00:00","valid_from":"2026-04-10T07:09:55.773107+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use underscore prefix for local implementation details in functions

When defining intermediate variables in module-level functions (e.g., `_runner_kwargs`), use leading underscore to signal they are private implementation details, not public API. This convention improves readability and signals intent to future readers that the variable is not meant for external use.

_Source: #6354 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPV","title":"Use underscore prefix for local implementation details in functions","content":"When defining intermediate variables in module-level functions (e.g., `_runner_kwargs`), use leading underscore to signal they are private implementation details, not public API. This convention improves readability and signals intent to future readers that the variable is not meant for external use.","topic":null,"source_type":"plan","source_issue":6354,"source_repo":null,"created_at":"2026-04-10T07:09:55.773138+00:00","updated_at":"2026-04-10T07:09:55.773141+00:00","valid_from":"2026-04-10T07:09:55.773138+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Deferred Imports Must Remain Inside Helpers

Optional module imports that live inside a method should stay inside extracted helpers, not moved to module level. This preserves graceful degradation when optional modules are missing. Moving deferred imports breaks the intent of the original error-isolation pattern.

_Source: #6355 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPW","title":"Deferred Imports Must Remain Inside Helpers","content":"Optional module imports that live inside a method should stay inside extracted helpers, not moved to module level. This preserves graceful degradation when optional modules are missing. Moving deferred imports breaks the intent of the original error-isolation pattern.","topic":null,"source_type":"plan","source_issue":6355,"source_repo":null,"created_at":"2026-04-10T07:14:58.678248+00:00","updated_at":"2026-04-10T07:14:58.678250+00:00","valid_from":"2026-04-10T07:14:58.678248+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Return Value Threading in Orchestrator Pattern

When extracting helpers from a large method, extracted helpers should return values needed by downstream logic. The orchestrator captures these returns and threads them to consuming functions (e.g., metrics collection). This maintains clean value flow without side effects.

_Source: #6355 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPX","title":"Return Value Threading in Orchestrator Pattern","content":"When extracting helpers from a large method, extracted helpers should return values needed by downstream logic. The orchestrator captures these returns and threads them to consuming functions (e.g., metrics collection). This maintains clean value flow without side effects.","topic":null,"source_type":"plan","source_issue":6355,"source_repo":null,"created_at":"2026-04-10T07:14:58.678259+00:00","updated_at":"2026-04-10T07:14:58.678259+00:00","valid_from":"2026-04-10T07:14:58.678259+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Deferred imports in helper methods avoid circular dependencies

When extracting helper methods that need imports like trace_rollup, tracing_context, or phase_utils, place deferred imports (with # noqa: PLC0415) at the start of each helper's method body rather than hoisting to module level. This prevents circular import chains while keeping dependencies explicit and scoped to the methods that use them.

_Source: #6356 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPY","title":"Deferred imports in helper methods avoid circular dependencies","content":"When extracting helper methods that need imports like trace_rollup, tracing_context, or phase_utils, place deferred imports (with # noqa: PLC0415) at the start of each helper's method body rather than hoisting to module level. This prevents circular import chains while keeping dependencies explicit and scoped to the methods that use them.","topic":null,"source_type":"plan","source_issue":6356,"source_repo":null,"created_at":"2026-04-10T07:18:10.589088+00:00","updated_at":"2026-04-10T07:18:10.589099+00:00","valid_from":"2026-04-10T07:18:10.589088+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Deferred imports remain at usage sites with lint suppression

Deferred imports (MemoryScorer, CompletedTimeline, json) must stay inside method bodies where used, not hoisted to module level. Annotate with `# noqa: PLC0415` to suppress linting warnings. This keeps import coupling local to method scope and avoids unintended module-level dependencies.

_Source: #6358 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPZ","title":"Deferred imports remain at usage sites with lint suppression","content":"Deferred imports (MemoryScorer, CompletedTimeline, json) must stay inside method bodies where used, not hoisted to module level. Annotate with `# noqa: PLC0415` to suppress linting warnings. This keeps import coupling local to method scope and avoids unintended module-level dependencies.","topic":null,"source_type":"plan","source_issue":6358,"source_repo":null,"created_at":"2026-04-10T07:30:03.436784+00:00","updated_at":"2026-04-10T07:30:03.436785+00:00","valid_from":"2026-04-10T07:30:03.436784+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Sentry integration: ERROR+ only triggers alerts

LoggingIntegration(event_level=logging.ERROR) in server.py means only ERROR and above are sent to Sentry. WARNING-level records bypass Sentry entirely. Use this configuration pattern to prevent false-positive alerts from transient/handled errors while preserving them in structured logs.

_Source: #6359 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ0","title":"Sentry integration: ERROR+ only triggers alerts","content":"LoggingIntegration(event_level=logging.ERROR) in server.py means only ERROR and above are sent to Sentry. WARNING-level records bypass Sentry entirely. Use this configuration pattern to prevent false-positive alerts from transient/handled errors while preserving them in structured logs.","topic":null,"source_type":"plan","source_issue":6359,"source_repo":null,"created_at":"2026-04-10T07:33:04.050924+00:00","updated_at":"2026-04-10T07:33:04.050927+00:00","valid_from":"2026-04-10T07:33:04.050924+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Fatal error hierarchy—propagate vs. suppress

AuthenticationError and CreditExhaustedError are fatal and must propagate; all other exceptions are suppressed. This pattern is canonical across the codebase (base_background_loop.py:141, orchestrator.py:948, phase_utils.py:392). Always catch fatal errors first in except clauses before a generic Exception fallback.

_Source: #6360 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ1","title":"Fatal error hierarchy—propagate vs. suppress","content":"AuthenticationError and CreditExhaustedError are fatal and must propagate; all other exceptions are suppressed. This pattern is canonical across the codebase (base_background_loop.py:141, orchestrator.py:948, phase_utils.py:392). Always catch fatal errors first in except clauses before a generic Exception fallback.","topic":null,"source_type":"plan","source_issue":6360,"source_repo":null,"created_at":"2026-04-10T07:37:26.758732+00:00","updated_at":"2026-04-10T07:37:26.758748+00:00","valid_from":"2026-04-10T07:37:26.758732+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Polling loops must sleep when service disabled

Polling loops that run against a service should always check a boolean flag (e.g., _pipeline_enabled) and sleep when disabled. This prevents tight loops that attempt operations against uninitialized resources. See _polling_loop (line 940) pattern.

_Source: #6360 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ2","title":"Polling loops must sleep when service disabled","content":"Polling loops that run against a service should always check a boolean flag (e.g., _pipeline_enabled) and sleep when disabled. This prevents tight loops that attempt operations against uninitialized resources. See _polling_loop (line 940) pattern.","topic":null,"source_type":"plan","source_issue":6360,"source_repo":null,"created_at":"2026-04-10T07:37:26.758846+00:00","updated_at":"2026-04-10T07:37:26.758853+00:00","valid_from":"2026-04-10T07:37:26.758846+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Context manager protocol for async resource pooling

Add `__aenter__`/`__aexit__` to classes wrapping `httpx.AsyncClient`, delegating `__aexit__` to an existing `close()` method. Follow the exact pattern from `DockerRunner` (src/docker_runner.py:357-361) for type-safe implementation. This enables `async with` syntax and proper cleanup.

_Source: #6362 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ3","title":"Context manager protocol for async resource pooling","content":"Add `__aenter__`/`__aexit__` to classes wrapping `httpx.AsyncClient`, delegating `__aexit__` to an existing `close()` method. Follow the exact pattern from `DockerRunner` (src/docker_runner.py:357-361) for type-safe implementation. This enables `async with` syntax and proper cleanup.","topic":null,"source_type":"plan","source_issue":6362,"source_repo":null,"created_at":"2026-04-10T07:44:23.400349+00:00","updated_at":"2026-04-10T07:44:23.400389+00:00","valid_from":"2026-04-10T07:44:23.400349+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## httpx.AsyncClient.aclose() is idempotent and safe

httpx clients handle multiple `aclose()` calls gracefully (no-op on already-closed). Safe for multiple cleanup paths (e.g., orchestrator and ServiceRegistry both closing hindsight). Eliminates need for guard flags or state tracking.

_Source: #6362 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ4","title":"httpx.AsyncClient.aclose() is idempotent and safe","content":"httpx clients handle multiple `aclose()` calls gracefully (no-op on already-closed). Safe for multiple cleanup paths (e.g., orchestrator and ServiceRegistry both closing hindsight). Eliminates need for guard flags or state tracking.","topic":null,"source_type":"plan","source_issue":6362,"source_repo":null,"created_at":"2026-04-10T07:44:23.400455+00:00","updated_at":"2026-04-10T07:44:23.400460+00:00","valid_from":"2026-04-10T07:44:23.400455+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## AST-based regression tests are fragile to refactoring

Tests that walk the AST looking for specific function/variable names and nesting patterns break if code is renamed, wrapped, or restructured. Keep cleanup calls simple and direct—no indirection, no renaming, no extra nesting. Fragility is the cost of catching accidental refactorings.

_Source: #6362 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ5","title":"AST-based regression tests are fragile to refactoring","content":"Tests that walk the AST looking for specific function/variable names and nesting patterns break if code is renamed, wrapped, or restructured. Keep cleanup calls simple and direct—no indirection, no renaming, no extra nesting. Fragility is the cost of catching accidental refactorings.","topic":null,"source_type":"plan","source_issue":6362,"source_repo":null,"created_at":"2026-04-10T07:44:23.400467+00:00","updated_at":"2026-04-10T07:44:23.400470+00:00","valid_from":"2026-04-10T07:44:23.400467+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Never-raise contract uses broad exception catching

Health checks and diagnostic functions should catch `Exception` (not specific types like `httpx.HTTPError`) and return False/safe default rather than propagate. Matches the `*_safe` pattern used for functions that must not raise (e.g., `retain_safe`, `recall_safe`).

_Source: #6362 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ6","title":"Never-raise contract uses broad exception catching","content":"Health checks and diagnostic functions should catch `Exception` (not specific types like `httpx.HTTPError`) and return False/safe default rather than propagate. Matches the `*_safe` pattern used for functions that must not raise (e.g., `retain_safe`, `recall_safe`).","topic":null,"source_type":"plan","source_issue":6362,"source_repo":null,"created_at":"2026-04-10T07:44:23.400476+00:00","updated_at":"2026-04-10T07:44:23.400479+00:00","valid_from":"2026-04-10T07:44:23.400476+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Service composition root needs async cleanup method

ServiceRegistry (composition root) should have an `async def aclose()` method that closes owned resources like `self.hindsight`. Keep it as the first method on the dataclass. Enables caller to clean up composition root in one call.

_Source: #6362 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ7","title":"Service composition root needs async cleanup method","content":"ServiceRegistry (composition root) should have an `async def aclose()` method that closes owned resources like `self.hindsight`. Keep it as the first method on the dataclass. Enables caller to clean up composition root in one call.","topic":null,"source_type":"plan","source_issue":6362,"source_repo":null,"created_at":"2026-04-10T07:44:23.400484+00:00","updated_at":"2026-04-10T07:44:23.400487+00:00","valid_from":"2026-04-10T07:44:23.400484+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## exc_info=True parameter preserves full tracebacks at lower levels

logger.warning(..., exc_info=True) captures the full exception traceback in logs (visible in structured logs and observability tools) while downgrading the severity level. This enables post-incident debugging without triggering alerting systems designed for ERROR-level events.

_Source: #6363 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ8","title":"exc_info=True parameter preserves full tracebacks at lower levels","content":"logger.warning(..., exc_info=True) captures the full exception traceback in logs (visible in structured logs and observability tools) while downgrading the severity level. This enables post-incident debugging without triggering alerting systems designed for ERROR-level events.","topic":null,"source_type":"plan","source_issue":6363,"source_repo":null,"created_at":"2026-04-10T07:48:21.129667+00:00","updated_at":"2026-04-10T07:48:21.129669+00:00","valid_from":"2026-04-10T07:48:21.129667+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Distinguish similarly-named modules during cleanup

When removing dead code, watch for naming collisions—e.g., `verification.py` (orphaned formatter) vs `verification_judge.py` (active production code with real callers). Confusion between them can lead to removing live code or missing dependencies. Always verify caller graphs and module purpose separately.

_Source: #6365 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ9","title":"Distinguish similarly-named modules during cleanup","content":"When removing dead code, watch for naming collisions—e.g., `verification.py` (orphaned formatter) vs `verification_judge.py` (active production code with real callers). Confusion between them can lead to removing live code or missing dependencies. Always verify caller graphs and module purpose separately.","topic":null,"source_type":"plan","source_issue":6365,"source_repo":null,"created_at":"2026-04-10T07:59:04.461030+00:00","updated_at":"2026-04-10T07:59:04.461033+00:00","valid_from":"2026-04-10T07:59:04.461030+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Test class names describe scenarios, not test subjects

Test class names like `TestGCLoopNoCircuitBreaker` describe the scenario being tested (GC loop behavior without circuit breaking) rather than the code under test. When removing a module, check whether test classes with that name actually import or test it, or are simply documenting a test scenario.

_Source: #6365 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQA","title":"Test class names describe scenarios, not test subjects","content":"Test class names like `TestGCLoopNoCircuitBreaker` describe the scenario being tested (GC loop behavior without circuit breaking) rather than the code under test. When removing a module, check whether test classes with that name actually import or test it, or are simply documenting a test scenario.","topic":null,"source_type":"plan","source_issue":6365,"source_repo":null,"created_at":"2026-04-10T07:59:04.461043+00:00","updated_at":"2026-04-10T07:59:04.461045+00:00","valid_from":"2026-04-10T07:59:04.461043+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Inline implementations preferred over extracted utility classes

The orchestrator implements its own circuit-breaking logic (consecutive-failure counter at :926-1026) rather than using the extracted `CircuitBreaker` class. This suggests the project favors inline implementations for simple patterns over shared utility classes, reducing coupling and import complexity.

_Source: #6365 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQB","title":"Inline implementations preferred over extracted utility classes","content":"The orchestrator implements its own circuit-breaking logic (consecutive-failure counter at :926-1026) rather than using the extracted `CircuitBreaker` class. This suggests the project favors inline implementations for simple patterns over shared utility classes, reducing coupling and import complexity.","topic":null,"source_type":"plan","source_issue":6365,"source_repo":null,"created_at":"2026-04-10T07:59:04.461047+00:00","updated_at":"2026-04-10T07:59:04.461048+00:00","valid_from":"2026-04-10T07:59:04.461047+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Grep-based verification validates dead code removal completeness

After removing orphaned modules, use systematic grep for `from X import` patterns across src/ and tests/ to confirm no remaining references. This catches both direct imports and transitive dependencies, and serves as the acceptance criterion for cleanup completeness.

_Source: #6365 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQC","title":"Grep-based verification validates dead code removal completeness","content":"After removing orphaned modules, use systematic grep for `from X import` patterns across src/ and tests/ to confirm no remaining references. This catches both direct imports and transitive dependencies, and serves as the acceptance criterion for cleanup completeness.","topic":null,"source_type":"plan","source_issue":6365,"source_repo":null,"created_at":"2026-04-10T07:59:04.461050+00:00","updated_at":"2026-04-10T07:59:04.461051+00:00","valid_from":"2026-04-10T07:59:04.461050+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dead code removal verification via grep across codebase

When removing unused functions, verify with grep across both src/ and tests/ directories to ensure no remaining references. Pattern: grep -rn "symbol_name" src/ and grep -rn "symbol_name" tests/ should both return zero results after removal.

_Source: #6366 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQD","title":"Dead code removal verification via grep across codebase","content":"When removing unused functions, verify with grep across both src/ and tests/ directories to ensure no remaining references. Pattern: grep -rn \"symbol_name\" src/ and grep -rn \"symbol_name\" tests/ should both return zero results after removal.","topic":null,"source_type":"plan","source_issue":6366,"source_repo":null,"created_at":"2026-04-10T08:02:02.177024+00:00","updated_at":"2026-04-10T08:02:02.177033+00:00","valid_from":"2026-04-10T08:02:02.177024+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Audit __all__ exports when removing public functions

When removing public functions, check for stale __all__ exports or module re-exports that might still reference the removed symbols. This prevents subtle import errors and keeps the public API surface clean and explicit.

_Source: #6366 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQE","title":"Audit __all__ exports when removing public functions","content":"When removing public functions, check for stale __all__ exports or module re-exports that might still reference the removed symbols. This prevents subtle import errors and keeps the public API surface clean and explicit.","topic":null,"source_type":"plan","source_issue":6366,"source_repo":null,"created_at":"2026-04-10T08:02:02.177061+00:00","updated_at":"2026-04-10T08:02:02.177063+00:00","valid_from":"2026-04-10T08:02:02.177061+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6311

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6311 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQF","title":"Review patterns from #6311","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6311,"source_repo":null,"created_at":"2026-04-10T08:57:55.373407+00:00","updated_at":"2026-04-10T08:57:55.373409+00:00","valid_from":"2026-04-10T08:57:55.373407+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6309

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6309 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQG","title":"Review patterns from #6309","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6309,"source_repo":null,"created_at":"2026-04-10T08:57:55.395160+00:00","updated_at":"2026-04-10T08:57:55.395165+00:00","valid_from":"2026-04-10T08:57:55.395160+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6310

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6310 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQH","title":"Review patterns from #6310","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6310,"source_repo":null,"created_at":"2026-04-10T09:21:58.340223+00:00","updated_at":"2026-04-10T09:21:58.340225+00:00","valid_from":"2026-04-10T09:21:58.340223+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6312

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6312 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQJ","title":"Review patterns from #6312","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6312,"source_repo":null,"created_at":"2026-04-10T09:24:54.991719+00:00","updated_at":"2026-04-10T09:24:54.991722+00:00","valid_from":"2026-04-10T09:24:54.991719+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6313

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6313 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQK","title":"Review patterns from #6313","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6313,"source_repo":null,"created_at":"2026-04-10T09:44:55.478484+00:00","updated_at":"2026-04-10T09:44:55.478486+00:00","valid_from":"2026-04-10T09:44:55.478484+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6315

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6315 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQM","title":"Review patterns from #6315","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6315,"source_repo":null,"created_at":"2026-04-10T09:48:57.940327+00:00","updated_at":"2026-04-10T09:48:57.940333+00:00","valid_from":"2026-04-10T09:48:57.940327+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6314

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6314 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQN","title":"Review patterns from #6314","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6314,"source_repo":null,"created_at":"2026-04-10T10:09:52.312091+00:00","updated_at":"2026-04-10T10:09:52.312098+00:00","valid_from":"2026-04-10T10:09:52.312091+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6316

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6316 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQP","title":"Review patterns from #6316","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6316,"source_repo":null,"created_at":"2026-04-10T10:18:01.717692+00:00","updated_at":"2026-04-10T10:18:01.717698+00:00","valid_from":"2026-04-10T10:18:01.717692+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6318

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6318 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQQ","title":"Review patterns from #6318","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6318,"source_repo":null,"created_at":"2026-04-10T10:42:51.557727+00:00","updated_at":"2026-04-10T10:42:51.557730+00:00","valid_from":"2026-04-10T10:42:51.557727+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6320

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6320 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQR","title":"Review patterns from #6320","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6320,"source_repo":null,"created_at":"2026-04-10T10:43:59.246347+00:00","updated_at":"2026-04-10T10:43:59.246353+00:00","valid_from":"2026-04-10T10:43:59.246347+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6294

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6294 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQS","title":"Review patterns from #6294","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6294,"source_repo":null,"created_at":"2026-04-10T10:49:54.737951+00:00","updated_at":"2026-04-10T10:49:54.737956+00:00","valid_from":"2026-04-10T10:49:54.737951+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6322

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6322 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQT","title":"Review patterns from #6322","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6322,"source_repo":null,"created_at":"2026-04-10T11:07:53.400144+00:00","updated_at":"2026-04-10T11:07:53.400150+00:00","valid_from":"2026-04-10T11:07:53.400144+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6297

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6297 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQV","title":"Review patterns from #6297","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6297,"source_repo":null,"created_at":"2026-04-10T11:14:53.812715+00:00","updated_at":"2026-04-10T11:14:53.812725+00:00","valid_from":"2026-04-10T11:14:53.812715+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6323

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6323 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQW","title":"Review patterns from #6323","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6323,"source_repo":null,"created_at":"2026-04-10T11:32:55.993735+00:00","updated_at":"2026-04-10T11:32:55.993741+00:00","valid_from":"2026-04-10T11:32:55.993735+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6328

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6328 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQX","title":"Review patterns from #6328","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6328,"source_repo":null,"created_at":"2026-04-10T11:36:56.528046+00:00","updated_at":"2026-04-10T11:36:56.528049+00:00","valid_from":"2026-04-10T11:36:56.528046+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6299

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6299 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQY","title":"Review patterns from #6299","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6299,"source_repo":null,"created_at":"2026-04-10T11:43:56.815443+00:00","updated_at":"2026-04-10T11:43:56.815449+00:00","valid_from":"2026-04-10T11:43:56.815443+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6327

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6327 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQZ","title":"Review patterns from #6327","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6327,"source_repo":null,"created_at":"2026-04-10T12:01:56.126432+00:00","updated_at":"2026-04-10T12:01:56.126438+00:00","valid_from":"2026-04-10T12:01:56.126432+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6330

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6330 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQR0","title":"Review patterns from #6330","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6330,"source_repo":null,"created_at":"2026-04-10T12:12:56.546462+00:00","updated_at":"2026-04-10T12:12:56.546467+00:00","valid_from":"2026-04-10T12:12:56.546462+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6300

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6300 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQR1","title":"Review patterns from #6300","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6300,"source_repo":null,"created_at":"2026-04-10T12:22:56.417902+00:00","updated_at":"2026-04-10T12:22:56.417905+00:00","valid_from":"2026-04-10T12:22:56.417902+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6301

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6301 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQR2","title":"Review patterns from #6301","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6301,"source_repo":null,"created_at":"2026-04-10T12:26:56.518066+00:00","updated_at":"2026-04-10T12:26:56.518070+00:00","valid_from":"2026-04-10T12:26:56.518066+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6331

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6331 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQR3","title":"Review patterns from #6331","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6331,"source_repo":null,"created_at":"2026-04-10T12:34:56.020225+00:00","updated_at":"2026-04-10T12:34:56.020229+00:00","valid_from":"2026-04-10T12:34:56.020225+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Review patterns from #6334

API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC."},"request_id":"r

_Source: #6334 (review)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQR4","title":"Review patterns from #6334","content":"API Error: 400 {\"type\":\"error\",\"error\":{\"type\":\"invalid_request_error\",\"message\":\"You have reached your specified API usage limits. You will regain access on 2026-05-01 at 00:00 UTC.\"},\"request_id\":\"r","topic":null,"source_type":"review","source_issue":6334,"source_repo":null,"created_at":"2026-04-10T13:04:53.744630+00:00","updated_at":"2026-04-10T13:04:53.744637+00:00","valid_from":"2026-04-10T13:04:53.744630+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Trust Fleet — Lights-Off Background Loop Pattern

HydraFlow runs 10 autonomous trust loops + 2 non-loop subsystems (ADR-0045) that make every automated concern individually observable, killable, and escalatable without a human in the loop. The 10 loops: corpus_learning (skill-escape synthesis), contract_refresh (cassette refresh PRs), staging_bisect (auto-revert on RC red), principles_audit (ADR-0044 drift), flake_tracker (RC flake detection), skill_prompt_eval (weekly adversarial gate), fake_coverage_auditor (un-cassetted methods), rc_budget (wall-clock bloat), wiki_rot_detector (broken cites), trust_fleet_sanity (meta-observer). The 2 subsystems: discover-completeness/shape-coherence evaluator gates (§4.10) and the cost-rollups + diagnostics waterfall (§4.11). Every loop must (1) be a BaseBackgroundLoop subclass with the standard 8-checkpoint wiring; (2) gate every tick on LoopDeps.enabled_cb (ADR-0049); (3) persist dedup via DedupStore keyed on the anomaly; (4) escalate only via the hitl-escalation label; (5) tolerate environment imperfection on startup (broken gh, missing Makefile target, stale credentials → log + skip, never raise). The dark-factory property: no single loop failure can kill the orchestrator; the meta-observer + dead-man-switch make the fleet self-supervising through one bounded meta-layer. See also: Kill-Switch Convention; DedupStore + Reconcile Pattern; Five-Checkpoint Loop Wiring; Meta-Observability with Bounded Recursion.


```json:entry
{"id":"01KQ11A4G670SNNXM1DDZ98XHY","title":"Trust Fleet — Lights-Off Background Loop Pattern","content":"HydraFlow runs 10 autonomous trust loops + 2 non-loop subsystems (ADR-0045) that make every automated concern individually observable, killable, and escalatable without a human in the loop. The 10 loops: corpus_learning (skill-escape synthesis), contract_refresh (cassette refresh PRs), staging_bisect (auto-revert on RC red), principles_audit (ADR-0044 drift), flake_tracker (RC flake detection), skill_prompt_eval (weekly adversarial gate), fake_coverage_auditor (un-cassetted methods), rc_budget (wall-clock bloat), wiki_rot_detector (broken cites), trust_fleet_sanity (meta-observer). The 2 subsystems: discover-completeness/shape-coherence evaluator gates (§4.10) and the cost-rollups + diagnostics waterfall (§4.11). Every loop must (1) be a BaseBackgroundLoop subclass with the standard 8-checkpoint wiring; (2) gate every tick on LoopDeps.enabled_cb (ADR-0049); (3) persist dedup via DedupStore keyed on the anomaly; (4) escalate only via the hitl-escalation label; (5) tolerate environment imperfection on startup (broken gh, missing Makefile target, stale credentials → log + skip, never raise). The dark-factory property: no single loop failure can kill the orchestrator; the meta-observer + dead-man-switch make the fleet self-supervising through one bounded meta-layer. See also: Kill-Switch Convention; DedupStore + Reconcile Pattern; Five-Checkpoint Loop Wiring; Meta-Observability with Bounded Recursion.","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:40:54.022648+00:00","updated_at":"2026-04-25T00:40:54.022794+00:00","valid_from":"2026-04-25T00:40:54.022648+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## DedupStore + Reconcile-on-Close Pattern

Trust loops file one issue per anomaly (not one per tick). Pattern: (1) compute a stable dedup_key on the anomaly (test_id, sha, plan_name, etc.); (2) check if key in self._dedup.get(); if so, skip filing; (3) on file success, self._dedup.add(key); (4) every tick first calls _reconcile_closed_escalations: lists closed hitl-escalation issues via gh issue list, parses the dedup key from the issue title/body, removes those keys from DedupStore so the next anomaly with the same key re-files. The DedupStore is a filesystem-backed JSON set under .hydraflow/<loop>/dedup.json. Always wrap self._dedup.get() in set(...) before mutating in a loop body — DedupStore returns the backing set, not a copy. Loops that handle terminal events (corpus_learning consumes skill-escape issues; staging_bisect processes a red SHA) don't need reconcile-on-close — once processed, stays processed. Loops that handle ongoing anomalies (flake_tracker, rc_budget, wiki_rot_detector) MUST reconcile so an operator closing the issue clears the counter and lets the loop refile if the anomaly recurs. See also: HITL Escalation Channel; Trust Fleet Pattern.


```json:entry
{"id":"01KQ11A4G670SNNXM1DDZ98XJ0","title":"DedupStore + Reconcile-on-Close Pattern","content":"Trust loops file one issue per anomaly (not one per tick). Pattern: (1) compute a stable dedup_key on the anomaly (test_id, sha, plan_name, etc.); (2) check if key in self._dedup.get(); if so, skip filing; (3) on file success, self._dedup.add(key); (4) every tick first calls _reconcile_closed_escalations: lists closed hitl-escalation issues via gh issue list, parses the dedup key from the issue title/body, removes those keys from DedupStore so the next anomaly with the same key re-files. The DedupStore is a filesystem-backed JSON set under .hydraflow/<loop>/dedup.json. Always wrap self._dedup.get() in set(...) before mutating in a loop body — DedupStore returns the backing set, not a copy. Loops that handle terminal events (corpus_learning consumes skill-escape issues; staging_bisect processes a red SHA) don't need reconcile-on-close — once processed, stays processed. Loops that handle ongoing anomalies (flake_tracker, rc_budget, wiki_rot_detector) MUST reconcile so an operator closing the issue clears the counter and lets the loop refile if the anomaly recurs. See also: HITL Escalation Channel; Trust Fleet Pattern.","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:40:54.022843+00:00","updated_at":"2026-04-25T00:40:54.022844+00:00","valid_from":"2026-04-25T00:40:54.022843+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Eight-Checkpoint Loop Wiring

Adding a new BaseBackgroundLoop requires synchronized edits in eight places — miss one and the loop may not run, may not be operator-controllable, may not be tested, or will trip a CI drift gate. The eight checkpoints: (1) src/service_registry.py — dataclass field + build_services instantiation; (2) src/orchestrator.py bg_loop_registry dict + loop_factories tuple; (3) src/ui/src/constants.js EDITABLE_INTERVAL_WORKERS set + SYSTEM_WORKER_INTERVALS dict; (4) src/dashboard_routes/_common.py _INTERVAL_BOUNDS dict; (5) tests/scenarios/catalog/test_loop_instantiation.py + test_loop_registrations.py loops list + a tests/scenarios/test_<name>_scenario.py file + tests/scenarios/catalog/loop_registrations.py `_BUILDERS` entry + tests/orchestrator_integration_utils.py SimpleNamespace `services.<name>_loop = FakeBackgroundLoop()`; (6) src/dashboard_routes/_control_routes.py _bg_worker_defs entry (label + description) AND _INTERVAL_WORKERS membership — without this, /api/system/workers won't return the loop and the System tab UI won't render its kill-switch toggle (missed in PR #8390, fixed in #8416); (7) **docs/arch/functional_areas.yml** — the loop's class name MUST appear under exactly one area's `loops:` list; tests/architecture/test_functional_area_coverage.py is a hard gate (introduced PR #8434 with the Architecture Knowledge System; missed in PR #8447 follow-up, caught in `make quality` on PricingRefreshLoop branch); (8) **`uv run python -m arch.runner --emit`** to regenerate docs/arch/generated/* after step (7); the curated/generated drift guard (tests/architecture/test_curated_drift.py, also from PR #8434) is a hard gate that fails CI if generated docs don't match the source-of-truth extractors. Auto-discovery test at tests/test_loop_wiring_completeness.py walks src/*_loop.py and asserts every loop is wired in all checkpoints — run it to catch drift. See also: Kill-Switch Convention; Background Loops and Skill Infrastructure.


```json:entry
{"id":"01KQ11A4G670SNNXM1DDZ98XJ2","title":"Eight-Checkpoint Loop Wiring","content":"Adding a new BaseBackgroundLoop requires synchronized edits in eight places — miss one and the loop may not run, may not be operator-controllable, may not be tested, or will trip a CI drift gate. The eight checkpoints: (1) src/service_registry.py — dataclass field + build_services instantiation; (2) src/orchestrator.py bg_loop_registry dict + loop_factories tuple; (3) src/ui/src/constants.js EDITABLE_INTERVAL_WORKERS set + SYSTEM_WORKER_INTERVALS dict; (4) src/dashboard_routes/_common.py _INTERVAL_BOUNDS dict; (5) tests/scenarios/catalog/test_loop_instantiation.py + test_loop_registrations.py loops list + a tests/scenarios/test_<name>_scenario.py file + tests/scenarios/catalog/loop_registrations.py _BUILDERS entry + tests/orchestrator_integration_utils.py SimpleNamespace services.<name>_loop = FakeBackgroundLoop(); (6) src/dashboard_routes/_control_routes.py _bg_worker_defs entry (label + description) AND _INTERVAL_WORKERS membership — without this, /api/system/workers won't return the loop and the System tab UI won't render its kill-switch toggle (missed in PR #8390, fixed in #8416); (7) docs/arch/functional_areas.yml — the loop's class name MUST appear under exactly one area's loops: list; tests/architecture/test_functional_area_coverage.py is a hard gate (PR #8434 + PR #8447 follow-up); (8) uv run python -m arch.runner --emit to regenerate docs/arch/generated/* after step (7); the curated/generated drift guard (tests/architecture/test_curated_drift.py, PR #8434) is a hard gate that fails CI if generated docs don't match the source-of-truth extractors. Auto-discovery test at tests/test_loop_wiring_completeness.py walks src/*_loop.py and asserts every loop is wired in all checkpoints — run it to catch drift. See also: Kill-Switch Convention; Background Loops and Skill Infrastructure.","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:40:54.022859+00:00","updated_at":"2026-04-26T20:55:00.000000+00:00","valid_from":"2026-04-25T00:40:54.022859+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":2}
```


## Auto-Revert on RC Red — Four-Guardrail Policy

StagingBisectLoop auto-reverts on confirmed RC red with four guardrails (ADR-0048, extends ADR-0042's two-tier branch model). (1) Flake filter: re-run `make bisect-probe` against the same SHA; if the probe passes, increment flake_reruns_total, dedup the SHA, no revert. (2) Bisect attribution: git bisect between last_green_rc_sha and red SHA with `make bisect-probe` as the is-broken predicate, yielding a culprit SHA written into the revert PR body. (3) One auto-revert per cycle: state.get_auto_reverts_in_cycle(); after the first revert, _check_guardrail_and_maybe_escalate fires hitl-escalation + rc-red-attribution-unsafe (matching ADR-0048 §3 exactly — earlier code used the wrong label `rc-red-bisect-exhausted`, fixed in #8390). (4) Revert PR auto-merge: labels `[hydraflow-find, auto-revert, rc-red-attribution]`, flows through the standard reviewer + auto-merge path with no special privileges; an 8-hour watchdog (_check_pending_watchdog) fires rc-red-verify-timeout if the next RC isn't green. The probe MUST use asyncio.create_subprocess_exec (not subprocess.run) because long probes (up to 2700s) on a sync call freeze the event loop — caught in #8390 review. See also: Trust Fleet Pattern; Two-Tier Branch Model.


```json:entry
{"id":"01KQ11A4G670SNNXM1DDZ98XJ5","title":"Auto-Revert on RC Red — Four-Guardrail Policy","content":"StagingBisectLoop auto-reverts on confirmed RC red with four guardrails (ADR-0048, extends ADR-0042's two-tier branch model). (1) Flake filter: re-run `make bisect-probe` against the same SHA; if the probe passes, increment flake_reruns_total, dedup the SHA, no revert. (2) Bisect attribution: git bisect between last_green_rc_sha and red SHA with `make bisect-probe` as the is-broken predicate, yielding a culprit SHA written into the revert PR body. (3) One auto-revert per cycle: state.get_auto_reverts_in_cycle(); after the first revert, _check_guardrail_and_maybe_escalate fires hitl-escalation + rc-red-attribution-unsafe (matching ADR-0048 §3 exactly — earlier code used the wrong label `rc-red-bisect-exhausted`, fixed in #8390). (4) Revert PR auto-merge: labels `[hydraflow-find, auto-revert, rc-red-attribution]`, flows through the standard reviewer + auto-merge path with no special privileges; an 8-hour watchdog (_check_pending_watchdog) fires rc-red-verify-timeout if the next RC isn't green. The probe MUST use asyncio.create_subprocess_exec (not subprocess.run) because long probes (up to 2700s) on a sync call freeze the event loop — caught in #8390 review. See also: Trust Fleet Pattern; Two-Tier Branch Model.","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:40:54.022885+00:00","updated_at":"2026-04-25T00:40:54.022886+00:00","valid_from":"2026-04-25T00:40:54.022885+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Per-Loop Telemetry — emit_loop_subprocess_trace

Trust loops emit a JSON trace per subprocess call via trace_collector.emit_loop_subprocess_trace(loop, command, duration_ms, returncode). The trace flows through the same telemetry pipeline as inference traces, joined by timestamp in build_per_loop_cost (src/dashboard_routes/_cost_rollups.py) to attribute LLM cost + wall-clock seconds back to the originating loop. The waterfall view at /api/diagnostics/waterfall shows per-loop overlay. The per-loop cost row joins into /api/trust/fleet's loops array (cost_usd, tokens_in, tokens_out, llm_calls fields) so operators see fleet operability + machinery cost on the same pane (spec §4.11.3). Cost rollup failures are caught and reported as zero — an outage in the cost pipeline never takes down the trust dashboard. See also: Trust Fleet Pattern; Meta-Observability.


```json:entry
{"id":"01KQ11A4G670SNNXM1DDZ98XJ6","title":"Per-Loop Telemetry — emit_loop_subprocess_trace","content":"Trust loops emit a JSON trace per subprocess call via trace_collector.emit_loop_subprocess_trace(loop, command, duration_ms, returncode). The trace flows through the same telemetry pipeline as inference traces, joined by timestamp in build_per_loop_cost (src/dashboard_routes/_cost_rollups.py) to attribute LLM cost + wall-clock seconds back to the originating loop. The waterfall view at /api/diagnostics/waterfall shows per-loop overlay. The per-loop cost row joins into /api/trust/fleet's loops array (cost_usd, tokens_in, tokens_out, llm_calls fields) so operators see fleet operability + machinery cost on the same pane (spec §4.11.3). Cost rollup failures are caught and reported as zero — an outage in the cost pipeline never takes down the trust dashboard. See also: Trust Fleet Pattern; Meta-Observability.","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:40:54.022895+00:00","updated_at":"2026-04-25T00:40:54.022896+00:00","valid_from":"2026-04-25T00:40:54.022895+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Architecture

HydraFlow runs five concurrent async loops from `src/orchestrator.py`:

1. **Triage loop** — Fetches new issues, scores complexity, classifies type, and applies the `hydraflow-plan` label.
2. **Plan loop** — Fetches issues labeled `hydraflow-plan`, runs a read-only Claude agent to explore the codebase and produce an implementation plan, posts the plan as a comment, then swaps the label to `hydraflow-ready`.
3. **Implement loop** — Fetches issues labeled `hydraflow-ready`, creates git worktrees, runs implementation agents, pushes branches, creates PRs, then swaps to `hydraflow-review`.
4. **Review loop** — Fetches issues labeled `hydraflow-review`, runs a review agent to check quality and optionally fix issues, submits a formal PR review, waits for CI, and auto-merges approved PRs. CI failures escalate to `hydraflow-hitl` for human intervention.
5. **HITL loop** — Processes issues labeled `hydraflow-hitl` that need human-in-the-loop correction.

For the authoritative design rationale, see [`docs/adr/0001-five-concurrent-async-loops.md`](../adr/0001-five-concurrent-async-loops.md) and [`docs/adr/0002-labels-as-state-machine.md`](../adr/0002-labels-as-state-machine.md).


```json:entry
{"id":"01KQ11NX7GQ7PZX0266428BPN3","title":"Architecture","content":"HydraFlow runs five concurrent async loops from `src/orchestrator.py`:\n\n1. **Triage loop** — Fetches new issues, scores complexity, classifies type, and applies the `hydraflow-plan` label.\n2. **Plan loop** — Fetches issues labeled `hydraflow-plan`, runs a read-only Claude agent to explore the codebase and produce an implementation plan, posts the plan as a comment, then swaps the label to `hydraflow-ready`.\n3. **Implement loop** — Fetches issues labeled `hydraflow-ready`, creates git worktrees, runs implementation agents, pushes branches, creates PRs, then swaps to `hydraflow-review`.\n4. **Review loop** — Fetches issues labeled `hydraflow-review`, runs a review agent to check quality and optionally fix issues, submits a formal PR review, waits for CI, and auto-merges approved PRs. CI failures escalate to `hydraflow-hitl` for human intervention.\n5. **HITL loop** — Processes issues labeled `hydraflow-hitl` that need human-in-the-loop correction.\n\nFor the authoritative design rationale, see [`docs/adr/0001-five-concurrent-async-loops.md`](../adr/0001-five-concurrent-async-loops.md) and [`docs/adr/0002-labels-as-state-machine.md`](../adr/0002-labels-as-state-machine.md).","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.792850+00:00","updated_at":"2026-04-25T00:47:19.793007+00:00","valid_from":"2026-04-25T00:47:19.792850+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Key Files

### Core infrastructure
- `src/server.py` — Server entry point (`python -m server`)
- `scripts/run_admin_task.py` — Admin task runner (clean, prep, scaffold, ensure-labels)
- `src/orchestrator.py` — Main coordinator (five async polling loops)
- `src/config.py` — `HydraFlowConfig` Pydantic model (50+ env-var overrides)
- `src/models.py` — Pydantic data models (Phase, SessionLog, ReviewResult, etc.)
- `src/service_registry.py` — Composition root (`build_services()`); imports from all layers to wire dependencies
- `src/state.py` — `StateTracker` (JSON-backed crash recovery)
- `src/events.py` — `EventBus` async pub/sub

### Phase implementations
- `src/plan_phase.py` / `src/implement_phase.py` / `src/review_phase.py` / `src/triage_phase.py` / `src/hitl_phase.py`
- `src/phase_utils.py` — Shared phase utilities
- `src/pr_unsticker.py` — Stale PR recovery coordinator

### Agents and runners
- `src/agent.py` — `AgentRunner` (implementation agent)
- `src/planner.py` — `PlannerRunner` (read-only planning agent)
- `src/reviewer.py` — `ReviewRunner` (review + CI fix agent)
- `src/hitl_runner.py` — HITL correction agent
- `src/base_runner.py` — Base runner class

### Git and PR management
- `src/worktree.py` — `WorktreeManager` (git worktree lifecycle) — see [`docs/adr/0003-git-worktrees-for-isolation.md`](../adr/0003-git-worktrees-for-isolation.md)
- `src/pr_manager.py` — `PRManager` (all `gh` CLI operations)
- `src/merge_conflict_resolver.py` — Merge conflict resolution
- `src/post_merge_handler.py` — Post-merge cleanup

### Background loops
- `src/base_background_loop.py` — Base async loop pattern — see [`docs/adr/0029-caretaker-loop-pattern.md`](../adr/0029-caretaker-loop-pattern.md)
- `src/manifest_refresh_loop.py` / `src/memory_sync_loop.py` / `src/metrics_sync_loop.py` / `src/pr_unsticker_loop.py` — workers

### Dashboard
- `src/dashboard.py` + `src/dashboard_routes/` — FastAPI + WebSocket backend
- `ui/` — React + Vite frontend — see [`ui-standards.md`](ui-standards.md)

### Repo scaffolding (prep system)
- `src/prep.py` — Repository preparation orchestrator
- `src/ci_scaffold.py` / `src/lint_scaffold.py` / `src/test_scaffold.py` / `src/makefile_scaffold.py`
- `src/polyglot_prep.py` — Language detection

### Persistence
Per-repo state layout is documented in [`docs/adr/0021-persistence-architecture-and-data-layout.md`](../adr/0021-persistence-architecture-and-data-layout.md). Per-target-repo LLM knowledge base: [`src/repo_wiki.py`](../../src/repo_wiki.py) — see [`docs/adr/0032-per-repo-wiki-knowledge-base.md`](../adr/0032-per-repo-wiki-knowledge-base.md).


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PB8","title":"Key Files","content":"### Core infrastructure\n- `src/server.py` — Server entry point (`python -m server`)\n- `scripts/run_admin_task.py` — Admin task runner (clean, prep, scaffold, ensure-labels)\n- `src/orchestrator.py` — Main coordinator (five async polling loops)\n- `src/config.py` — `HydraFlowConfig` Pydantic model (50+ env-var overrides)\n- `src/models.py` — Pydantic data models (Phase, SessionLog, ReviewResult, etc.)\n- `src/service_registry.py` — Composition root (`build_services()`); imports from all layers to wire dependencies\n- `src/state.py` — `StateTracker` (JSON-backed crash recovery)\n- `src/events.py` — `EventBus` async pub/sub\n\n### Phase implementations\n- `src/plan_phase.py` / `src/implement_phase.py` / `src/review_phase.py` / `src/triage_phase.py` / `src/hitl_phase.py`\n- `src/phase_utils.py` — Shared phase utilities\n- `src/pr_unsticker.py` — Stale PR recovery coordinator\n\n### Agents and runners\n- `src/agent.py` — `AgentRunner` (implementation agent)\n- `src/planner.py` — `PlannerRunner` (read-only planning agent)\n- `src/reviewer.py` — `ReviewRunner` (review + CI fix agent)\n- `src/hitl_runner.py` — HITL correction agent\n- `src/base_runner.py` — Base runner class\n\n### Git and PR management\n- `src/worktree.py` — `WorktreeManager` (git worktree lifecycle) — see [`docs/adr/0003-git-worktrees-for-isolation.md`](../adr/0003-git-worktrees-for-isolation.md)\n- `src/pr_manager.py` — `PRManager` (all `gh` CLI operations)\n- `src/merge_conflict_resolver.py` — Merge conflict resolution\n- `src/post_merge_handler.py` — Post-merge cleanup\n\n### Background loops\n- `src/base_background_loop.py` — Base async loop pattern — see [`docs/adr/0029-caretaker-loop-pattern.md`](../adr/0029-caretaker-loop-pattern.md)\n- `src/manifest_refresh_loop.py` / `src/memory_sync_loop.py` / `src/metrics_sync_loop.py` / `src/pr_unsticker_loop.py` — workers\n\n### Dashboard\n- `src/dashboard.py` + `src/dashboard_routes/` — FastAPI + WebSocket backend\n- `ui/` — React + Vite frontend — see [`ui-standards.md`](ui-standards.md)\n\n### Repo scaffolding (prep system)\n- `src/prep.py` — Repository preparation orchestrator\n- `src/ci_scaffold.py` / `src/lint_scaffold.py` / `src/test_scaffold.py` / `src/makefile_scaffold.py`\n- `src/polyglot_prep.py` — Language detection\n\n### Persistence\nPer-repo state layout is documented in [`docs/adr/0021-persistence-architecture-and-data-layout.md`](../adr/0021-persistence-architecture-and-data-layout.md). Per-target-repo LLM knowledge base: [`src/repo_wiki.py`](../../src/repo_wiki.py) — see [`docs/adr/0032-per-repo-wiki-knowledge-base.md`](../adr/0032-per-repo-wiki-knowledge-base.md).","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793040+00:00","updated_at":"2026-04-25T00:47:19.793041+00:00","valid_from":"2026-04-25T00:47:19.793040+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Spawning background sleep loops to poll for results

Never write `sleep(N)` inside a loop waiting for a test suite or background process to finish.

**Wrong:**

```python
while not result_file.exists():
    time.sleep(5)
```

**Right:**

- Use `run_in_background` with a single command and wait on the notification.
- Run the command in the foreground and await its completion directly.

**Why:** Sleep loops waste wall clock, mask failures, and provide no structured feedback. The harness exposes explicit background-task primitives for this exact purpose — use them.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBD","title":"Spawning background sleep loops to poll for results","content":"Never write `sleep(N)` inside a loop waiting for a test suite or background process to finish.\n\n**Wrong:**\n\n```python\nwhile not result_file.exists():\n    time.sleep(5)\n```\n\n**Right:**\n\n- Use `run_in_background` with a single command and wait on the notification.\n- Run the command in the foreground and await its completion directly.\n\n**Why:** Sleep loops waste wall clock, mask failures, and provide no structured feedback. The harness exposes explicit background-task primitives for this exact purpose — use them.","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793224+00:00","updated_at":"2026-04-25T00:47:19.793225+00:00","valid_from":"2026-04-25T00:47:19.793224+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Mocking at the wrong level

Patch functions at their **import site**, not their **definition site**.

If `src/base_runner.py` contains `from hindsight import recall_safe`, then within `base_runner` the name `recall_safe` is a local binding. Patching `hindsight.recall_safe` at the definition module leaves the local binding unchanged and the mock is never hit.

**Wrong:**

```python
with patch("hindsight.recall_safe") as mock_recall:
    runner.run()  # runner's local `recall_safe` binding is unaffected
```

**Right:**

```python
with patch("base_runner.recall_safe") as mock_recall:
    runner.run()  # patches the binding the runner actually calls
```

**Why:** Python imports bind names into the importing module's namespace. A patch at the definition module only affects callers that go through that module explicitly, not callers that imported the name locally.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBE","title":"Mocking at the wrong level","content":"Patch functions at their **import site**, not their **definition site**.\n\nIf `src/base_runner.py` contains `from hindsight import recall_safe`, then within `base_runner` the name `recall_safe` is a local binding. Patching `hindsight.recall_safe` at the definition module leaves the local binding unchanged and the mock is never hit.\n\n**Wrong:**\n\n```python\nwith patch(\"hindsight.recall_safe\") as mock_recall:\n    runner.run()  # runner's local `recall_safe` binding is unaffected\n```\n\n**Right:**\n\n```python\nwith patch(\"base_runner.recall_safe\") as mock_recall:\n    runner.run()  # patches the binding the runner actually calls\n```\n\n**Why:** Python imports bind names into the importing module's namespace. A patch at the definition module only affects callers that go through that module explicitly, not callers that imported the name locally.","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793237+00:00","updated_at":"2026-04-25T00:47:19.793238+00:00","valid_from":"2026-04-25T00:47:19.793237+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Hardcoded path lists that duplicate filesystem state

When multiple files (Dockerfile, Python constant, documentation) must agree on a list of paths or names, scan the authoritative source at runtime instead of hardcoding a parallel list that can drift.

**Wrong:**

```python
# src/agent_cli.py
_DOCKER_PLUGIN_DIRS: tuple[str, ...] = (
    "/opt/plugins/claude-plugins-official",
    "/opt/plugins/superpowers",
    "/opt/plugins/lightfactory",
)
# Dockerfile.agent-base clones these three — but if a fourth is added
# there, this tuple silently stays wrong.
```

**Right:**

```python
# src/agent_cli.py
_PRE_CLONED_PLUGIN_ROOT = Path("/opt/plugins")

def _plugin_dir_flags() -> list[str]:
    if not _PRE_CLONED_PLUGIN_ROOT.is_dir():
        return []
    flags: list[str] = []
    for entry in sorted(_PRE_CLONED_PLUGIN_ROOT.iterdir()):
        if entry.is_dir():
            flags.extend(["--plugin-dir", str(entry)])
    return flags
```

**Why:** Two sources of truth decay. Every time someone edits the Dockerfile, CI passes but the Python list falls behind. Dynamic enumeration of the filesystem (or a single config source) eliminates the drift.

**How to check:** Any hardcoded list that mirrors filesystem layout, Dockerfile state, or config file contents should raise a flag — can it be computed at runtime from the source of truth?


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBK","title":"Hardcoded path lists that duplicate filesystem state","content":"When multiple files (Dockerfile, Python constant, documentation) must agree on a list of paths or names, scan the authoritative source at runtime instead of hardcoding a parallel list that can drift.\n\n**Wrong:**\n\n```python\n# src/agent_cli.py\n_DOCKER_PLUGIN_DIRS: tuple[str, ...] = (\n    \"/opt/plugins/claude-plugins-official\",\n    \"/opt/plugins/superpowers\",\n    \"/opt/plugins/lightfactory\",\n)\n# Dockerfile.agent-base clones these three — but if a fourth is added\n# there, this tuple silently stays wrong.\n```\n\n**Right:**\n\n```python\n# src/agent_cli.py\n_PRE_CLONED_PLUGIN_ROOT = Path(\"/opt/plugins\")\n\ndef _plugin_dir_flags() -> list[str]:\n    if not _PRE_CLONED_PLUGIN_ROOT.is_dir():\n        return []\n    flags: list[str] = []\n    for entry in sorted(_PRE_CLONED_PLUGIN_ROOT.iterdir()):\n        if entry.is_dir():\n            flags.extend([\"--plugin-dir\", str(entry)])\n    return flags\n```\n\n**Why:** Two sources of truth decay. Every time someone edits the Dockerfile, CI passes but the Python list falls behind. Dynamic enumeration of the filesystem (or a single config source) eliminates the drift.\n\n**How to check:** Any hardcoded list that mirrors filesystem layout, Dockerfile state, or config file contents should raise a flag — can it be computed at runtime from the source of truth?","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793271+00:00","updated_at":"2026-04-25T00:47:19.793272+00:00","valid_from":"2026-04-25T00:47:19.793271+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Adding a new avoided pattern

When you observe a new recurring agent failure:

1. Add a new `##` section to this doc with the same structure (wrong example, right example, why).
2. Consider adding a rule to `src/sensor_rules.py` so the sensor enricher surfaces the hint automatically on matching failures.
3. Consider whether `.claude/commands/hf.audit-code.md` Agent 5 (convention drift) should check for this pattern on its next sweep.

Documenting the pattern once in this file propagates it to all three surfaces.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBN","title":"Adding a new avoided pattern","content":"When you observe a new recurring agent failure:\n\n1. Add a new `##` section to this doc with the same structure (wrong example, right example, why).\n2. Consider adding a rule to `src/sensor_rules.py` so the sensor enricher surfaces the hint automatically on matching failures.\n3. Consider whether `.claude/commands/hf.audit-code.md` Agent 5 (convention drift) should check for this pattern on its next sweep.\n\nDocumenting the pattern once in this file propagates it to all three surfaces.","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793282+00:00","updated_at":"2026-04-25T00:47:19.793283+00:00","valid_from":"2026-04-25T00:47:19.793282+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Background Loop Guidelines

When creating a new background loop (`BaseBackgroundLoop` subclass):

1. **Use `make scaffold-loop`** to generate boilerplate — it handles all wiring.

2. **Restart safety.** Any `self._` state that affects behavior across cycles must either:
   - Be persisted via `StateTracker` or `DedupStore` (survives restart)
   - Be rehydrated from an external source (GitHub API) on first `_do_work()` cycle
   - Be explicitly documented as ephemeral with a `# ephemeral: lost on restart` comment

3. **Wiring checklist** (automated by `tests/test_loop_wiring_completeness.py`):
   - `src/service_registry.py` — dataclass field + `build_services()` instantiation
   - `src/orchestrator.py` — entry in `bg_loop_registry` dict
   - `src/ui/src/constants.js` — entry in `BACKGROUND_WORKERS`
   - `src/dashboard_routes/_common.py` — entry in `_INTERVAL_BOUNDS`
   - `src/config.py` — interval Field + `_ENV_INT_OVERRIDES` entry

Missing any of these five entries will cause `test_loop_wiring_completeness` to fail. Add them all in the same commit.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBP","title":"Background Loop Guidelines","content":"When creating a new background loop (`BaseBackgroundLoop` subclass):\n\n1. **Use `make scaffold-loop`** to generate boilerplate — it handles all wiring.\n\n2. **Restart safety.** Any `self._` state that affects behavior across cycles must either:\n   - Be persisted via `StateTracker` or `DedupStore` (survives restart)\n   - Be rehydrated from an external source (GitHub API) on first `_do_work()` cycle\n   - Be explicitly documented as ephemeral with a `# ephemeral: lost on restart` comment\n\n3. **Wiring checklist** (automated by `tests/test_loop_wiring_completeness.py`):\n   - `src/service_registry.py` — dataclass field + `build_services()` instantiation\n   - `src/orchestrator.py` — entry in `bg_loop_registry` dict\n   - `src/ui/src/constants.js` — entry in `BACKGROUND_WORKERS`\n   - `src/dashboard_routes/_common.py` — entry in `_INTERVAL_BOUNDS`\n   - `src/config.py` — interval Field + `_ENV_INT_OVERRIDES` entry\n\nMissing any of these five entries will cause `test_loop_wiring_completeness` to fail. Add them all in the same commit.","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793357+00:00","updated_at":"2026-04-25T00:47:19.793358+00:00","valid_from":"2026-04-25T00:47:19.793357+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Design rationale

See [`docs/adr/0029-caretaker-loop-pattern.md`](../adr/0029-caretaker-loop-pattern.md) for the caretaker loop pattern, and [`docs/adr/0019-background-task-delegation-abstraction-layer.md`](../adr/0019-background-task-delegation-abstraction-layer.md) for the delegation abstraction.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBR","title":"Design rationale","content":"See [`docs/adr/0029-caretaker-loop-pattern.md`](../adr/0029-caretaker-loop-pattern.md) for the caretaker loop pattern, and [`docs/adr/0019-background-task-delegation-abstraction-layer.md`](../adr/0019-background-task-delegation-abstraction-layer.md) for the delegation abstraction.","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793369+00:00","updated_at":"2026-04-25T00:47:19.793369+00:00","valid_from":"2026-04-25T00:47:19.793369+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Sequence before committing

1. After each significant code change: `make lint` (auto-fixes formatting and imports)
2. Before committing: `make quality` (lint + typecheck + security + tests in parallel)
3. If lint auto-fixes files, re-check for type errors introduced by removed imports
4. Track your edits across files — avoid creating duplicate helpers or inconsistent naming when refactoring multiple test files
5. Merge consecutive identical if-conditions so the shared guard is evaluated once. When you see redundant chains like `if A and B: ... elif A and not B: ...`, restructure them as `if A: if B: ... else: ...` to keep the shared condition centralized and avoid logic drift.

The `/hf.quality-gate` slash command runs a structured quality check sequence. Use it before presenting work as complete.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PC1","title":"Sequence before committing","content":"1. After each significant code change: `make lint` (auto-fixes formatting and imports)\n2. Before committing: `make quality` (lint + typecheck + security + tests in parallel)\n3. If lint auto-fixes files, re-check for type errors introduced by removed imports\n4. Track your edits across files — avoid creating duplicate helpers or inconsistent naming when refactoring multiple test files\n5. Merge consecutive identical if-conditions so the shared guard is evaluated once. When you see redundant chains like `if A and B: ... elif A and not B: ...`, restructure them as `if A: if B: ... else: ...` to keep the shared condition centralized and avoid logic drift.\n\nThe `/hf.quality-gate` slash command runs a structured quality check sequence. Use it before presenting work as complete.","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793543+00:00","updated_at":"2026-04-25T00:47:19.793543+00:00","valid_from":"2026-04-25T00:47:19.793543+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Related

- [`testing.md`](testing.md) — test requirements
- [`avoided-patterns.md`](avoided-patterns.md) — mistakes that commonly slip through quality gates
- [`commands.md`](commands.md) — full `make` target reference


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PC5","title":"Related","content":"- [`testing.md`](testing.md) — test requirements\n- [`avoided-patterns.md`](avoided-patterns.md) — mistakes that commonly slip through quality gates\n- [`commands.md`](commands.md) — full `make` target reference","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793564+00:00","updated_at":"2026-04-25T00:47:19.793565+00:00","valid_from":"2026-04-25T00:47:19.793564+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Layout

- **CSS Grid** for page-level layout (`App.jsx`), **Flexbox** for component internals
- Sidebar is fixed at `280px`; set `flexShrink: 0` on fixed-width panels and connectors
- Set `minWidth` on containers to prevent content overlap at narrow viewports


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PCF","title":"Layout","content":"- **CSS Grid** for page-level layout (`App.jsx`), **Flexbox** for component internals\n- Sidebar is fixed at `280px`; set `flexShrink: 0` on fixed-width panels and connectors\n- Set `minWidth` on containers to prevent content overlap at narrow viewports","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793791+00:00","updated_at":"2026-04-25T00:47:19.793792+00:00","valid_from":"2026-04-25T00:47:19.793791+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Style consistency

- Define `const styles = {}` at file bottom; pre-compute variants (active/inactive, lit/dim) outside the component to avoid object spread in render loops. See `Header.jsx` `pillStyles` for the reference pattern.
- Spacing scale: multiples of 4px (4, 8, 12, 16, 20, 24, 32).
- Font size scale: 9, 10, 11, 12, 13, 14, 16, 18.
- New colors must be added to both `ui/index.html` `:root` and `ui/src/theme.js`.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PCH","title":"Style consistency","content":"- Define `const styles = {}` at file bottom; pre-compute variants (active/inactive, lit/dim) outside the component to avoid object spread in render loops. See `Header.jsx` `pillStyles` for the reference pattern.\n- Spacing scale: multiples of 4px (4, 8, 12, 16, 20, 24, 32).\n- Font size scale: 9, 10, 11, 12, 13, 14, 16, 18.\n- New colors must be added to both `ui/index.html` `:root` and `ui/src/theme.js`.","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793802+00:00","updated_at":"2026-04-25T00:47:19.793802+00:00","valid_from":"2026-04-25T00:47:19.793802+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Component patterns

- Check for existing components before creating new ones — pill badges in `Header.jsx`, status badges in `StreamCard.jsx`, tables in `ReviewTable.jsx`.
- Prefer extending existing components over parallel implementations.
- Interactive elements need hover and focus states (`cursor: 'pointer'`, `transition`).
- Derive stage-related UI from `PIPELINE_STAGES` in `constants.js`.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PCJ","title":"Component patterns","content":"- Check for existing components before creating new ones — pill badges in `Header.jsx`, status badges in `StreamCard.jsx`, tables in `ReviewTable.jsx`.\n- Prefer extending existing components over parallel implementations.\n- Interactive elements need hover and focus states (`cursor: 'pointer'`, `transition`).\n- Derive stage-related UI from `PIPELINE_STAGES` in `constants.js`.","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793807+00:00","updated_at":"2026-04-25T00:47:19.793807+00:00","valid_from":"2026-04-25T00:47:19.793807+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Worktrees and Branch Protection

HydraFlow creates isolated git worktrees for each issue. **Always clean up worktrees when their PRs are merged or issues are closed. Always implement issue work on a dedicated git worktree branch; do not implement directly in the primary repo checkout.**

> **CRITICAL:** The `main` branch is protected. Direct commits and pushes to `main` will be rejected. All code changes — including one-line fixes — MUST go through a worktree branch and a pull request. Never stage, commit, or modify files in the primary repo checkout. No exceptions.

Design rationale: [`docs/adr/0003-git-worktrees-for-isolation.md`](../adr/0003-git-worktrees-for-isolation.md) and [`docs/adr/0010-worktree-and-path-isolation.md`](../adr/0010-worktree-and-path-isolation.md).


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PCK","title":"Worktrees and Branch Protection","content":"HydraFlow creates isolated git worktrees for each issue. **Always clean up worktrees when their PRs are merged or issues are closed. Always implement issue work on a dedicated git worktree branch; do not implement directly in the primary repo checkout.**\n\n> **CRITICAL:** The `main` branch is protected. Direct commits and pushes to `main` will be rejected. All code changes — including one-line fixes — MUST go through a worktree branch and a pull request. Never stage, commit, or modify files in the primary repo checkout. No exceptions.\n\nDesign rationale: [`docs/adr/0003-git-worktrees-for-isolation.md`](../adr/0003-git-worktrees-for-isolation.md) and [`docs/adr/0010-worktree-and-path-isolation.md`](../adr/0010-worktree-and-path-isolation.md).","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793862+00:00","updated_at":"2026-04-25T00:47:19.793863+00:00","valid_from":"2026-04-25T00:47:19.793862+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## ADR Reference

- [ADR-0022](../adr/0022-integration-test-architecture-cross-phase.md) — PipelineHarness pattern (foundation MockWorld builds on)


```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ2496","title":"ADR Reference","content":"- [ADR-0022](../adr/0022-integration-test-architecture-cross-phase.md) — PipelineHarness pattern (foundation MockWorld builds on)","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794057+00:00","updated_at":"2026-04-25T00:47:19.794058+00:00","valid_from":"2026-04-25T00:47:19.794057+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## EC2 Deployment Guide

This guide shows how to run HydraFlow as a long-lived service on Ubuntu-based EC2 hosts. It ships three building blocks:

- `deploy/ec2/deploy-hydraflow.sh` — bootstrap, update, and run helper
- `deploy/ec2/hydraflow.service` — systemd unit template
- `GET /healthz` — FastAPI health-check endpoint suitable for load balancers or uptime monitors
- `/etc/hydraflow.env` — optional runtime environment file automatically sourced before HydraFlow starts (override with `RUNTIME_ENV_FILE`)

Follow the steps below to install everything under `/opt/hydraflow`, expose the dashboard, and keep the instance healthy.


```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249B","title":"EC2 Deployment Guide","content":"This guide shows how to run HydraFlow as a long-lived service on Ubuntu-based EC2 hosts. It ships three building blocks:\n\n- `deploy/ec2/deploy-hydraflow.sh` — bootstrap, update, and run helper\n- `deploy/ec2/hydraflow.service` — systemd unit template\n- `GET /healthz` — FastAPI health-check endpoint suitable for load balancers or uptime monitors\n- `/etc/hydraflow.env` — optional runtime environment file automatically sourced before HydraFlow starts (override with `RUNTIME_ENV_FILE`)\n\nFollow the steps below to install everything under `/opt/hydraflow`, expose the dashboard, and keep the instance healthy.","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794182+00:00","updated_at":"2026-04-25T00:47:19.794183+00:00","valid_from":"2026-04-25T00:47:19.794182+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## 1. Prerequisites

```bash
sudo apt-get update
sudo apt-get install -y git make python3.11 python3.11-venv build-essential curl
curl -LsSf https://astral.sh/uv/install.sh | sh                    # installs uv into ~/.local/bin
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -  # Node 22 (for dashboard assets)
sudo apt-get install -y nodejs
```

Create a dedicated user and directories for persistent state and logs:

```bash
sudo useradd --system --create-home --shell /bin/bash hydraflow || true
sudo mkdir -p /opt/hydraflow /var/lib/hydraflow /var/log/hydraflow
sudo chown -R hydraflow:hydraflow /opt/hydraflow /var/lib/hydraflow /var/log/hydraflow
```

Clone the repository as that user:

```bash
sudo -u hydraflow git clone https://github.com/hydraflow-ai/hydraflow.git /opt/hydraflow
```

### Quick readiness check (doctor)

Before bootstrapping, run the built-in doctor to confirm the host has everything it needs:

```bash
cd /opt/hydraflow
sudo -u hydraflow deploy/ec2/deploy-hydraflow.sh doctor
```

The doctor exits non-zero when required commands (`git`, `make`, `uv`) are missing, when `/opt/hydraflow` is not a git checkout, or when `.env` has not been created yet. It also warns if `/var/lib/hydraflow`, `/var/log/hydraflow`, or the rendered `hydraflow.service` are absent so you can fix the filesystem layout before touching systemd.


```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249C","title":"1. Prerequisites","content":"```bash\nsudo apt-get update\nsudo apt-get install -y git make python3.11 python3.11-venv build-essential curl\ncurl -LsSf https://astral.sh/uv/install.sh | sh                    # installs uv into ~/.local/bin\ncurl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -  # Node 22 (for dashboard assets)\nsudo apt-get install -y nodejs\n```\n\nCreate a dedicated user and directories for persistent state and logs:\n\n```bash\nsudo useradd --system --create-home --shell /bin/bash hydraflow || true\nsudo mkdir -p /opt/hydraflow /var/lib/hydraflow /var/log/hydraflow\nsudo chown -R hydraflow:hydraflow /opt/hydraflow /var/lib/hydraflow /var/log/hydraflow\n```\n\nClone the repository as that user:\n\n```bash\nsudo -u hydraflow git clone https://github.com/hydraflow-ai/hydraflow.git /opt/hydraflow\n```\n\n### Quick readiness check (doctor)\n\nBefore bootstrapping, run the built-in doctor to confirm the host has everything it needs:\n\n```bash\ncd /opt/hydraflow\nsudo -u hydraflow deploy/ec2/deploy-hydraflow.sh doctor\n```\n\nThe doctor exits non-zero when required commands (`git`, `make`, `uv`) are missing, when `/opt/hydraflow` is not a git checkout, or when `.env` has not been created yet. It also warns if `/var/lib/hydraflow`, `/var/log/hydraflow`, or the rendered `hydraflow.service` are absent so you can fix the filesystem layout before touching systemd.","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794188+00:00","updated_at":"2026-04-25T00:47:19.794189+00:00","valid_from":"2026-04-25T00:47:19.794188+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## 2. Bootstrap the runtime

Run the helper script once to install Python deps, build the dashboard, and seed `.env`:

```bash
cd /opt/hydraflow
sudo -u hydraflow deploy/ec2/deploy-hydraflow.sh bootstrap
```

The script will:

1. Verify `git`, `uv`, and `make` are available.
2. Copy `.env.sample` to `.env` if one is missing.
3. Sync the git branch (`GIT_BRANCH`/`GIT_REMOTE` can be overridden) and update submodules.
4. Create `/var/lib/hydraflow`, `.hydraflow/logs`, and `/var/log/hydraflow` when writable.
5. Run `uv sync --all-extras` and `make ui` so FastAPI can serve the compiled React dashboard.

Re-run the script with `deploy` any time you need to pull new commits and restart the service:

```bash
sudo -u hydraflow deploy/ec2/deploy-hydraflow.sh deploy
```

To launch HydraFlow manually (for smoke tests), call:

```bash
sudo -u hydraflow deploy/ec2/deploy-hydraflow.sh run --dashboard-port 5555
```


```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249D","title":"2. Bootstrap the runtime","content":"Run the helper script once to install Python deps, build the dashboard, and seed `.env`:\n\n```bash\ncd /opt/hydraflow\nsudo -u hydraflow deploy/ec2/deploy-hydraflow.sh bootstrap\n```\n\nThe script will:\n\n1. Verify `git`, `uv`, and `make` are available.\n2. Copy `.env.sample` to `.env` if one is missing.\n3. Sync the git branch (`GIT_BRANCH`/`GIT_REMOTE` can be overridden) and update submodules.\n4. Create `/var/lib/hydraflow`, `.hydraflow/logs`, and `/var/log/hydraflow` when writable.\n5. Run `uv sync --all-extras` and `make ui` so FastAPI can serve the compiled React dashboard.\n\nRe-run the script with `deploy` any time you need to pull new commits and restart the service:\n\n```bash\nsudo -u hydraflow deploy/ec2/deploy-hydraflow.sh deploy\n```\n\nTo launch HydraFlow manually (for smoke tests), call:\n\n```bash\nsudo -u hydraflow deploy/ec2/deploy-hydraflow.sh run --dashboard-port 5555\n```","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794193+00:00","updated_at":"2026-04-25T00:47:19.794194+00:00","valid_from":"2026-04-25T00:47:19.794193+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## 4. Install the systemd unit

Let the helper script handle copying and enabling the unit:

```bash
cd /opt/hydraflow
sudo deploy/ec2/deploy-hydraflow.sh install
```

By default the unit is written to `/etc/systemd/system/hydraflow.service`; override this or the service name via `SYSTEMD_DIR=/custom/path deploy/ec2/deploy-hydraflow.sh install` and/or `SERVICE_NAME=my-hydraflow`.

The installer renders the template with a handful of environment overrides so you rarely have to edit the unit by hand:

- `SERVICE_USER` / `SERVICE_GROUP` — user/group that owns the process (default: `hydraflow`)
- `SERVICE_WORK_DIR` — checkout path HydraFlow runs from (default: `HYDRAFLOW_ROOT`)
- `SERVICE_LOG_FILE` — file used for both stdout/stderr (default: `${HYDRAFLOW_LOG_DIR:-/var/log/hydraflow}/orchestrator.log`)
- `SERVICE_RUNTIME_DIR` — name for the systemd runtime dir (`RuntimeDirectory=`; default: `hydraflow`)
- `RUNTIME_ENV_FILE` — EnvironmentFile path sourced before the service starts (default: `/etc/hydraflow.env`)
- `SERVICE_EXEC_START` — command systemd executes (default: `<repo>/deploy/ec2/deploy-hydraflow.sh run`)

Example for a non-root install under `/srv/hf`:

```bash
sudo SYSTEMD_DIR=/etc/systemd/system \
     SERVICE_USER=ubuntu \
     SERVICE_GROUP=ubuntu \
     SERVICE_WORK_DIR=/srv/hf \
     SERVICE_LOG_FILE=/srv/hf/logs/orchestrator.log \
     deploy/ec2/deploy-hydraflow.sh install
```

The unit calls the deploy script’s `run` verb, so it inherits all of the script’s environment handling. Runtime environment is loaded from `/etc/hydraflow.env` (see Step 3). Logs are written to `/var/log/hydraflow/orchestrator.log`; watch them with:

```bash
sudo journalctl -u hydraflow -f
```


```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249F","title":"4. Install the systemd unit","content":"Let the helper script handle copying and enabling the unit:\n\n```bash\ncd /opt/hydraflow\nsudo deploy/ec2/deploy-hydraflow.sh install\n```\n\nBy default the unit is written to `/etc/systemd/system/hydraflow.service`; override this or the service name via `SYSTEMD_DIR=/custom/path deploy/ec2/deploy-hydraflow.sh install` and/or `SERVICE_NAME=my-hydraflow`.\n\nThe installer renders the template with a handful of environment overrides so you rarely have to edit the unit by hand:\n\n- `SERVICE_USER` / `SERVICE_GROUP` — user/group that owns the process (default: `hydraflow`)\n- `SERVICE_WORK_DIR` — checkout path HydraFlow runs from (default: `HYDRAFLOW_ROOT`)\n- `SERVICE_LOG_FILE` — file used for both stdout/stderr (default: `${HYDRAFLOW_LOG_DIR:-/var/log/hydraflow}/orchestrator.log`)\n- `SERVICE_RUNTIME_DIR` — name for the systemd runtime dir (`RuntimeDirectory=`; default: `hydraflow`)\n- `RUNTIME_ENV_FILE` — EnvironmentFile path sourced before the service starts (default: `/etc/hydraflow.env`)\n- `SERVICE_EXEC_START` — command systemd executes (default: `<repo>/deploy/ec2/deploy-hydraflow.sh run`)\n\nExample for a non-root install under `/srv/hf`:\n\n```bash\nsudo SYSTEMD_DIR=/etc/systemd/system \\\n     SERVICE_USER=ubuntu \\\n     SERVICE_GROUP=ubuntu \\\n     SERVICE_WORK_DIR=/srv/hf \\\n     SERVICE_LOG_FILE=/srv/hf/logs/orchestrator.log \\\n     deploy/ec2/deploy-hydraflow.sh install\n```\n\nThe unit calls the deploy script’s `run` verb, so it inherits all of the script’s environment handling. Runtime environment is loaded from `/etc/hydraflow.env` (see Step 3). Logs are written to `/var/log/hydraflow/orchestrator.log`; watch them with:\n\n```bash\nsudo journalctl -u hydraflow -f\n```","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794204+00:00","updated_at":"2026-04-25T00:47:19.794205+00:00","valid_from":"2026-04-25T00:47:19.794204+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## 6. Updates

Each deploy only requires one command:

```bash
sudo systemctl stop hydraflow
sudo -u hydraflow deploy/ec2/deploy-hydraflow.sh deploy
sudo systemctl start hydraflow
```

Or let the script restart the service automatically (it calls `systemctl restart` when run as root and the unit is installed):

```bash
HEALTHCHECK_WAIT_FOR_READY=1 sudo deploy/ec2/deploy-hydraflow.sh deploy
```

The script honours `GIT_BRANCH`, `GIT_REMOTE`, `UV_BIN`, and `HYDRAFLOW_HOME_DIR` env vars, so you can pin to a release branch or custom fork by exporting those variables before running it.


```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249H","title":"6. Updates","content":"Each deploy only requires one command:\n\n```bash\nsudo systemctl stop hydraflow\nsudo -u hydraflow deploy/ec2/deploy-hydraflow.sh deploy\nsudo systemctl start hydraflow\n```\n\nOr let the script restart the service automatically (it calls `systemctl restart` when run as root and the unit is installed):\n\n```bash\nHEALTHCHECK_WAIT_FOR_READY=1 sudo deploy/ec2/deploy-hydraflow.sh deploy\n```\n\nThe script honours `GIT_BRANCH`, `GIT_REMOTE`, `UV_BIN`, and `HYDRAFLOW_HOME_DIR` env vars, so you can pin to a release branch or custom fork by exporting those variables before running it.","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794215+00:00","updated_at":"2026-04-25T00:47:19.794216+00:00","valid_from":"2026-04-25T00:47:19.794215+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## 7. Troubleshooting checklist

- `deploy/ec2/deploy-hydraflow.sh status` — shows the live systemd state.
- `journalctl -u hydraflow -b` — inspect the last boot’s logs.
- `curl http://127.0.0.1:5555/healthz` — verify FastAPI is responsive even if the ALB is failing.
- Ensure `/var/log/hydraflow` and `/var/lib/hydraflow` are writable by the `hydraflow` user.
- Open TCP port 5555 (or your configured port) in the EC2 security group to whichever CIDR blocks need dashboard access.

With these assets in place you can treat HydraFlow as any other continuously-running service: deploy updates with one command, monitor `/healthz`, and expose the dashboard safely.


```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249J","title":"7. Troubleshooting checklist","content":"- `deploy/ec2/deploy-hydraflow.sh status` — shows the live systemd state.\n- `journalctl -u hydraflow -b` — inspect the last boot’s logs.\n- `curl http://127.0.0.1:5555/healthz` — verify FastAPI is responsive even if the ALB is failing.\n- Ensure `/var/log/hydraflow` and `/var/lib/hydraflow` are writable by the `hydraflow` user.\n- Open TCP port 5555 (or your configured port) in the EC2 security group to whichever CIDR blocks need dashboard access.\n\nWith these assets in place you can treat HydraFlow as any other continuously-running service: deploy updates with one command, monitor `/healthz`, and expose the dashboard safely.","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794220+00:00","updated_at":"2026-04-25T00:47:19.794221+00:00","valid_from":"2026-04-25T00:47:19.794220+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
