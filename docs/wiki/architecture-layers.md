# Architecture-Layers


## Four-Layer Architecture with Downward-Only Imports

HydraFlow's architecture: L1 (Utilities: subprocess_util, file_util, state) → L2 (Application: phases, runners, background loops) → L3 (Agents: specialized LLM runners) → L4 (Infrastructure: HTTP routes, FastAPI, CLI). Only downward imports permitted (L2 can import L1; L3 can import L1–L2; etc.). Never import upward.
**Why:** Enforces separation of concerns and prevents circular dependencies.


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488E","title":"Four-Layer Architecture with Downward-Only Imports","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:44:20.100478+00:00","updated_at":"2026-05-03T03:44:20.100492+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use @runtime_checkable Protocols for Structural Typing

Use @runtime_checkable Protocol abstractions (AgentPort, PRPort, IssueStorePort, OrchestratorPort) to decouple layers via structural typing. Concrete implementations automatically satisfy protocols via duck typing; no explicit inheritance required. Define port interfaces at layer boundaries (type hints only via TYPE_CHECKING), instantiate concrete classes at service registry.
**Why:** Enables type safety without runtime layer violations.


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488F","title":"Use @runtime_checkable Protocols for Structural Typing","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:44:20.100522+00:00","updated_at":"2026-05-03T03:44:20.100526+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Service Registry as Single Composition Root

service_registry.py is the single architecturally-exempt composition root. Instantiate dependencies in correct order; annotate fields with port types for abstraction but instantiate with concrete classes; thread shared dependencies through all consumers. No other module violates layer boundaries.
**Why:** Centralizes dependency management and prevents scattered layer violations.


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488G","title":"Service Registry as Single Composition Root","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:44:20.100538+00:00","updated_at":"2026-05-03T03:44:20.100539+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Background Loop 5-Point Wiring Synchronization

Background loops require 5-point synchronization: (1) config fields in HydraFlowConfig, (2) service_registry imports, (3) instantiation in service registry, (4) orchestrator bg_loop_registry dict entry, (5) dashboard constants. Update all five in lockstep when adding/removing a loop.
**Why:** Prevents partially-wired loops that cause silent failures or incomplete dashboard visibility.


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488H","title":"Background Loop 5-Point Wiring Synchronization","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:44:20.100547+00:00","updated_at":"2026-05-03T03:44:20.100549+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use Pattern-Based Inference to Assign Layer Membership

Modules auto-assign to layers via naming patterns: *_loop.py → L2, *_runner.py → L3, *_scaffold.py → L4, *_util.py or *_constants.py → L1. Validate assignments in arch_compliance.py MODULE_LAYERS via static checkers (check_layer_imports.py) and LLM compliance skills.
**Why:** Reduces manual layer tracking and surfaces layer violations early via automated validation.


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488J","title":"Use Pattern-Based Inference to Assign Layer Membership","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:44:20.100559+00:00","updated_at":"2026-05-03T03:44:20.100560+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Extract Pure Functions for Independently-Testable Business Logic

Extract pure functions (taking primitives/objects, returning primitives or tuples) for reusable business logic. Example: classify_merge_outcome(verdict_score, comment_count, ...) → (outcome, confidence). Pure functions isolate rules from service coupling, enable unit testing without mocks, and clarify logic intent.
**Why:** Improves testability and reasoning about behavior without service scaffolding.


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488K","title":"Extract Pure Functions for Independently-Testable Business Logic","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:44:20.100570+00:00","updated_at":"2026-05-03T03:44:20.100571+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Prefer Module-Level Utility Functions Over Instance Methods

Use module-level async/sync utilities (e.g., polling_loop(supervisor, ...) → None) rather than instance methods. Keeps containing class small (e.g., extract ~80-line utility to keep supervisor under 200 lines), enables independent testing, avoids tight coupling. Module-level functions accept the object as first argument. Retain thin instance-method wrapper for backward compatibility with existing mocks.
**Why:** Reduces class complexity while improving independent testability and reusability.


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488M","title":"Prefer Module-Level Utility Functions Over Instance Methods","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:44:20.100579+00:00","updated_at":"2026-05-03T03:44:20.100580+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Convert Closures to Standalone Functions by Parameterizing Nonlocal State

When extracting a closure to standalone function, convert each nonlocal variable to either a function parameter (input) or field in returned NamedTuple (output). Eliminates implicit state sharing and makes dependencies explicit—critical for testing and reasoning about behavior.
**Why:** Improves clarity and testability by making hidden dependencies visible in function signatures.


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488N","title":"Convert Closures to Standalone Functions by Parameterizing Nonlocal State","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:44:20.100588+00:00","updated_at":"2026-05-03T03:44:20.100589+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Pass Config Objects as Parameters for Configuration-Dependent Values

