# Architecture-State-Persistence


## State Persistence: Atomic Writes and Backup Recovery

All critical file operations use atomic write patterns to prevent partial corruption on crash: write to temp file, fsync for durability, then os.replace() for atomic swap. Use centralized utilities: `file_util.atomic_write()` for entire file rewrites (e.g., JSONL rotations) and `file_util.append_jsonl()` for crash-safe appends with automatic mkdir, flush, and fsync. For JSONL rotation/trimming: read, filter, write atomically; acquire exclusive file lock (.{filename}.lock) for the entire read-filter-write cycle to prevent TOCTOU bugs. Cache JSONL parsing results with TTL patterns for HTTP handlers. StateTracker uses backup pattern: save .bak backup before overwriting; restore from backup if main file corrupts. Single-writer assumption (async orchestrator) eliminates need for write-ahead logging. Applies to WAL files, state snapshots, JSONL stores, and configuration.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VS","title":"State Persistence: Atomic Writes and Backup Recovery","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849528+00:00","updated_at":"2026-04-10T03:41:18.849529+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## In-Place Mutation Requirement for Shared Dicts

If any sub-component reassigns a dict (e.g., `self._queues = {}`) instead of mutating in-place (e.g., `self._queues[stage].clear()`), the shared reference breaks and mutations become invisible to other components. This is the central risk — all state mutations in extracted classes must be in-place, not reassignment.

_Source: #6327 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X5","title":"In-Place Mutation Requirement for Shared Dicts","topic":null,"source_type":"plan","source_issue":6327,"source_repo":null,"created_at":"2026-04-10T05:07:55.384588+00:00","updated_at":"2026-04-10T05:07:55.384589+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Immutable Scalars in Shared State Pattern

`_last_poll_ts` (a string) cannot be shared by reference like dicts — reassignment on the facade doesn't propagate to sub-components. Solution: snapshot's `get_queue_stats()` accepts `last_poll_ts` as a parameter; the facade passes `self._last_poll_ts` at call time. This pattern applies to any immutable scalar in shared state.

_Source: #6327 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X7","title":"Immutable Scalars in Shared State Pattern","topic":null,"source_type":"plan","source_issue":6327,"source_repo":null,"created_at":"2026-04-10T05:07:55.384597+00:00","updated_at":"2026-04-10T05:07:55.384598+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Feature Gates and Configuration-Driven Behavior

When a feature depends on unimplemented prerequisites, gate the entire feature behind a config flag (default False) rather than attempting runtime degradation. This isolates incomplete work, prevents confusing partial-state behavior, and makes the feature truly opt-in until dependencies land. Example: `post_acceptance_tracking_enabled` in config. Test both enabled and disabled paths separately. For optional allocations, add feature functionality via `get_allocation(label, fallback_cap)` method that returns config-defined caps when feature enabled, falling back to fallback_cap when no budget set. This ensures zero behavioral change when feature disabled and allows safe feature rollout without regressions. Individual section caps serve as `max_chars` overrides, preserving existing guardrails. Backward compatibility is preserved: old code paths continue unchanged when feature is disabled. See also: Optional Dependencies for runtime service handling.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W2","title":"Feature Gates and Configuration-Driven Behavior","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849567+00:00","updated_at":"2026-04-10T03:41:18.849568+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dataclass Design for Schema Evolution and Backward Compatibility

Use TypedDict with total=False or Pydantic dataclasses with optional fields for backward-compatible schema evolution. Missing fields handled gracefully with .get(key, default). Use frozen dataclasses (`@dataclass(frozen=True, slots=True)`) to bundle context parameters that won't change at runtime. Include optional fields with empty string defaults for fields not yet populated, preventing accidental mutation and making contracts explicit. Placeholder fields anticipate feature extension points: add fields for planned features even if data sources don't exist yet, defaulting to empty strings with docstring notes. Model fields should include optional metadata that can be populated opportunistically, avoiding breaking changes later. Ensure all fields have non-empty defaults if parametrized tests override individual fields. String annotations and `from __future__ import annotations` enable Literal and forward references without runtime overhead. For JSONL records, add new fields as optional with sensible defaults; existing consumers tolerate extra keys automatically. Legacy records without new fields remain valid via fallback logic.


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0W3","title":"Dataclass Design for Schema Evolution and Backward Compatibility","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849570+00:00","updated_at":"2026-04-10T03:41:18.849572+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Annotated[str, Validator] pattern for backward-compatible type narrowing

