# Wiki Index: T-rav/hydraflow

**293 entries** | Last updated: 2026-05-03T04:19:35.650996+00:00


## Architecture (33)

- ADR Structure and Validation Checklist
- Source Citations and Runtime References in ADRs
- Set ADR Status to 'Accepted' for Existing Implicit Patterns
- ADR Superseding When Feature Is Removed
- Ghost Entries Indicate Stale Documentation Migrations
- LLM-Based Architecture Checks Need Conservative Scope
- Deferred Imports and Async Read-Then-Write Are Documented Acceptable
- Architecture Tests Must Assert Content Not Just Structure
- Three-Layer Defense-in-Depth for Architecture Enforcement
- Claude Code Discovers Commands From Subprocess CWD
- hf.* Namespace Isolation with .gitignore Entries
- Unified Discovery Across Multiple Registration Mechanisms
- Path Traversal Guard for extra_tool_dirs
- Pre-Flight Validation and Escalation Pattern
- Prevent Scope Creep While Maintaining Correctness
- Model Duplication Across Codebase Suggests Ownership Clarity Issue
- Validate Diagram References Point to Existing Code
- Hindsight Client Cleanup Ownership Must Be Explicit
- Create Regression Test Files Before Documentation Reference
- Architecture Diagram Scope Can Exceed Implementation Plan
- Trust Fleet — Lights-Off Background Loop Pattern
- DedupStore + Reconcile-on-Close Pattern
- Eight-Checkpoint Loop Wiring Checklist
- Loop Wiring Auto-Discovery Test
- Auto-Revert on RC Red — Four-Guardrail Policy
- Per-Loop Telemetry — emit_loop_subprocess_trace
- Never Write Sleep Loops Waiting for Background Tasks
- Mocking at the Wrong Level
- Hardcoded Path Lists That Duplicate Filesystem State
- Adding a New Avoided Pattern
- Use make scaffold-loop to Generate Loop Boilerplate
- Restart Safety for self._ State in Background Loops
- Daily Cost-Cap Kill-Switch

## Architecture-Async-Control (24)

- A-prefixed async wrappers delegate sync I/O to asyncio.to_thread()
- Async context managers: add __aenter__, __aexit__, _closed flag
- Async helper extraction: keep shared-resource cleanup in coordinator finally
- Done callbacks: use module-level functions, not methods
- Label-based async loop routing via GitHub issue labels
- Clarity score routing: fast path vs multi-stage maturation pipeline
- Side-effect consumption pattern: initialize, populate, expose, clear
- Callback construction order: state → snapshot → router → tracker
- Callbacks decouple isolated components from orchestrator state
- Orchestrator pattern: extracted helpers return values for threading
- Config tuples replace copy-paste blocks with parameterized loops
- Polling loops must sleep when service disabled
- Context manager protocol: wrap httpx.AsyncClient with __aenter__/__aexit__
- httpx.AsyncClient.aclose() is idempotent and safe for multiple calls
- ServiceRegistry (composition root) needs async aclose() method
- Sentry integration: ERROR+ only triggers alerts (WARNING bypasses)
- Fatal error hierarchy: AuthenticationError and CreditExhaustedError propagate
- Background loops: five-step audit pattern
- Background loop wiring: synchronize 5 locations
- Background loops vs per-PR skills: distinct patterns
- Phase-filtered skill injection: tool filtering only, execution unchanged
- Multiple backend skills: use marker-based checks, not strict structure
- Two-file consolidation: Pydantic model and JSONL persistence must sync
- Operator review gates dynamic skills due to prompt injection risk

## Architecture-Imports-Types (12)

- TYPE_CHECKING guard pattern for type-only imports
- Deferred imports in function bodies
- Exception classification functions defer exception imports
- monkeypatch.delitem() safely removes modules in tests
- Optional Dependencies: Graceful Degradation and Safe Handling
- Deferred imports preserve test mocking patterns
- Logger names resolve to full module path from __name__
- Environment Override Validation via get_args() for Literal Types
- Distinguish similarly-named modules during cleanup
- Import-site patch targets must migrate with extracted functions
- Strict no-circular-import rule for extracted coordinators
- Restrict extracted component imports to prevent circular dependencies