When logic depends on configuration, pass config object (or relevant subset) as parameter rather than accessing globally. Enables testing with different configs and avoids tight coupling to module-level configuration.
**Why:** Improves testability and clarity. Makes which config values a function depends on explicit.


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488P","title":"Pass Config Objects as Parameters for Configuration-Dependent Values","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:44:20.100597+00:00","updated_at":"2026-05-03T03:44:20.100598+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use Re-Exports to Preserve Import Paths During Refactoring

When moving implementation to new canonical location, re-export from original module. Existing `from old_module import Class` statements continue working unchanged. Test re-exports with identity checks: `assert Class1 is Class2`.
**Why:** Preserves isinstance() checks and import statements across 40+ existing call sites with zero impact.


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488Q","title":"Use Re-Exports to Preserve Import Paths During Refactoring","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:44:20.100606+00:00","updated_at":"2026-05-03T03:44:20.100607+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Add Optional Parameters with None Defaults for Backward Compatibility

When adding new functionality, define optional kwargs with None defaults. Callers omitting them get fallback behavior matching the old implementation. Avoids breaking existing call sites.
**Why:** Enables feature addition without forcing callers to update.


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488R","title":"Add Optional Parameters with None Defaults for Backward Compatibility","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:44:20.100615+00:00","updated_at":"2026-05-03T03:44:20.100616+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use Facade + Composition for Large Class Decomposition

When splitting large classes (20+ importing modules, 50+ mock targets, 947 lines, 37 methods): keep original class as thin facade with delegation stubs, move implementation to stateless or single-concern sub-modules. Preserves all import paths, isinstance checks, and mock targets—enabling zero-test-breakage refactors.
**Why:** Prevents breaking 40+ existing import sites, isinstance checks, and test mocks while enabling incremental refactoring.


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488S","title":"Use Facade + Composition for Large Class Decomposition","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:44:20.100623+00:00","updated_at":"2026-05-03T03:44:20.100625+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Layer 1 Assignment for Pure Data Constants

Pure string/data constants with no imports can safely be assigned to Layer 1 (runner_constants module). No circular dependency risk when module has no external dependencies.
**Why:** Keeps data-only definitions accessible without introducing layer violations.

_Source: #6295 (review)_


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488T","title":"Layer 1 Assignment for Pure Data Constants","topic":null,"source_type":"review","source_issue":6295,"source_repo":null,"created_at":"2026-05-03T03:44:20.100637+00:00","updated_at":"2026-05-03T03:44:20.100638+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Layer Checker Must Track Newly Added Data Modules

When creating new constant/data modules at a given layer, update the layer import checker (check_layer_imports.py) to recognize them. Prevents false positives and keeps layer validation current.
**Why:** Ensures layer checking remains accurate as codebase grows. Stale checkers become untrustworthy.

_Source: #6295 (review)_


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488V","title":"Layer Checker Must Track Newly Added Data Modules","topic":null,"source_type":"review","source_issue":6295,"source_repo":null,"created_at":"2026-05-03T03:44:20.100646+00:00","updated_at":"2026-05-03T03:44:20.100647+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Facade Exception: Public Method Limits for Behavioral Classes

The ≤7 public method / ≤200 line constraints apply to extracted behavioral classes (ActiveIssueTracker, IssueSnapshotBuilder, IssueQueueRouter), not the facade. Facade retains ~25 delegation stubs for backward compatibility—each stub is 1–2 lines. This is a documented exception.
**Why:** Distinguishes implementation quality constraints from backward-compatibility requirements.

_Source: #6327 (plan)_


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488W","title":"Facade Exception: Public Method Limits for Behavioral Classes","topic":null,"source_type":"plan","source_issue":6327,"source_repo":null,"created_at":"2026-05-03T03:44:20.100656+00:00","updated_at":"2026-05-03T03:44:20.100659+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Distinguish Public Facades from Implementation in Acceptance Criteria

When refactoring with facade pattern, acceptance criteria like 'no class exceeds N public methods' should apply to *implementation classes*, not the facade. Clarify this distinction upfront to avoid criteria conflicts with delegation requirements.
**Why:** Prevents rejection of correct facade patterns due to conflicting acceptance criteria.

_Source: #6338 (plan)_


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488X","title":"Distinguish Public Facades from Implementation in Acceptance Criteria","topic":null,"source_type":"plan","source_issue":6338,"source_repo":null,"created_at":"2026-05-03T03:44:20.100667+00:00","updated_at":"2026-05-03T03:44:20.100668+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Template Method Exception to 50-Line Logic Limit

