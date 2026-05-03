# Architecture-State-Persistence


## Atomic writes with fsync and replace for crash safety

Use atomic write pattern: write to temp file, fsync for durability, then `os.replace()` for atomic swap. Use centralized utilities: `file_util.atomic_write()` for full file rewrites and `file_util.append_jsonl()` for crash-safe appends with automatic mkdir/flush. Applies to WAL files, state snapshots, JSONL stores, and configuration.

**Why:** Prevents partial file corruption from crashes during writes.


```json:entry
{"id":"01KQP0AJ4Y4348S0D9AKRTCPP7","title":"Atomic writes with fsync and replace for crash safety","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:07:42.494727+00:00","updated_at":"2026-05-03T04:07:42.495108+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## File locking for JSONL rotation prevents TOCTOU bugs

When rotating or trimming JSONL files, acquire exclusive lock (`.{filename}.lock`) for the entire read-filter-write cycle. This prevents time-of-check-time-of-use bugs where file contents change between read and subsequent write.

**Why:** Without locking, concurrent access causes lost updates or inconsistent state.


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN95","title":"File locking for JSONL rotation prevents TOCTOU bugs","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:07:42.495178+00:00","updated_at":"2026-05-03T04:07:42.495182+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Cache JSONL parsing results with TTL for handlers

Cache JSONL log parsing results with TTL patterns for HTTP handlers. This avoids re-parsing identical entries on each request.

**Why:** Reduces CPU overhead for frequently-accessed logs.


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN96","title":"Cache JSONL parsing results with TTL for handlers","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:07:42.495222+00:00","updated_at":"2026-05-03T04:07:42.495224+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Single-writer assumption enables simpler persistence

Only the async orchestrator writes state—no concurrent writers. This eliminates write-ahead logging complexity. Recovery uses backup pattern: save `.bak` before overwriting, restore if corruption detected.

**Why:** WAL is required for concurrent writers; single-writer achieves crash safety with backups and atomic writes.


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN97","title":"Single-writer assumption enables simpler persistence","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:07:42.495241+00:00","updated_at":"2026-05-03T04:07:42.495243+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Feature gates isolate incomplete features from production

Gate incomplete features behind config flags (default False) rather than runtime degradation. Test both enabled/disabled paths separately. For optional allocations, use `get_allocation(label, fallback_cap)` returning config-defined caps when enabled, falling back when no budget set.

**Why:** Prevents confusing partial-state behavior and enables safe rollout.


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN98","title":"Feature gates isolate incomplete features from production","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:07:42.495255+00:00","updated_at":"2026-05-03T04:07:42.495257+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Optional fields enable schema evolution without breaking changes

Use TypedDict `total=False` or Pydantic optional fields for backward-compatible schema evolution. Missing fields handled with `.get(key, default)`. Add placeholder fields for planned features (marked with docstring notes), defaulting to empty strings. For JSONL records, new fields default gracefully.

**Why:** Enables adding fields without breaking existing consumers.


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN99","title":"Optional fields enable schema evolution without breaking changes","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:07:42.495270+00:00","updated_at":"2026-05-03T04:07:42.495272+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Frozen dataclasses bundle immutable context safely

Use frozen dataclasses (`@dataclass(frozen=True, slots=True)`) to bundle context parameters that won't change at runtime. Prevents accidental mutation and documents parameter-passing contracts. Ensure all fields have non-empty defaults if parametrized tests override individual fields.

**Why:** Immutability catches logic errors and makes intent explicit.


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9A","title":"Frozen dataclasses bundle immutable context safely","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:07:42.495288+00:00","updated_at":"2026-05-03T04:07:42.495290+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## In-place mutations preserve shared dict references

If sub-components reassign dicts (e.g., `self._queues = {}`) instead of mutating in-place (e.g., `self._queues[stage].clear()`), shared references break and mutations become invisible to other components. All state mutations in extracted classes must be in-place.

**Why:** Reassignment breaks shared references and causes mutations to be invisible to other components.

_Source: #6327 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9B","title":"In-place mutations preserve shared dict references","topic":null,"source_type":"plan","source_issue":6327,"source_repo":null,"created_at":"2026-05-03T04:07:42.495326+00:00","updated_at":"2026-05-03T04:07:42.495329+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Pass immutable scalars as parameters, not shared references

Immutable scalars like strings cannot be shared by reference—reassignment on the facade doesn't propagate to sub-components. Pass immutable values as parameters: `get_queue_stats(last_poll_ts=self._last_poll_ts)` instead of storing shared references.

**Why:** Immutable scalars can't be updated by reference the way mutable dicts can.

_Source: #6327 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9C","title":"Pass immutable scalars as parameters, not shared references","topic":null,"source_type":"plan","source_issue":6327,"source_repo":null,"created_at":"2026-05-03T04:07:42.495344+00:00","updated_at":"2026-05-03T04:07:42.495347+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Annotated[str, Validator] adds validation without breaking serialization

Use `Annotated[str, AfterValidator(...)]` to add runtime validation while maintaining serialization compatibility. This pattern serializes identically to bare `str` in JSON, enabling strict validation at construction without breaking existing JSON schema or client contracts.

**Why:** Provides validation safety without changing serialized format or breaking consumers.

_Source: #6318 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9D","title":"Annotated[str, Validator] adds validation without breaking serialization","topic":null,"source_type":"plan","source_issue":6318,"source_repo":null,"created_at":"2026-05-03T04:07:42.495360+00:00","updated_at":"2026-05-03T04:07:42.495363+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Literal types provide compile-time validation for bounded fields

Model fields with known bounded values should use `Literal` types rather than bare `str`. Examples: `VisualEvidenceItem.status`, `Release.status`. Provides compile-time validation and IDE autocomplete, catching invalid values at construction rather than runtime.

**Why:** Type checking catches invalid values early instead of at runtime.

_Source: #6320 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9E","title":"Literal types provide compile-time validation for bounded fields","topic":null,"source_type":"plan","source_issue":6320,"source_repo":null,"created_at":"2026-05-03T04:07:42.495382+00:00","updated_at":"2026-05-03T04:07:42.495384+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Convert dict returns to typed Pydantic models

When callers use `.get()` on return values, convert return type from `list[dict[str, Any]]` to typed Pydantic model like `list[GitHubIssue]`. Eliminates fragile dict access and enables type checking. Update all callers together—avoid partial migrations.

**Why:** Typed models are more maintainable and type-safe than dict access.

_Source: #6322 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9F","title":"Convert dict returns to typed Pydantic models","topic":null,"source_type":"plan","source_issue":6322,"source_repo":null,"created_at":"2026-05-03T04:07:42.495396+00:00","updated_at":"2026-05-03T04:07:42.495397+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Empty string sentinel with Union type maintains type safety

To allow default empty string while maintaining type safety for valid values, use `FieldType | Literal[""]`. This pattern enables optional/unset states in strongly-typed fields without sacrificing validation of non-empty values.

**Why:** Provides a type-safe way to represent unset or empty states.

_Source: #6335 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9G","title":"Empty string sentinel with Union type maintains type safety","topic":null,"source_type":"plan","source_issue":6335,"source_repo":null,"created_at":"2026-05-03T04:07:42.495408+00:00","updated_at":"2026-05-03T04:07:42.495410+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## StrEnum fields serialize without data migration

StrEnum fields serialize to the same string values already persisted in storage (state.json, etc.). Converting bare `str` field to StrEnum is schema-additive and requires no migration per ADR-0021.

**Why:** Backward compatibility—existing stored values remain valid without conversion.

_Source: #6335 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9H","title":"StrEnum fields serialize without data migration","topic":null,"source_type":"plan","source_issue":6335,"source_repo":null,"created_at":"2026-05-03T04:07:42.495419+00:00","updated_at":"2026-05-03T04:07:42.495421+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Naming conventions are scoped to architectural layers

GitHub-issue pipeline layer uses `issue_number` convention; other domains (caching, memory scoring, review) intentionally keep `issue_id`. Don't over-generalize renames across modules—respect domain boundaries and only align naming where architectural layers actually overlap.

**Why:** Different layers have independent naming conventions; overgeneralizing renames causes confusion.

_Source: #6337 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9J","title":"Naming conventions are scoped to architectural layers","topic":null,"source_type":"plan","source_issue":6337,"source_repo":null,"created_at":"2026-05-03T04:07:42.495430+00:00","updated_at":"2026-05-03T04:07:42.495432+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## f-string output format decoupled from parameter naming

Directory path format `issue-{N}` comes from f-string template, not the parameter name. Renaming the parameter doesn't affect output format, making the rename purely cosmetic at the output level.

**Why:** Decouples internal parameter names from external API surfaces.

_Source: #6337 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9K","title":"f-string output format decoupled from parameter naming","topic":null,"source_type":"plan","source_issue":6337,"source_repo":null,"created_at":"2026-05-03T04:07:42.495445+00:00","updated_at":"2026-05-03T04:07:42.495448+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## FastAPI route registration order affects specificity matching

Routes are matched in registration order. Generic routes like `/{path:path}` (SPA catch-all) must register last or they shadow more specific routes. When decomposing monolithic handlers, document required registration order and verify catch-all placement.

**Why:** Incorrect order causes specific routes to become unreachable.

_Source: #6336 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9M","title":"FastAPI route registration order affects specificity matching","topic":null,"source_type":"plan","source_issue":6336,"source_repo":null,"created_at":"2026-05-03T04:07:42.495458+00:00","updated_at":"2026-05-03T04:07:42.495459+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Convert closure mutable state to class-based encapsulation

When extracting stateful closures (cache dicts, timestamp lists, file paths) into separate modules, convert them to a class encapsulating mutable state and providing methods. This replaces closure-scoped variables with instance state and makes cache invalidation explicit and testable.

**Why:** Classes are more testable and maintainable than closures for stateful logic.

_Source: #6336 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9N","title":"Convert closure mutable state to class-based encapsulation","topic":null,"source_type":"plan","source_issue":6336,"source_repo":null,"created_at":"2026-05-03T04:07:42.495469+00:00","updated_at":"2026-05-03T04:07:42.495471+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Endpoint path preservation enables test reuse across refactors

When refactoring monolithic route handlers into sub-modules, if endpoint paths remain unchanged, existing test files need no modification—they match endpoints by HTTP path, not internal function structure. This enables high-confidence refactoring with zero test churn.

**Why:** Test reuse without churn reduces refactoring risk.

_Source: #6336 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9P","title":"Endpoint path preservation enables test reuse across refactors","topic":null,"source_type":"plan","source_issue":6336,"source_repo":null,"created_at":"2026-05-03T04:07:42.495482+00:00","updated_at":"2026-05-03T04:07:42.495484+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Pydantic Field() accepts module-level constants safely

Pydantic `Field(le=...)`, `Field(default=...)`, and `Field(ge=...)` accept plain int constants identically to literals. When extracting magic numbers into module-level constants for config classes, substitution is type-correct and requires no special handling.

**Why:** Constants are first-class in Pydantic Field validators.

_Source: #6341 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9Q","title":"Pydantic Field() accepts module-level constants safely","topic":null,"source_type":"plan","source_issue":6341,"source_repo":null,"created_at":"2026-05-03T04:07:42.495494+00:00","updated_at":"2026-05-03T04:07:42.495496+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Path prefix pattern handles root and nested objects correctly

When building dotted paths for nested objects, use `f"{path_prefix}.{key}" if path_prefix else key` to handle both root-level (`key`) and nested (`parent.key`) cases. This avoids leading dots and false positives in path matching.

**Why:** Incorrect handling creates invalid paths like `.key` for root objects.

_Source: #6352 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9R","title":"Path prefix pattern handles root and nested objects correctly","topic":null,"source_type":"plan","source_issue":6352,"source_repo":null,"created_at":"2026-05-03T04:07:42.495505+00:00","updated_at":"2026-05-03T04:07:42.495507+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Accept typed enums at method signatures, call .value internally

Helper methods should accept typed enums (`ReviewerStatus`, `ReviewVerdict`) at the signature level for caller type safety, then call `.value` internally when building string-keyed payloads. This improves type checking at call sites without forcing callers to extract enum values manually.

**Why:** Provides type safety to callers while allowing internal string-based representations.

_Source: #6351 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9S","title":"Accept typed enums at method signatures, call .value internally","topic":null,"source_type":"plan","source_issue":6351,"source_repo":null,"created_at":"2026-05-03T04:07:42.495516+00:00","updated_at":"2026-05-03T04:07:42.495518+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Parametrized validation tests isolate new validators

Test annotated types by extending existing validation test classes with parametrized tests covering malformed inputs (rejection) and valid inputs (acceptance). This pattern isolates validation logic testing and reuses test infrastructure for new validators across multiple models.

**Why:** Isolation and reuse make validation testing systematic and maintainable.

_Source: #6318 (plan)_


```json:entry
{"id":"01KQP0AJ4Z2MY1EXMWW9BTXN9T","title":"Parametrized validation tests isolate new validators","topic":null,"source_type":"plan","source_issue":6318,"source_repo":null,"created_at":"2026-05-03T04:07:42.495528+00:00","updated_at":"2026-05-03T04:07:42.495529+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