## Architecture-Layers (23)

- Four-Layer Architecture with Downward-Only Imports
- Use @runtime_checkable Protocols for Structural Typing
- Service Registry as Single Composition Root
- Background Loop 5-Point Wiring Synchronization
- Use Pattern-Based Inference to Assign Layer Membership
- Extract Pure Functions for Independently-Testable Business Logic
- Prefer Module-Level Utility Functions Over Instance Methods
- Convert Closures to Standalone Functions by Parameterizing Nonlocal State
- Pass Config Objects as Parameters for Configuration-Dependent Values
- Use Re-Exports to Preserve Import Paths During Refactoring
- Add Optional Parameters with None Defaults for Backward Compatibility
- Use Facade + Composition for Large Class Decomposition
- Layer 1 Assignment for Pure Data Constants
- Layer Checker Must Track Newly Added Data Modules
- Facade Exception: Public Method Limits for Behavioral Classes
- Distinguish Public Facades from Implementation in Acceptance Criteria
- Template Method Exception to 50-Line Logic Limit
- Coordinator + Focused Helpers Decomposition Pattern
- Orchestrator Pattern: Deferred Module Registration via Factory
- Avoid Thin-Wrapper Abstractions—Target Concrete Duplication
- Use Sibling File Patterns as Architectural Reference
- Module-Level State via Constructor Injection
- Preserve Organizational Comments During Dead Code Removal

## Architecture-Patterns-Practices (27)

- Use monkeypatch.delitem(raising=False) for sys.modules cleanup
- Parametrized tests with dual lists for interface conformance
- Use conftest session-scope setup for deferred imports in tests
- Call discovery functions on-demand at runtime
- Use reversible naming conventions to eliminate registry files
- Catch broad exceptions during module discovery
- Coordinator pattern with call-order sensitivity
- NamedTuple for multi-return extracted methods
- Parameter threading across extracted methods
- Structured transcript parsing: markers and lists
- Separate parsing utilities from subprocess concerns
- Thin public wrappers replace private method access
- Line/method budgets force better decomposition
- Selective EventBus threading by behavioral intent
- Never-raise contract uses broad exception catching
- Use exc_info=True to preserve full exception tracebacks
- Test class names describe scenarios, not subjects
- Inline implementations preferred over extracted utilities
- Multi-bank memory deduplication via PromptDeduplicator
- Multi-tier context capping for memory injection
- Strategy dispatcher pattern for conditional behavior
- Export widely-reused constants without underscore prefix
- Document variant patterns; defer premature parameterization
- Dependency injection + re-export for backward-compatible splits
- Sub-factory coordination via frozen dataclass
- Distinguish local from cross-group wiring at architecture boundary
- AST-based regression tests are fragile to refactoring

## Architecture-Refactoring (18)

- Consolidate patterns with explicit scope to avoid partial migrations
- Verify dead code removal via tests, lint, and layer checks
- Complete dead code removal: update MODULE_LAYERS, delete stubs, preserve comments
- Dead-code removal: three-phase decomposition pattern
- Wire unconnected config parameters to existing consumers
- Visual alignment of code dicts overrides logical layer assignment
- Define explicit scope for extraction refactors to prevent scope creep
- Use symbol names instead of line numbers in refactoring plans
- Cross-cutting methods as callbacks, not new classes
- Regex-based test parsing constrains source structure format
- Verify dead code removal with grep across src/ and tests/
- Audit __all__ exports and module re-exports when removing public functions
- Preserve module-specific guards when extracting duplicated logic
- Grep word-boundary verification validates constant extraction
- Design extracted methods to accept unused parameters for future integration
- Backward-compat layers require individual liveness evaluation per item
- Document trade-off when removing implicit documentation methods
- Use underscore prefix for local implementation details in module-level functions