Use `Annotated[str, AfterValidator(...)]` to add runtime validation to string fields while maintaining serialization compatibility. This pattern serializes identically to bare `str` in JSON output, enabling strict validation at construction time without breaking existing JSON schema or client contracts. Useful for retrofitting validation onto existing fields across Pydantic models.

_Source: #6318 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WQ","title":"Annotated[str, Validator] pattern for backward-compatible type narrowing","topic":null,"source_type":"plan","source_issue":6318,"source_repo":null,"created_at":"2026-04-10T04:05:05.202950+00:00","updated_at":"2026-04-10T04:05:05.202964+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use Literal types for bounded enum-like fields

Model fields with known bounded values should use Literal types rather than bare str. The codebase establishes this pattern (VisualEvidenceItem.status, Release.status). This provides compile-time validation and IDE autocomplete, catching invalid values at construction rather than runtime.

_Source: #6320 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WS","title":"Use Literal types for bounded enum-like fields","topic":null,"source_type":"plan","source_issue":6320,"source_repo":null,"created_at":"2026-04-10T04:14:20.752849+00:00","updated_at":"2026-04-10T04:14:20.752855+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dict-to-Model Conversion Pattern for Type Safety

When callers use `.get()` on return values, convert the return type from `list[dict[str, Any]]` to a typed Pydantic model like `list[GitHubIssue]`. This eliminates fragile dict access and enables type checking. Update all callers together—avoid partial migrations where some code uses attributes and some uses `.get()`.

_Source: #6322 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WX","title":"Dict-to-Model Conversion Pattern for Type Safety","topic":null,"source_type":"plan","source_issue":6322,"source_repo":null,"created_at":"2026-04-10T04:31:05.960687+00:00","updated_at":"2026-04-10T04:31:05.960695+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Empty String Sentinel with Union Type Annotation

To allow a default empty string while maintaining type safety for valid values, use `FieldType | Literal[""]`. This pattern enables optional/unset states in strongly-typed fields without sacrificing validation of non-empty values.

_Source: #6335 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNQ","title":"Empty String Sentinel with Union Type Annotation","topic":null,"source_type":"plan","source_issue":6335,"source_repo":null,"created_at":"2026-04-10T05:43:58.108257+00:00","updated_at":"2026-04-10T05:43:58.108261+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## StrEnum Fields Serialize Without Migration

StrEnum fields serialize to the same string values already persisted in storage (state.json, etc.). Converting a bare `str` field to StrEnum is schema-additive and requires no data migration per ADR-0021 (persistence architecture).

_Source: #6335 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNR","title":"StrEnum Fields Serialize Without Migration","topic":null,"source_type":"plan","source_issue":6335,"source_repo":null,"created_at":"2026-04-10T05:43:58.108275+00:00","updated_at":"2026-04-10T05:43:58.108277+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Naming conventions are pipeline-layer scoped

The GitHub-issue pipeline layer uses `issue_number` naming convention, but other domains (caching, memory scoring, review) intentionally keep `issue_id`. Don't over-generalize renames across modules—respect domain boundaries and only align naming where architectural layers actually overlap.

_Source: #6337 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNS","title":"Naming conventions are pipeline-layer scoped","topic":null,"source_type":"plan","source_issue":6337,"source_repo":null,"created_at":"2026-04-10T05:49:11.253569+00:00","updated_at":"2026-04-10T05:49:11.253573+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## f-string output decoupled from parameter naming

Directory path format `issue-{N}` comes from f-string template, not the parameter name. Renaming the parameter doesn't affect directory structure, making the rename purely cosmetic at the output level.

_Source: #6337 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNT","title":"f-string output decoupled from parameter naming","topic":null,"source_type":"plan","source_issue":6337,"source_repo":null,"created_at":"2026-04-10T05:49:11.253590+00:00","updated_at":"2026-04-10T05:49:11.253591+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## FastAPI route registration order affects specificity matching

