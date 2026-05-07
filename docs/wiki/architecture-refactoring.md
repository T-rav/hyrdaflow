# Architecture-Refactoring


## Consolidate patterns with explicit scope to avoid partial migrations

Consolidate patterns only when systemic (e.g., 8 runners total, not 3) and consolidate all instances together or none, not partially.

Example: Extract duplicated paths into module-level constants like ALL_LIFECYCLE_LABEL_FIELDS to enable cross-module imports without circular dependencies.

**Why:** Partial migrations create maintenance burden; full consolidation with constants enables safe reuse.


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T2X","title":"Consolidate patterns with explicit scope to avoid partial migrations","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:09:34.637287+00:00","updated_at":"2026-05-03T04:09:34.637531+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Verify dead code removal via tests, lint, and layer checks

Verify dead code removal with a four-step checklist: (1) make test for dependencies, (2) make quality-lite for lint/types/security, (3) make layer-check for boundaries, (4) grep across src/ and tests/ for references.

Example: Run all four steps sequentially to catch hidden dependencies and incomplete removals.

**Why:** Ensures no hidden dependencies remain and validates completeness.


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T2Y","title":"Verify dead code removal via tests, lint, and layer checks","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:09:34.637582+00:00","updated_at":"2026-05-03T04:09:34.637584+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Complete dead code removal: update MODULE_LAYERS, delete stubs, preserve comments

When removing modules, update MODULE_LAYERS dict, delete entire files (not stubs), and preserve section heading comments if other items remain.

Example: In check_layer_imports.py, remove the module entry; delete the file entirely; keep '# --- Return Types ---' comment if other return types remain.

**Why:** Empty stubs create ambiguity; preserved comments document remaining members and maintain section structure.


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T2Z","title":"Complete dead code removal: update MODULE_LAYERS, delete stubs, preserve comments","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:09:34.637596+00:00","updated_at":"2026-05-03T04:09:34.637597+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dead-code removal: three-phase decomposition pattern

Decompose dead-code removal into three phases: P1 removes core methods and plumbing, P2 removes tests and helpers, P3 verifies with grep and type checking.

Example: PR #6315 phases removals as: remove method implementations → remove tests → verify no references remain.

**Why:** Phased approach prevents partial removals; ensures all callers updated before final verification.

_Source: #6315 (plan)_


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T30","title":"Dead-code removal: three-phase decomposition pattern","topic":null,"source_type":"plan","source_issue":6315,"source_repo":null,"created_at":"2026-05-03T04:09:34.637607+00:00","updated_at":"2026-05-03T04:09:34.637608+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Wire unconnected config parameters to existing consumers

When a consumer already accepts constructor parameters matching config fields but wiring is missing from the service builder, add the one-line connection.

Example: StateTracker accepts constructor params; check its signature first—it often has sensible defaults. Wire the param in the service builder.

**Why:** Low-risk, high-value fix; the consumer already supports the parameter.

_Source: #6314 (plan)_


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T31","title":"Wire unconnected config parameters to existing consumers","topic":null,"source_type":"plan","source_issue":6314,"source_repo":null,"created_at":"2026-05-03T04:09:34.637616+00:00","updated_at":"2026-05-03T04:09:34.637617+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Visual alignment of code dicts overrides logical layer assignment

Code dict entries should visually align with their layer assignment comment blocks, not their logical layer placement.

Example: In a type layer section, position dict entries to align with the comment header '# --- Types ---', not where they logically belong.

**Why:** Misalignment is visually misleading and reduces code clarity for future maintainers.

_Source: #6295 (review)_


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T32","title":"Visual alignment of code dicts overrides logical layer assignment","topic":null,"source_type":"review","source_issue":6295,"source_repo":null,"created_at":"2026-05-03T04:09:34.637625+00:00","updated_at":"2026-05-03T04:09:34.637626+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Define explicit scope for extraction refactors to prevent scope creep

Extraction refactors must explicitly name target files and functions in scope, not just the pattern to extract.

Example: 'Extract duplicates from runners.py and handlers.py; exclude similar patterns in coordinators.py' instead of vague 'consolidate duplication'.

**Why:** Clarifies intentional exclusions; prevents false-positive review flags when boundaries are ambiguous.

_Source: #6295 (review)_


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T33","title":"Define explicit scope for extraction refactors to prevent scope creep","topic":null,"source_type":"review","source_issue":6295,"source_repo":null,"created_at":"2026-05-03T04:09:34.637633+00:00","updated_at":"2026-05-03T04:09:34.637634+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use symbol names instead of line numbers in refactoring plans

Identify code by symbol name and signature, not line numbers, in refactoring plans and PRs.

Example: Remove `invalidate_cache()` from PlannerRunner instead of 'line 287 of X'.

**Why:** Line numbers shift during merges and file changes; symbols remain stable across refactorings.


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T34","title":"Use symbol names instead of line numbers in refactoring plans","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:09:34.637650+00:00","updated_at":"2026-05-03T04:09:34.637652+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Cross-cutting methods as callbacks, not new classes

Methods called by 4+ concerns should stay on the origin class as callbacks, not extract to new coordinators.

Example: `_escalate_to_hitl` stays on origin class; pass as bound-method callback to extracted coordinators.

**Why:** Avoids creating another coordinator; matches PostMergeHandler/MergeApprovalContext callback pattern.

_Source: #6321 (plan)_


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T35","title":"Cross-cutting methods as callbacks, not new classes","topic":null,"source_type":"plan","source_issue":6321,"source_repo":null,"created_at":"2026-05-03T04:09:34.637660+00:00","updated_at":"2026-05-03T04:09:34.637661+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Regex-based test parsing constrains source structure format