Methods containing static prompt templates or configuration strings can exceed 50 lines of text while maintaining good design if logic content is minimal (<5 lines). _assemble_plan_prompt ~110 lines of f-string + variables is acceptable. Splitting such templates reduces prompt readability.
**Why:** Balances brevity rule with readability of self-documenting prompt templates.

_Source: #6332 (plan)_


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488Y","title":"Template Method Exception to 50-Line Logic Limit","topic":null,"source_type":"plan","source_issue":6332,"source_repo":null,"created_at":"2026-05-03T03:44:20.100675+00:00","updated_at":"2026-05-03T03:44:20.100677+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Coordinator + Focused Helpers Decomposition Pattern

Decompose oversized methods by creating lean coordinator (30–50 lines) delegating to focused single-concern helpers (12–45 lines each). Apply when method mixes concerns: prompt assembly, retry coordination, validation. Each helper encapsulates one concern; coordinator orchestrates without duplicating logic.
**Why:** Manages complexity without creating new abstractions. Each unit is small and independently testable.

_Source: #6332 (plan)_


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF488Z","title":"Coordinator + Focused Helpers Decomposition Pattern","topic":null,"source_type":"plan","source_issue":6332,"source_repo":null,"created_at":"2026-05-03T03:44:20.100684+00:00","updated_at":"2026-05-03T03:44:20.100686+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Orchestrator Pattern: Deferred Module Registration via Factory

Factory function becomes thin orchestrator (~80 lines) creating shared context, delegating route registration to ~12 sub-modules via consistent `register(router, ctx)` signature. Each sub-module owns 50–200 lines; factory merely composes them.
**Why:** Decouples endpoint logic from factory complexity. Enables parallel sub-module implementation.

_Source: #6336 (plan)_


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF4890","title":"Orchestrator Pattern: Deferred Module Registration via Factory","topic":null,"source_type":"plan","source_issue":6336,"source_repo":null,"created_at":"2026-05-03T03:44:20.100693+00:00","updated_at":"2026-05-03T03:44:20.100696+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Avoid Thin-Wrapper Abstractions—Target Concrete Duplication

Reject `_build_base_prompt_context()` wrapper returning a tuple if it merely consolidates perceived similarity without eliminating real duplication. Target specific repeated code: only extract when 4+ runners share the same lines, not when they're just similar.
**Why:** Thin wrappers create coupling without real benefit. Extract only where duplication is genuine.

_Source: #6340 (plan)_


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF4891","title":"Avoid Thin-Wrapper Abstractions—Target Concrete Duplication","topic":null,"source_type":"plan","source_issue":6340,"source_repo":null,"created_at":"2026-05-03T03:44:20.100704+00:00","updated_at":"2026-05-03T03:44:20.100705+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use Sibling File Patterns as Architectural Reference

When implementing a change, reference similar patterns in sibling files (e.g., _control_routes.py) to ensure consistency. Provides evidence the pattern is established and approved in the codebase, reducing design ambiguity.
**Why:** Prevents design divergence and provides peer-reviewed precedent for the pattern.

_Source: #6333 (plan)_


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF4892","title":"Use Sibling File Patterns as Architectural Reference","topic":null,"source_type":"plan","source_issue":6333,"source_repo":null,"created_at":"2026-05-03T03:44:20.100712+00:00","updated_at":"2026-05-03T03:44:20.100714+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Module-Level State via Constructor Injection

When extracted classes need access to module-level state (e.g., _FETCH_LOCKS dict), pass it via constructor injection (e.g., fetch_lock_fn: Callable[[], asyncio.Lock]) rather than direct imports. Avoids circular dependencies while preserving test patchability.
**Why:** Prevents circular imports while maintaining testability. Explicit dependencies clarify state sharing.

_Source: #6338 (plan)_


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF4893","title":"Module-Level State via Constructor Injection","topic":null,"source_type":"plan","source_issue":6338,"source_repo":null,"created_at":"2026-05-03T03:44:20.100721+00:00","updated_at":"2026-05-03T03:44:20.100722+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve Organizational Comments During Dead Code Removal

Section heading comments (e.g., '# --- reset ---', '# --- threshold tracking ---') and blank-line separators maintain code structure and readability. Preserve these markers even when adjacent dead methods are removed.
**Why:** Signals logical grouping to future readers. Structural markers survive refactoring.

_Source: #6345 (plan)_


```json:entry
{"id":"01KQNYZRM4B7DX9MWDQFHF4894","title":"Preserve Organizational Comments During Dead Code Removal","topic":null,"source_type":"plan","source_issue":6345,"source_repo":null,"created_at":"2026-05-03T03:44:20.100730+00:00","updated_at":"2026-05-03T03:44:20.100731+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
