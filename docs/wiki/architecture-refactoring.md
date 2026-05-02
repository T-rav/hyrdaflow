# Architecture Refactoring

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

## Plan line numbers become stale; search by pattern instead



When implementing a plan generated in a prior session, files may have been modified since the plan was written. Prefer searching for method signature patterns rather than relying on exact line numbers provided in the plan.

_Source: #6317 (plan)_

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WP","title":"Plan line numbers become stale; search by pattern instead","content":"When implementing a plan generated in a prior session, files may have been modified since the plan was written. Prefer searching for method signature patterns rather than relying on exact line numbers provided in the plan.","topic":null,"source_type":"plan","source_issue":6317,"source_repo":null,"created_at":"2026-04-10T03:55:35.397280+00:00","updated_at":"2026-04-10T03:55:35.397281+00:00","valid_from":"2026-04-10T03:55:35.397280+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Cross-cutting methods as callbacks, not new classes



Methods called by 4+ concerns (like `_escalate_to_hitl` and `_publish_review_status`) should stay on the origin class and be passed as bound-method callbacks to extracted coordinators. This avoids creating yet another coordinator just for common operations and matches the established PostMergeHandler/MergeApprovalContext callback pattern.

_Source: #6321 (plan)_

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WT","title":"Cross-cutting methods as callbacks, not new classes","content":"Methods called by 4+ concerns (like `_escalate_to_hitl` and `_publish_review_status`) should stay on the origin class and be passed as bound-method callbacks to extracted coordinators. This avoids creating yet another coordinator just for common operations and matches the established PostMergeHandler/MergeApprovalContext callback pattern.","topic":null,"source_type":"plan","source_issue":6321,"source_repo":null,"created_at":"2026-04-10T04:19:28.375208+00:00","updated_at":"2026-04-10T04:19:28.375220+00:00","valid_from":"2026-04-10T04:19:28.375208+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Regex-based test parsing creates hard constraints on source structure



`test_loop_wiring_completeness.py` uses regex to parse `orchestrator.py` source for patterns like `('triage', self._triage_loop)` in loop_factories. Refactoring must preserve both the physical location and format of these definitions in orchestrator.py, not just the functionality. Any change to how loop_factories is defined will break the regex match and cause test failures, making this a critical constraint.

_Source: #6323 (plan)_

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WZ","title":"Regex-based test parsing creates hard constraints on source structure","content":"`test_loop_wiring_completeness.py` uses regex to parse `orchestrator.py` source for patterns like `('triage', self._triage_loop)` in loop_factories. Refactoring must preserve both the physical location and format of these definitions in orchestrator.py, not just the functionality. Any change to how loop_factories is defined will break the regex match and cause test failures, making this a critical constraint.","topic":null,"source_type":"plan","source_issue":6323,"source_repo":null,"created_at":"2026-04-10T04:47:03.630689+00:00","updated_at":"2026-04-10T04:47:03.630691+00:00","valid_from":"2026-04-10T04:47:03.630689+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
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

## Preserve module-specific guards when extracting duplicated logic



When consolidating duplicated parsing patterns, keep module-specific behavior (e.g., empty-transcript guards) outside the shared helper. In plan_compliance.py, the early-return guard precedes the shared pattern and must not be folded into the helper function. Extract only the common logic, leaving module-specific pre- or post-conditions in place.

_Source: #6349 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPG","title":"Preserve module-specific guards when extracting duplicated logic","content":"When consolidating duplicated parsing patterns, keep module-specific behavior (e.g., empty-transcript guards) outside the shared helper. In plan_compliance.py, the early-return guard precedes the shared pattern and must not be folded into the helper function. Extract only the common logic, leaving module-specific pre- or post-conditions in place.","topic":null,"source_type":"plan","source_issue":6349,"source_repo":null,"created_at":"2026-04-10T06:47:04.972401+00:00","updated_at":"2026-04-10T06:47:04.972412+00:00","valid_from":"2026-04-10T06:47:04.972401+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
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

## Use underscore prefix for local implementation details in functions



When defining intermediate variables in module-level functions (e.g., `_runner_kwargs`), use leading underscore to signal they are private implementation details, not public API. This convention improves readability and signals intent to future readers that the variable is not meant for external use.

_Source: #6354 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPV","title":"Use underscore prefix for local implementation details in functions","content":"When defining intermediate variables in module-level functions (e.g., `_runner_kwargs`), use leading underscore to signal they are private implementation details, not public API. This convention improves readability and signals intent to future readers that the variable is not meant for external use.","topic":null,"source_type":"plan","source_issue":6354,"source_repo":null,"created_at":"2026-04-10T07:09:55.773138+00:00","updated_at":"2026-04-10T07:09:55.773141+00:00","valid_from":"2026-04-10T07:09:55.773138+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Partial migrations of similar components create maintenance burden



When multiple similar classes share the same pattern (e.g., 8 runner instantiations with identical kwargs), refactoring only some of them creates future maintenance risk. Always refactor all instances together, even if some seem unnecessary. Use explicit line-number lists to catch all occurrences and prevent partial migrations.

_Source: #6354 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPT","title":"Partial migrations of similar components create maintenance burden","content":"When multiple similar classes share the same pattern (e.g., 8 runner instantiations with identical kwargs), refactoring only some of them creates future maintenance risk. Always refactor all instances together, even if some seem unnecessary. Use explicit line-number lists to catch all occurrences and prevent partial migrations.","topic":null,"source_type":"plan","source_issue":6354,"source_repo":null,"created_at":"2026-04-10T07:09:55.773107+00:00","updated_at":"2026-04-10T07:09:55.773111+00:00","valid_from":"2026-04-10T07:09:55.773107+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