## Architecture-State-Persistence (23)

- Atomic writes with fsync and replace for crash safety
- File locking for JSONL rotation prevents TOCTOU bugs
- Cache JSONL parsing results with TTL for handlers
- Single-writer assumption enables simpler persistence
- Feature gates isolate incomplete features from production
- Optional fields enable schema evolution without breaking changes
- Frozen dataclasses bundle immutable context safely
- In-place mutations preserve shared dict references
- Pass immutable scalars as parameters, not shared references
- Annotated[str, Validator] adds validation without breaking serialization
- Literal types provide compile-time validation for bounded fields
- Convert dict returns to typed Pydantic models
- Empty string sentinel with Union type maintains type safety
- StrEnum fields serialize without data migration
- Naming conventions are scoped to architectural layers
- f-string output format decoupled from parameter naming
- FastAPI route registration order affects specificity matching
- Convert closure mutable state to class-based encapsulation
- Endpoint path preservation enables test reuse across refactors
- Pydantic Field() accepts module-level constants safely
- Path prefix pattern handles root and nested objects correctly
- Accept typed enums at method signatures, call .value internally
- Parametrized validation tests isolate new validators

## Dependencies (15)

- Use TYPE_CHECKING guards to break circular imports
- Use callbacks instead of class refs for runtime dependencies
- Degrade gracefully when optional dependencies fail
- Use Protocol for optional dependency interfaces
- Define shared artifacts once, import everywhere
- Extract parallel-independent classes before dependent ones
- Verify extraction completeness in two stages
- Register FastAPI catch-all routes last
- Embed schema_version in each JSON line
- Use Pydantic defaults for backward-compatible schemas
- Scan transitive dependencies when invalidating items
- Use atomic writes with rotate_backups for versioning
- Use sha256(text)[:16] for synthetic API content IDs
- Type signatures communicate breaking contract changes
- Never import optional deps at module level in tests

## Gotchas (52)

- Verify imports are present and not circular before type annotations
- Import ordering follows isort: stdlib, third-party, local
- Use `is None` and `is not None` for optional objects
- Protocol method signatures must match exactly
- Class refactoring: enforce ≤400 lines, ≤15 public methods
- Preserve edge cases during refactoring (label ordering, removal)
- Delete code blocks from bottom-to-top to avoid line-number shift
- Patch mock functions at definition site, not import site
- Verify file existence before planning changes
- Serialization tests must validate both directions
- Use explicit markers in tests instead of prose
- ID generation must be consistent across all lookups
- Run tests and quality checks before declaring work complete
- Distinguish bug exceptions from transient operational failures
- Use logger.exception() only for genuine bugs, not transient failures
- HTTP errors: use reraise_on_credit_or_bug() for critical exceptions
- Subprocess: catch TimeoutExpired and CalledProcessError separately
- Wrap per-item API calls in retry loops to isolate failures
- Background loops: classify exceptions (fatal, bug, transient)
- Async/await: omitting await returns unawaited coroutines
- Config validators serve as source of truth for audit fields
- New list[str] label fields must have optional defaults
- JSONL: append-only with idempotent writes and atomic ops
- Schema evolution: new Pydantic fields with defaults load old state
- Frozen Pydantic models: use object.__setattr__ for mutation
- Use idempotent installation when HydraFlow manages itself
- Preserve worktrees on HITL failure for post-mortem debugging
- Pass explicit self_fname parameter to avoid implicit self-exclusion
- Representation consistency: document which model each helper uses
- Stage progression: verify both ordering and progression logic
- Skip detection triggers only for plan-stage or later
- Phase progression via label mutations is observable
- Telemetry: always expose sample_size alongside metrics
- Aggregate telemetry by final attempt outcome, not per-attempt
- Memory filtering: check both content prefix AND metadata status
- Memory query customization: prepend context, not replace
- Enforcement ADRs: explicit tier-to-mechanism mapping
- Commit message validation: allow WIP and auto-generated commits
- New skills start with blocking=False until proven
- Hardcode workflow concepts in PHASE_SKILL_GUIDANCE dict
- Alpine Linux: use portable shell commands to consume memory
- Separate silent events from events with result values
- Create specialized methods instead of overloading general ones
- Document top 3–5 failure risks in pre-mortem phase
- Best-effort parsing: use try/except, never raise on format failure
- logger.error() requires format string as first argument
- Per-worker model overrides via HYDRAFLOW_*_MODEL env vars
- Hindsight recall toggle during observation window
- Self-review PRs before declaring done
- Use explicit reasoning prompts for analysis-heavy tasks
- Sentry captures real code bugs only, not transient failures
- Never use git commit --no-verify or --no-hooks