In FastAPI, routes are matched in registration order. Generic routes like `/{path:path}` (SPA catch-all) must be registered last or they shadow more specific routes. When decomposing monolithic route handlers into sub-modules, document the required registration order and verify catch-all placement during refactoring.

_Source: #6336 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNY","title":"FastAPI route registration order affects specificity matching","topic":null,"source_type":"plan","source_issue":6336,"source_repo":null,"created_at":"2026-04-10T05:57:03.732493+00:00","updated_at":"2026-04-10T05:57:03.732510+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Convert closure mutable state to class-based encapsulation

When extracting stateful closures (e.g., cache dicts, timestamp lists, file paths) into separate modules, convert them into a class that encapsulates mutable state and provides methods. This replaces closure-scoped variables with instance state and makes cache invalidation logic explicit and testable rather than implicit in helper functions.

_Source: #6336 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQNZ","title":"Convert closure mutable state to class-based encapsulation","topic":null,"source_type":"plan","source_issue":6336,"source_repo":null,"created_at":"2026-04-10T05:57:03.732527+00:00","updated_at":"2026-04-10T05:57:03.732530+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Endpoint path preservation enables test reuse across refactors

When refactoring monolithic route handlers into sub-modules, if endpoint paths remain unchanged, existing test files need no modification—they match endpoints by HTTP path, not by internal function structure. This allows high-confidence refactoring with zero test churn, since `make test` validates the entire endpoint surface area automatically.

_Source: #6336 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP0","title":"Endpoint path preservation enables test reuse across refactors","topic":null,"source_type":"plan","source_issue":6336,"source_repo":null,"created_at":"2026-04-10T05:57:03.732536+00:00","updated_at":"2026-04-10T05:57:03.732539+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Pydantic Field() accepts module-level int constants safely

Pydantic Field(le=...), Field(default=...), and Field(ge=...) accept plain int constants identically to literals. When extracting magic numbers into module-level constants for config classes, substitution is type-correct and requires no Pydantic-specific handling or adaptation.

_Source: #6341 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQP7","title":"Pydantic Field() accepts module-level int constants safely","topic":null,"source_type":"plan","source_issue":6341,"source_repo":null,"created_at":"2026-04-10T06:22:03.281124+00:00","updated_at":"2026-04-10T06:22:03.281131+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Path prefix pattern for hierarchical object keys

When building dotted paths for nested objects, use `f"{path_prefix}.{key}" if path_prefix else key` to correctly handle both root-level (`key`) and nested (`parent.key`) cases. This avoids leading dots and false positives in path matching.

_Source: #6352 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPS","title":"Path prefix pattern for hierarchical object keys","topic":null,"source_type":"plan","source_issue":6352,"source_repo":null,"created_at":"2026-04-10T07:02:55.409396+00:00","updated_at":"2026-04-10T07:02:55.409404+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Accept typed enums, call .value internally

Helper methods should accept typed enums (ReviewerStatus, ReviewVerdict) at the signature level for caller type safety, then call `.value` internally when building string-keyed payloads. This pattern improves type checking at call sites without forcing callers to extract enum values manually.

_Source: #6351 (plan)_


```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPR","title":"Accept typed enums, call .value internally","topic":null,"source_type":"plan","source_issue":6351,"source_repo":null,"created_at":"2026-04-10T06:58:24.321769+00:00","updated_at":"2026-04-10T06:58:24.321771+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Parametrized validation rejection tests follow annotated-type pattern

Test annotated types by extending existing validation test classes with parametrized tests covering malformed inputs (rejection) and valid inputs (acceptance). This pattern isolates validation logic testing and reuses test infrastructure for new validators across multiple models.

_Source: #6318 (plan)_


```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WR","title":"Parametrized validation rejection tests follow annotated-type pattern","topic":null,"source_type":"plan","source_issue":6318,"source_repo":null,"created_at":"2026-04-10T04:05:05.202985+00:00","updated_at":"2026-04-10T04:05:05.202986+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
