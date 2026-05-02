# Architecture Layers

## Layer Architecture: Four-Layer Model with Structural Typing



HydraFlow uses a 4-layer architecture with strict downward-only import direction: L1 (Utilities: subprocess_util, file_util, state) → L2 (Application: phases, runners, background loops) → L3 (Agents: specialized LLM runners) → L4 (Infrastructure: HTTP routes, FastAPI, CLI). TYPE_CHECKING imports and protocol abstractions enable type safety without runtime layer violations. Use @runtime_checkable Protocol abstractions (AgentPort, PRPort, IssueStorePort, OrchestratorPort) to decouple layers via structural typing—concrete implementations automatically satisfy protocols via duck typing. Service registry (service_registry.py) is the single architecturally-exempt composition root: instantiate dependencies in correct order, annotate fields with port types for abstraction but instantiate with concrete classes, thread shared dependencies through all consumers. Background loops require 5-point wiring synchronization: config fields, service_registry imports, instantiation, orchestrator bg_loop_registry dict, and dashboard constants. Layer assignments tracked in arch_compliance.py MODULE_LAYERS and validated via static checkers (check_layer_imports.py) and LLM-based compliance skills. Pattern-based inference: *_loop.py→L2, *_runner.py→L3, *_scaffold.py→L4. Bidirectional cross-cutting modules (state, events, ports) can be imported by any layer but must only import from L1. See also: Architecture Compliance for validation, Orchestrator/Sequencer Design for L2 patterns.

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VR","title":"Layer Architecture: Four-Layer Model with Structural Typing","content":"HydraFlow uses a 4-layer architecture with strict downward-only import direction: L1 (Utilities: subprocess_util, file_util, state) → L2 (Application: phases, runners, background loops) → L3 (Agents: specialized LLM runners) → L4 (Infrastructure: HTTP routes, FastAPI, CLI). TYPE_CHECKING imports and protocol abstractions enable type safety without runtime layer violations. Use @runtime_checkable Protocol abstractions (AgentPort, PRPort, IssueStorePort, OrchestratorPort) to decouple layers via structural typing—concrete implementations automatically satisfy protocols via duck typing. Service registry (service_registry.py) is the single architecturally-exempt composition root: instantiate dependencies in correct order, annotate fields with port types for abstraction but instantiate with concrete classes, thread shared dependencies through all consumers. Background loops require 5-point wiring synchronization: config fields, service_registry imports, instantiation, orchestrator bg_loop_registry dict, and dashboard constants. Layer assignments tracked in arch_compliance.py MODULE_LAYERS and validated via static checkers (check_layer_imports.py) and LLM-based compliance skills. Pattern-based inference: *_loop.py→L2, *_runner.py→L3, *_scaffold.py→L4. Bidirectional cross-cutting modules (state, events, ports) can be imported by any layer but must only import from L1. See also: Architecture Compliance for validation, Orchestrator/Sequencer Design for L2 patterns.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849524+00:00","updated_at":"2026-04-10T03:41:18.849525+00:00","valid_from":"2026-04-10T03:41:18.849524+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Functional Design: Pure Functions and Module-Level Utilities



Extract pure functions (taking primitives, returning primitives or tuples) for reusable business logic that should be independently testable. Pattern: classify_merge_outcome(verdict_score, comment_count, ...) → (outcome, confidence). Pure functions isolate rules from service coupling, enable unit testing without mocks, and clarify logic intent. Pass config objects as parameters to access configuration-dependent values. When scoring classification logic is split across modules, consolidate by creating a pure function in the domain module with named threshold constants. Simple tuple returns (3 elements) are preferable to new dataclasses. Prefer module-level utility functions (e.g., retain_safe(client, bank, content, metadata=...)) over instance methods. This pattern is more testable, avoids tight coupling, and provides cleaner APIs. Module-level functions accept the object as first argument. When converting a closure to a standalone function, convert each `nonlocal` variable to either a function parameter (input) or a field in a returned NamedTuple (output). This eliminates implicit state sharing and makes the function's dependencies explicit—critical for testing and reasoning about behavior.

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VV","title":"Functional Design: Pure Functions and Module-Level Utilities","content":"Extract pure functions (taking primitives, returning primitives or tuples) for reusable business logic that should be independently testable. Pattern: classify_merge_outcome(verdict_score, comment_count, ...) → (outcome, confidence). Pure functions isolate rules from service coupling, enable unit testing without mocks, and clarify logic intent. Pass config objects as parameters to access configuration-dependent values. When scoring classification logic is split across modules, consolidate by creating a pure function in the domain module with named threshold constants. Simple tuple returns (3 elements) are preferable to new dataclasses. Prefer module-level utility functions (e.g., retain_safe(client, bank, content, metadata=...)) over instance methods. This pattern is more testable, avoids tight coupling, and provides cleaner APIs. Module-level functions accept the object as first argument. When converting a closure to a standalone function, convert each `nonlocal` variable to either a function parameter (input) or a field in a returned NamedTuple (output). This eliminates implicit state sharing and makes the function's dependencies explicit—critical for testing and reasoning about behavior.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849538+00:00","updated_at":"2026-04-10T03:41:18.849540+00:00","valid_from":"2026-04-10T03:41:18.849538+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Layer 1 assignment for pure data constants



