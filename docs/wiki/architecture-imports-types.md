# Architecture-Imports-Types


## TYPE_CHECKING guard pattern for type-only imports

Use `TYPE_CHECKING` to import types only for annotations, avoiding runtime overhead. With `from __future__ import annotations`, import under `if TYPE_CHECKING: from module import TypedDict  # noqa: TCH004`. Suppress ruff linting with the `# noqa: TCH004` comment.

**Why:** Prevents circular dependencies while preserving type information for static analysis.


```json:entry
{"id":"01KQNYW9WM9NY7XJ0DNPVW4GDG","title":"TYPE_CHECKING guard pattern for type-only imports","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:42:26.708353+00:00","updated_at":"2026-05-03T03:42:26.708383+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Deferred imports in function bodies

Keep imports inside method bodies where used, not hoisted to module level. Use `# noqa: PLC0415` to suppress linting. Example: `def helper(): from trace_rollup import trace_context` rather than at module level. Apply to optional services (hindsight, docker) and cross-module utilities.

**Why:** Avoids startup overhead, enables graceful degradation for optional dependencies, prevents circular imports, and preserves test mocking patterns.


```json:entry
{"id":"01KQNYW9WM9NY7XJ0DNPVW4GDH","title":"Deferred imports in function bodies","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:42:26.708408+00:00","updated_at":"2026-05-03T03:42:26.708411+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Exception classification functions defer exception imports

Functions classifying specific exception types should import those types in the function body, not module-level, using `# noqa: PLC0415`. Example: `def check_error(exc): import CustomException; return isinstance(exc, CustomException)`.

**Why:** Prevents circular imports in error-handling code while keeping type information available.