Tests using regex to parse source (e.g., test_loop_wiring_completeness.py) require specific physical format and location of definitions.

Example: loop_factories regex expects `('triage', self._triage_loop)` format; changing location or format breaks the test even if functionality is preserved.

**Why:** Regex-based tests constrain source structure; refactoring must preserve both format and location.

_Source: #6323 (plan)_


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T36","title":"Regex-based test parsing constrains source structure format","topic":null,"source_type":"plan","source_issue":6323,"source_repo":null,"created_at":"2026-05-03T04:09:34.637668+00:00","updated_at":"2026-05-03T04:09:34.637669+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Verify dead code removal with grep across src/ and tests/

Verify dead code removal completeness with systematic grep across src/ and tests/ for remaining references.

Example: `grep -rn 'from X import' src/ tests/` and `grep -rn '\bsymbol_name\b' src/ tests/` should both return zero.

**Why:** Catches direct imports, transitive dependencies, and validates removal completeness.


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T37","title":"Verify dead code removal with grep across src/ and tests/","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:09:34.637675+00:00","updated_at":"2026-05-03T04:09:34.637676+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Audit __all__ exports and module re-exports when removing public functions

Audit __all__ exports and module re-exports when removing public functions to prevent stale references.

Example: Check for stale __all__ or re-exports like `from X import removed_func` after function removal.

**Why:** Prevents subtle import errors; keeps public API surface clean and explicit.

_Source: #6366 (plan)_


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T38","title":"Audit __all__ exports and module re-exports when removing public functions","topic":null,"source_type":"plan","source_issue":6366,"source_repo":null,"created_at":"2026-05-03T04:09:34.637681+00:00","updated_at":"2026-05-03T04:09:34.637682+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve module-specific guards when extracting duplicated logic

Keep module-specific behavior outside shared helpers when consolidating duplicated logic.

Example: Empty-transcript guard in plan_compliance.py must precede shared pattern and stay local, not folded into helper.

**Why:** Shared helpers must not carry module-specific constraints; preserves reusability.

_Source: #6349 (plan)_


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T39","title":"Preserve module-specific guards when extracting duplicated logic","topic":null,"source_type":"plan","source_issue":6349,"source_repo":null,"created_at":"2026-05-03T04:09:34.637693+00:00","updated_at":"2026-05-03T04:09:34.637695+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Grep word-boundary verification validates constant extraction

Validate constant extraction completeness using word-boundary grep to find all magic number occurrences.

Example: `grep -rn '\b<literal>\b' src/ tests/` should return exactly 1 match (the constant definition).

**Why:** Language-agnostic technique; catches incomplete replacements systematically.

_Source: #6341 (plan)_


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T3A","title":"Grep word-boundary verification validates constant extraction","topic":null,"source_type":"plan","source_issue":6341,"source_repo":null,"created_at":"2026-05-03T04:09:34.637700+00:00","updated_at":"2026-05-03T04:09:34.637703+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Design extracted methods to accept unused parameters for future integration

Accept unused parameters in extracted methods if they enable future feature extensibility without implementing now.

Example: `_build_close_comment(release_url)` where release_url is currently empty string; creates seam for future use.

**Why:** Avoids forcing API changes later; enables future extensibility without premature implementation.

_Source: #6342 (plan)_


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T3B","title":"Design extracted methods to accept unused parameters for future integration","topic":null,"source_type":"plan","source_issue":6342,"source_repo":null,"created_at":"2026-05-03T04:09:34.637708+00:00","updated_at":"2026-05-03T04:09:34.637709+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Backward-compat layers require individual liveness evaluation per item

Evaluate each item in backward-compatibility property collections individually, not as a blanket layer.

Example: review_phase.py has active _run_post_merge_hooks and dead _save_conflict_transcript; each needs individual evaluation.

**Why:** Cannot assume entire layer is wholly live or dead; mixed liveness within collections is common.

_Source: #6345 (plan)_


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T3C","title":"Backward-compat layers require individual liveness evaluation per item","topic":null,"source_type":"plan","source_issue":6345,"source_repo":null,"created_at":"2026-05-03T04:09:34.637715+00:00","updated_at":"2026-05-03T04:09:34.637716+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Document trade-off when removing implicit documentation methods

When removing implicit documentation methods, document the trade-off between explicitness and simplicity.

Example: Removing `invalidate()` that lists cache attributes trades explicitness for simplicity; __init__ remains self-documenting.

**Why:** Helps readers understand design decisions; acknowledges what implicit documentation is lost.

_Source: #6346 (plan)_


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T3D","title":"Document trade-off when removing implicit documentation methods","topic":null,"source_type":"plan","source_issue":6346,"source_repo":null,"created_at":"2026-05-03T04:09:34.637721+00:00","updated_at":"2026-05-03T04:09:34.637722+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use underscore prefix for local implementation details in module-level functions

Use underscore prefix for intermediate variables in module-level functions to signal private implementation details.

Example: `_runner_kwargs = {...}` in module-level function signals internal-only variable.

**Why:** Signals private implementation; improves readability and code clarity.

_Source: #6354 (plan)_


```json:entry
{"id":"01KQP0DZNDCVJVV0YHTG430T3E","title":"Use underscore prefix for local implementation details in module-level functions","topic":null,"source_type":"plan","source_issue":6354,"source_repo":null,"created_at":"2026-05-03T04:09:34.637727+00:00","updated_at":"2026-05-03T04:09:34.637728+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