## Patterns (32)

- Schema evolution with optional fields and type narrowing
- Verify call sites before refactoring function signatures
- Preserve public/semi-public method signatures during extraction
- Preserve error isolation during refactoring
- Mock at definition site, not import site
- Use structural checks instead of isinstance() for protocol verification
- Run existing tests unchanged after refactoring
- Use threading.Lock in thread pools, asyncio.Lock only for coroutines
- Use crash-safe file I/O patterns for persistence
- Use claim-then-merge for async queue processing
- Preserve tracing context lifecycle with try/finally
- Keep event publishing coupled with condition checks
- Preserve retry state during phase result extraction
- Maintain immutable return contracts in phase routing
- Two-round memory budget allocation
- Lazy-load memory context on user action
- Dedup memory items via SHA-256 hashing with threshold
- Batch load scoring data once per operation
- Full preference learning pathway
- Coerce Hindsight metadata values to strings
- Conservative contradiction detection with priority
- Memory eviction updates both item scores and items atomically
- Dual-file persistence: JSONL + atomic JSON
- Documentation consistency across CLAUDE.md and README
- Kill-Switch Convention — enabled_cb at top of _do_work
- HITL Escalation Channel — hitl-escalation label
- Underscore-prefixed names are not public imports
- Use bare _ for truly unused loop variables
- DRY principle for frontend constants and styles
- Worktree workflow and conventions
- Run and dev commands
- Why memory/observation is harnessed, not autonomous

## Testing (34)

- Enforce function structure limits for testability
- Mock at definition site, not usage site
- Mark integration tests with @pytest.mark.integration
- Test async patterns with AsyncMock and fire-and-forget cleanup
- Create Python script stand-ins for subprocess/CLI testing
- Use conftest as single source of truth for fixture setup
- Wire real business logic in integration tests, mock subprocess boundary
- Test protocol satisfaction with structural + duck typing
- Verify façaded refactors with __getattr__ routing tests
- Test extraction by running prompt-assertion tests in isolation
- Test Sentry/telemetry by asserting numeric values, not just key presence
- Assert on key terms, not exact query strings
- Use Playwright for frontend testing, not TestClient alone
- Never assert on absolute singleton ID values
- Keep schema evolution tests in sync with constants
- Update all serialization tests when adding Pydantic fields
- Use `is None` for optional object truthiness checks
- Check conftest before adding duplicate test helpers
- Never test ADR markdown content
- Always run make quality before declaring work complete
- Write unit tests before committing code changes
- Kill-switch testing pattern for background loops
- Cassette-based fake adapter contract testing
- Meta-observability with bounded recursion via trust fleet
- MockWorld fixture composes all external fakes into controllable environment
- Scenario tests are additive to unit and integration tests
- Run scenario tests with make scenario and make scenario-loops
- Caretaker-loop Pattern A: catalog-driven invocation
- Caretaker-loop Pattern B: direct instantiation with config overrides
- Test concurrent file operations with deterministic iteration counts
- Memory bank deduplication uses priority mapping
- Skill definition replication requires 4 backend consistency
- Cross-location key consistency is critical for data pipelines
- Feature toggle implementation requires config field + ENV override