Pure string/data constants with no imports can safely be assigned to Layer 1 (runner_constants module). This avoids circular dependencies while keeping data-only definitions accessible. Layer assignment is architecturally sound when the module has no external dependencies.

_Source: #6295 (review)_

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WJ","title":"Layer 1 assignment for pure data constants","content":"Pure string/data constants with no imports can safely be assigned to Layer 1 (runner_constants module). This avoids circular dependencies while keeping data-only definitions accessible. Layer assignment is architecturally sound when the module has no external dependencies.","topic":null,"source_type":"review","source_issue":6295,"source_repo":null,"created_at":"2026-04-10T03:47:50.097407+00:00","updated_at":"2026-04-10T03:47:50.097411+00:00","valid_from":"2026-04-10T03:47:50.097407+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Layer checker must track newly added data modules



When creating new constant/data modules at a given layer, update the layer import checker to recognize them. This prevents false positives and ensures the layer checker stays current as the codebase grows.

_Source: #6295 (review)_

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WN","title":"Layer checker must track newly added data modules","content":"When creating new constant/data modules at a given layer, update the layer import checker to recognize them. This prevents false positives and ensures the layer checker stays current as the codebase grows.","topic":null,"source_type":"review","source_issue":6295,"source_repo":null,"created_at":"2026-04-10T03:47:50.097432+00:00","updated_at":"2026-04-10T03:47:50.097438+00:00","valid_from":"2026-04-10T03:47:50.097432+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Backward Compatibility and Refactoring via Facades and Re-Exports



When splitting large classes or moving code, preserve backward compatibility using three strategies: (1) **Re-exports**: move implementation to canonical location, re-export from original module, ensuring `isinstance()` checks and existing imports work unchanged. Test re-exports with identity checks (`assert Class1 is Class2`). (2) **Optional parameters with None defaults**: add new functionality as optional kwargs, allowing callers to omit them with fallback behavior matching the old implementation. (3) **Facade + composition for large classes**: when splitting classes with 20+ importing modules and 50+ test mock targets, keep delegation stubs on original class so all existing import paths, isinstance checks, and mock targets continue working. Extract to sub-clients inheriting a shared base class. Fix encapsulation violations by defining proper public API methods on the base class. These patterns enable incremental migration and prevent breaking 40+ existing import sites across the codebase. See also: Consolidation Patterns for handling multiple refactoring scenarios.

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VT","title":"Backward Compatibility and Refactoring via Facades and Re-Exports","content":"When splitting large classes or moving code, preserve backward compatibility using three strategies: (1) **Re-exports**: move implementation to canonical location, re-export from original module, ensuring `isinstance()` checks and existing imports work unchanged. Test re-exports with identity checks (`assert Class1 is Class2`). (2) **Optional parameters with None defaults**: add new functionality as optional kwargs, allowing callers to omit them with fallback behavior matching the old implementation. (3) **Facade + composition for large classes**: when splitting classes with 20+ importing modules and 50+ test mock targets, keep delegation stubs on original class so all existing import paths, isinstance checks, and mock targets continue working. Extract to sub-clients inheriting a shared base class. Fix encapsulation violations by defining proper public API methods on the base class. These patterns enable incremental migration and prevent breaking 40+ existing import sites across the codebase. See also: Consolidation Patterns for handling multiple refactoring scenarios.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849534+00:00","updated_at":"2026-04-10T03:41:18.849536+00:00","valid_from":"2026-04-10T03:41:18.849534+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Facade Exception: Public Method Limits for Behavioral Classes



The ≤7 public method / ≤200 line constraints apply to extracted behavioral classes (ActiveIssueTracker, IssueSnapshotBuilder, IssueQueueRouter). The facade necessarily retains 25 delegation stubs for backward compatibility per the documented pattern — this is not a violation of the rule, but a documented exception to preserve import paths and external consumers.

