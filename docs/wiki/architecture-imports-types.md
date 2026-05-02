# Architecture Imports Types

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

## TYPE_CHECKING prevents circular imports on cross-module TypedDicts



When a TypedDict is shared between a loop module and service module (ADRReviewResult in adr_reviewer_loop.py used by adr_reviewer.py), import under TYPE_CHECKING guard to avoid circular imports while preserving type information for static analysis. Codebase already uses this pattern extensively.

_Source: #6331 (plan)_

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XC","title":"TYPE_CHECKING prevents circular imports on cross-module TypedDicts","content":"When a TypedDict is shared between a loop module and service module (ADRReviewResult in adr_reviewer_loop.py used by adr_reviewer.py), import under TYPE_CHECKING guard to avoid circular imports while preserving type information for static analysis. Codebase already uses this pattern extensively.","topic":null,"source_type":"plan","source_issue":6331,"source_repo":null,"created_at":"2026-04-10T05:23:05.143432+00:00","updated_at":"2026-04-10T05:23:05.143433+00:00","valid_from":"2026-04-10T05:23:05.143432+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Preserve deferred imports for optional dependencies



Use deferred imports (import inside method body, not module-level) for optional or infrequently-used dependencies like `prompt_dedup`. This avoids startup cost and avoids hard dependency failures in unrelated code paths. When refactoring such code, preserve the deferred import pattern.

_Source: #6332 (plan)_

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0XG","title":"Preserve deferred imports for optional dependencies","content":"Use deferred imports (import inside method body, not module-level) for optional or infrequently-used dependencies like `prompt_dedup`. This avoids startup cost and avoids hard dependency failures in unrelated code paths. When refactoring such code, preserve the deferred import pattern.","topic":null,"source_type":"plan","source_issue":6332,"source_repo":null,"created_at":"2026-04-10T05:33:08.098298+00:00","updated_at":"2026-04-10T05:33:08.098299+00:00","valid_from":"2026-04-10T05:33:08.098298+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Deferred Imports Must Remain Inside Helpers



Optional module imports that live inside a method should stay inside extracted helpers, not moved to module level. This preserves graceful degradation when optional modules are missing. Moving deferred imports breaks the intent of the original error-isolation pattern.

_Source: #6355 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPW","title":"Deferred Imports Must Remain Inside Helpers","content":"Optional module imports that live inside a method should stay inside extracted helpers, not moved to module level. This preserves graceful degradation when optional modules are missing. Moving deferred imports breaks the intent of the original error-isolation pattern.","topic":null,"source_type":"plan","source_issue":6355,"source_repo":null,"created_at":"2026-04-10T07:14:58.678248+00:00","updated_at":"2026-04-10T07:14:58.678250+00:00","valid_from":"2026-04-10T07:14:58.678248+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
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

## Deferred imports preserve test mocking patterns



Import hindsight and recall_tracker inside method bodies (not module-level) to allow `patch("hindsight.recall_safe", ...)` to intercept calls correctly. When imports are at the top of the file, patches may not apply to the actual import binding used by the method. This pattern is critical for testing async helpers that depend on external services.

_Source: #6350 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPP","title":"Deferred imports preserve test mocking patterns","content":"Import hindsight and recall_tracker inside method bodies (not module-level) to allow `patch(\"hindsight.recall_safe\", ...)` to intercept calls correctly. When imports are at the top of the file, patches may not apply to the actual import binding used by the method. This pattern is critical for testing async helpers that depend on external services.","topic":null,"source_type":"plan","source_issue":6350,"source_repo":null,"created_at":"2026-04-10T06:55:39.084035+00:00","updated_at":"2026-04-10T06:55:39.084043+00:00","valid_from":"2026-04-10T06:55:39.084035+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Preserve lazy imports to avoid module-level coupling



When extracting a helper that imports heavy or optional dependencies like `PromptDeduplicator`, keep the import lazy inside the method body, not at module level. This matches existing patterns in the codebase and avoids import-time coupling to utilities that may not be needed on every execution path.