```json:entry
{"id":"01KQNYW9WM9NY7XJ0DNPVW4GDJ","title":"Exception classification functions defer exception imports","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:42:26.708418+00:00","updated_at":"2026-05-03T03:42:26.708420+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## monkeypatch.delitem() safely removes modules in tests

Use `monkeypatch.delitem('sys.modules', key, raising=False)` when removing modules from sys.modules to handle both existing and missing keys safely. Critical for testing code using deferred imports where sys.modules reset is needed between tests.

**Why:** Prevents KeyError when the module key doesn't exist in sys.modules.


```json:entry
{"id":"01KQNYW9WM9NY7XJ0DNPVW4GDK","title":"monkeypatch.delitem() safely removes modules in tests","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:42:26.708425+00:00","updated_at":"2026-05-03T03:42:26.708426+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Optional Dependencies: Graceful Degradation and Safe Handling

Services like Hindsight, Docker may be unavailable. Design via: (1) **Never-raise pattern**: wrap calls in try/except returning safe defaults, catch broad exceptions. (2) **Graceful degradation**: fall back to file storage or no-op. (3) **Explicit None checks**: guard with `if hindsight is not None:`. (4) **Fire-and-forget async variants**. In tests, never import optional dependencies at module level; use deferred imports in test methods instead.

**Why:** Failures in non-critical features must never crash the pipeline.


```json:entry
{"id":"01KQNYW9WM9NY7XJ0DNPVW4GDM","title":"Optional Dependencies: Graceful Degradation and Safe Handling","topic":null,"source_type":"plan","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:42:26.708431+00:00","updated_at":"2026-05-03T03:42:26.708432+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Deferred imports preserve test mocking patterns

Import external services (hindsight, recall_tracker) inside method bodies, not module-level, to allow `patch("hindsight.recall_safe", ...)` to intercept calls correctly. When imports are at module level, patches may not apply to the actual import binding used by the method.

**Why:** Ensures patches target the correct import binding when testing code depending on external services.

_Source: #6350 (plan)_


```json:entry
{"id":"01KQNYW9WM9NY7XJ0DNPVW4GDN","title":"Deferred imports preserve test mocking patterns","topic":null,"source_type":"plan","source_issue":6350,"source_repo":null,"created_at":"2026-05-03T03:42:26.708438+00:00","updated_at":"2026-05-03T03:42:26.708439+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Logger names resolve to full module path from __name__

Modules using `logging.getLogger(__name__)` resolve to the full dotted module path (e.g., hydraflow.shape_phase), not just the filename. Tests capturing logs must use the full module path or logger name matchers will fail.

**Why:** Log capture and filtering depend on exact module path matching.

_Source: #6325 (plan)_


```json:entry
{"id":"01KQNYW9WM9NY7XJ0DNPVW4GDP","title":"Logger names resolve to full module path from __name__","topic":null,"source_type":"plan","source_issue":6325,"source_repo":null,"created_at":"2026-05-03T03:42:26.708443+00:00","updated_at":"2026-05-03T03:42:26.708444+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Environment Override Validation via get_args() for Literal Types

The `_ENV_LITERAL_OVERRIDES` table and validation handler use `get_args()` to extract allowed values from Literal types and validate environment variable inputs at startup. This pattern decouples override validation from field defaults.

**Why:** Enables dynamic validation of environment overrides without hardcoding literal values in validation code.

_Source: #6310 (plan)_


```json:entry
{"id":"01KQNYW9WM9NY7XJ0DNPVW4GDQ","title":"Environment Override Validation via get_args() for Literal Types","topic":null,"source_type":"plan","source_issue":6310,"source_repo":null,"created_at":"2026-05-03T03:42:26.708449+00:00","updated_at":"2026-05-03T03:42:26.708450+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Distinguish similarly-named modules during cleanup

When removing dead code, watch for naming collisions—e.g., `verification.py` (orphaned formatter) vs `verification_judge.py` (active production code). Confusion between them can lead to removing live code. Always verify caller graphs and module purpose separately.

**Why:** Prevents accidentally deleting active modules that have similar names to dead code.

_Source: #6365 (plan)_


```json:entry
{"id":"01KQNYW9WM9NY7XJ0DNPVW4GDR","title":"Distinguish similarly-named modules during cleanup","topic":null,"source_type":"plan","source_issue":6365,"source_repo":null,"created_at":"2026-05-03T03:42:26.708457+00:00","updated_at":"2026-05-03T03:42:26.708458+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Import-site patch targets must migrate with extracted functions

When tests patch functions at import sites (e.g., `patch('review_phase.analyze_patterns')`), extracting those functions to new modules breaks the patch. Update test patches to target the new module: `patch('review_insight_recorder.analyze_patterns')`. Attribute mocking via instance assignment continues to work unchanged.

**Why:** Patch targets must match the actual import location where the function is used.

_Source: #6321 (plan)_


```json:entry
{"id":"01KQNYW9WM9NY7XJ0DNPVW4GDS","title":"Import-site patch targets must migrate with extracted functions","topic":null,"source_type":"plan","source_issue":6321,"source_repo":null,"created_at":"2026-05-03T03:42:26.708463+00:00","updated_at":"2026-05-03T03:42:26.708464+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Strict no-circular-import rule for extracted coordinators

Extracted coordinator classes must never import the original ReviewPhase class. Coordinators should only import domain modules, models, config, and phase_utils. Back-references to ReviewPhase methods must flow through callback parameters passed at construction time.

**Why:** Prevents circular imports that break module independence and extraction.

_Source: #6321 (plan)_


```json:entry
{"id":"01KQNYW9WM9NY7XJ0DNPVW4GDT","title":"Strict no-circular-import rule for extracted coordinators","topic":null,"source_type":"plan","source_issue":6321,"source_repo":null,"created_at":"2026-05-03T03:42:26.708470+00:00","updated_at":"2026-05-03T03:42:26.708471+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Restrict extracted component imports to prevent circular dependencies

Extracted modules (PipelineStatsBuilder, CreditPauseManager, LoopSupervisor) must only import from a safe set: config, events, models, subprocess_util, service_registry, bg_worker_manager. Never import from orchestrator.py, even transitively.

**Why:** Keeps extracted components independently testable and reusable without hidden dependencies.

_Source: #6323 (plan)_


```json:entry
{"id":"01KQNYW9WM9NY7XJ0DNPVW4GDV","title":"Restrict extracted component imports to prevent circular dependencies","topic":null,"source_type":"plan","source_issue":6323,"source_repo":null,"created_at":"2026-05-03T03:42:26.708476+00:00","updated_at":"2026-05-03T03:42:26.708477+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