_Source: #6327 (plan)_

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X8","title":"Facade Exception: Public Method Limits for Behavioral Classes","content":"The ≤7 public method / ≤200 line constraints apply to extracted behavioral classes (ActiveIssueTracker, IssueSnapshotBuilder, IssueQueueRouter). The facade necessarily retains 25 delegation stubs for backward compatibility per the documented pattern — this is not a violation of the rule, but a documented exception to preserve import paths and external consumers.","topic":null,"source_type":"plan","source_issue":6327,"source_repo":null,"created_at":"2026-04-10T05:07:55.384601+00:00","updated_at":"2026-04-10T05:07:55.384602+00:00","valid_from":"2026-04-10T05:07:55.384601+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
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

## Move generic utilities to module-level functions to keep classes small



Rather than making `polling_loop` an instance method of LoopSupervisor, extract it as a module-level async function (~80 lines). This keeps the supervisor class under 200 lines while keeping polling logic independently testable. Orchestrator retains `_polling_loop()` as a thin wrapper for backward compatibility with existing mocks. This pattern aligns with codebase wiki guidance: 'Prefer module-level utility functions over instance methods.'

_Source: #6323 (plan)_

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WY","title":"Move generic utilities to module-level functions to keep classes small","content":"Rather than making `polling_loop` an instance method of LoopSupervisor, extract it as a module-level async function (~80 lines). This keeps the supervisor class under 200 lines while keeping polling logic independently testable. Orchestrator retains `_polling_loop()` as a thin wrapper for backward compatibility with existing mocks. This pattern aligns with codebase wiki guidance: 'Prefer module-level utility functions over instance methods.'","topic":null,"source_type":"plan","source_issue":6323,"source_repo":null,"created_at":"2026-04-10T04:47:03.630680+00:00","updated_at":"2026-04-10T04:47:03.630683+00:00","valid_from":"2026-04-10T04:47:03.630680+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Use sibling file patterns as architectural reference for consistency



When implementing a change, reference similar patterns in sibling files (e.g., _control_routes.py) to ensure consistency. This provides evidence that the pattern is established and approved in the codebase, reducing design ambiguity and potential review friction.

_Source: #6333 (plan)_

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XD","title":"Use sibling file patterns as architectural reference for consistency","content":"When implementing a change, reference similar patterns in sibling files (e.g., _control_routes.py) to ensure consistency. This provides evidence that the pattern is established and approved in the codebase, reducing design ambiguity and potential review friction.","topic":null,"source_type":"plan","source_issue":6333,"source_repo":null,"created_at":"2026-04-10T05:32:01.385950+00:00","updated_at":"2026-04-10T05:32:01.385951+00:00","valid_from":"2026-04-10T05:32:01.385950+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Module-Level State via Constructor Injection



When extracted classes need access to module-level state (e.g., `_FETCH_LOCKS` dict for regression test patching), pass it via constructor injection (e.g., `fetch_lock_fn: Callable[[], asyncio.Lock]`) rather than direct imports. This avoids circular dependencies between the facade and extracted modules while preserving the ability to patch module-level state in tests.

_Source: #6338 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNX","title":"Module-Level State via Constructor Injection","content":"When extracted classes need access to module-level state (e.g., `_FETCH_LOCKS` dict for regression test patching), pass it via constructor injection (e.g., `fetch_lock_fn: Callable[[], asyncio.Lock]`) rather than direct imports. This avoids circular dependencies between the facade and extracted modules while preserving the ability to patch module-level state in tests.","topic":null,"source_type":"plan","source_issue":6338,"source_repo":null,"created_at":"2026-04-10T05:56:11.037248+00:00","updated_at":"2026-04-10T05:56:11.037249+00:00","valid_from":"2026-04-10T05:56:11.037248+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Preserve organizational comments during dead code removal



Section heading comments (e.g., '# --- reset ---', '# --- threshold tracking ---') and blank-line separators maintain code structure and readability. Preserve these markers even when adjacent dead methods are removed. They signal logical grouping to future readers and should survive refactoring.

_Source: #6345 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPB","title":"Preserve organizational comments during dead code removal","content":"Section heading comments (e.g., '# --- reset ---', '# --- threshold tracking ---') and blank-line separators maintain code structure and readability. Preserve these markers even when adjacent dead methods are removed. They signal logical grouping to future readers and should survive refactoring.","topic":null,"source_type":"plan","source_issue":6345,"source_repo":null,"created_at":"2026-04-10T06:35:05.468491+00:00","updated_at":"2026-04-10T06:35:05.468493+00:00","valid_from":"2026-04-10T06:35:05.468491+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