_Source: #6340 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP3","title":"Preserve lazy imports to avoid module-level coupling","content":"When extracting a helper that imports heavy or optional dependencies like `PromptDeduplicator`, keep the import lazy inside the method body, not at module level. This matches existing patterns in the codebase and avoids import-time coupling to utilities that may not be needed on every execution path.","topic":null,"source_type":"plan","source_issue":6340,"source_repo":null,"created_at":"2026-04-10T06:11:06.699159+00:00","updated_at":"2026-04-10T06:11:06.699162+00:00","valid_from":"2026-04-10T06:11:06.699159+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Logger names resolve to full module path from __name__



Modules using logging.getLogger(__name__) resolve to the full dotted module path (e.g., hydraflow.shape_phase), not just the filename (shape_phase). Tests that capture logs must use the full module path or logger name matchers will fail to find the expected logs.

_Source: #6325 (plan)_

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X2","title":"Logger names resolve to full module path from __name__","content":"Modules using logging.getLogger(__name__) resolve to the full dotted module path (e.g., hydraflow.shape_phase), not just the filename (shape_phase). Tests that capture logs must use the full module path or logger name matchers will fail to find the expected logs.","topic":null,"source_type":"plan","source_issue":6325,"source_repo":null,"created_at":"2026-04-10T04:51:52.058659+00:00","updated_at":"2026-04-10T04:51:52.058666+00:00","valid_from":"2026-04-10T04:51:52.058659+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Environment Override Validation via get_args() for Literal Types



The `_ENV_LITERAL_OVERRIDES` table and its validation handler use `get_args()` to extract allowed values from Literal types and validate environment variable inputs at startup. This pattern decouples override validation from field defaults, enabling a cleaner separation between string overrides (with defaults) and literal overrides (options only). Enables dynamic validation of environment overrides without hardcoding literal values in validation code.

_Source: #6310 (plan)_

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WE","title":"Environment Override Validation via get_args() for Literal Types","content":"The `_ENV_LITERAL_OVERRIDES` table and its validation handler use `get_args()` to extract allowed values from Literal types and validate environment variable inputs at startup. This pattern decouples override validation from field defaults, enabling a cleaner separation between string overrides (with defaults) and literal overrides (options only). Enables dynamic validation of environment overrides without hardcoding literal values in validation code.","topic":null,"source_type":"plan","source_issue":6310,"source_repo":null,"created_at":"2026-04-10T03:41:18.852325+00:00","updated_at":"2026-04-10T03:41:18.852328+00:00","valid_from":"2026-04-10T03:41:18.852325+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Distinguish similarly-named modules during cleanup



When removing dead code, watch for naming collisions—e.g., `verification.py` (orphaned formatter) vs `verification_judge.py` (active production code with real callers). Confusion between them can lead to removing live code or missing dependencies. Always verify caller graphs and module purpose separately.

_Source: #6365 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ9","title":"Distinguish similarly-named modules during cleanup","content":"When removing dead code, watch for naming collisions—e.g., `verification.py` (orphaned formatter) vs `verification_judge.py` (active production code with real callers). Confusion between them can lead to removing live code or missing dependencies. Always verify caller graphs and module purpose separately.","topic":null,"source_type":"plan","source_issue":6365,"source_repo":null,"created_at":"2026-04-10T07:59:04.461030+00:00","updated_at":"2026-04-10T07:59:04.461033+00:00","valid_from":"2026-04-10T07:59:04.461030+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
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

## Restrict extracted component imports to prevent circular dependencies



Extracted modules (PipelineStatsBuilder, CreditPauseManager, LoopSupervisor) must only import from a safe set: config, events, models, subprocess_util, service_registry, bg_worker_manager. Never import from orchestrator.py, even transitively. This strict boundary prevents import-time deadlocks and keeps extracted components independently testable and reusable.

_Source: #6323 (plan)_

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X1","title":"Restrict extracted component imports to prevent circular dependencies","content":"Extracted modules (PipelineStatsBuilder, CreditPauseManager, LoopSupervisor) must only import from a safe set: config, events, models, subprocess_util, service_registry, bg_worker_manager. Never import from orchestrator.py, even transitively. This strict boundary prevents import-time deadlocks and keeps extracted components independently testable and reusable.","topic":null,"source_type":"plan","source_issue":6323,"source_repo":null,"created_at":"2026-04-10T04:47:03.630704+00:00","updated_at":"2026-04-10T04:47:03.630706+00:00","valid_from":"2026-04-10T04:47:03.630704+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
