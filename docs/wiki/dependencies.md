# Dependencies


## Use TYPE_CHECKING guards to break circular imports

Use `if TYPE_CHECKING:` blocks and PEP 563 (`from __future__ import annotations`) to defer imports that create cycles. Type hints are evaluated at type-check time, not runtime, allowing the import cycle to break.

**Why:** Circular imports at module level cause runtime failure; TYPE_CHECKING breaks the cycle without losing type information.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKD","title":"Use TYPE_CHECKING guards to break circular imports","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811703+00:00","updated_at":"2026-05-03T03:52:34.811721+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use callbacks instead of class refs for runtime dependencies

When classes have runtime circular references, inject callback functions instead of importing the class directly. Example: `get_progress=epic_reporter.get_progress` passed to constructor instead of importing Reporter class.

**Why:** Defers resolution until initialization, avoiding import-time cycles and making dependency direction explicit in function signatures.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKE","title":"Use callbacks instead of class refs for runtime dependencies","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811755+00:00","updated_at":"2026-05-03T03:52:34.811757+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Degrade gracefully when optional dependencies fail

Wrap optional dependency usage in broad exception handlers with safe defaults; never re-raise. Example: `except Exception: return safe_default # noqa: BLE001` for optional Hindsight recall or memory injection.

**Why:** Failures in optional features must not interrupt the pipeline; graceful degradation preserves core functionality when optional systems fail.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKF","title":"Degrade gracefully when optional dependencies fail","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811769+00:00","updated_at":"2026-05-03T03:52:34.811771+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use Protocol for optional dependency interfaces

Define Protocol interfaces instead of concrete imports for optional dependencies. Callers use duck typing without importing the optional module.

**Why:** Avoids hardcoding imports of optional packages into main code; allows swapping implementations and testing without the optional dependency installed.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKG","title":"Use Protocol for optional dependency interfaces","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811779+00:00","updated_at":"2026-05-03T03:52:34.811781+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Define shared artifacts once, import everywhere

Create artifacts (schemas, constants, routes) in a single module and import them everywhere they're used. Don't duplicate definitions across files.

**Why:** Prevents divergence where the same artifact has multiple versions in different parts of the codebase.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKH","title":"Define shared artifacts once, import everywhere","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811788+00:00","updated_at":"2026-05-03T03:52:34.811790+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Extract parallel-independent classes before dependent ones

When extracting coordinators from a god class, identify classes with zero cross-dependencies and extract them in phase 1; handle phase ordering for classes with dependencies. Map dependencies as a task graph to prevent parallel work from being blocked.

**Why:** Unblocks parallel extraction and makes dependency constraints explicit.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKJ","title":"Extract parallel-independent classes before dependent ones","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811799+00:00","updated_at":"2026-05-03T03:52:34.811801+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Verify extraction completeness in two stages

Stage 1: Check function signatures, return types, and other references in the source file. Stage 2: Grep the codebase for old names in imports, docs, comments, fixtures.

**Why:** Stage 1 catches unused local imports; Stage 2 catches references in tests, dynamic imports, and external modules that single-file grep misses.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKK","title":"Verify extraction completeness in two stages","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811810+00:00","updated_at":"2026-05-03T03:52:34.811813+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Register FastAPI catch-all routes last

Use `/{path:path}` route at the end of route registration. Register more specific routes first.

**Why:** Catch-all routes match anything; registering them first prevents more specific routes from ever being reached.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKM","title":"Register FastAPI catch-all routes last","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811822+00:00","updated_at":"2026-05-03T03:52:34.811824+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Embed schema_version in each JSON line

Include `schema_version` field in every JSON line for self-describing records. Example: `{"schema_version": 1, "field": "value"}`.

**Why:** Allows schema evolution without migration code; old records missing new fields deserialize safely via Pydantic defaults.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKN","title":"Embed schema_version in each JSON line","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811831+00:00","updated_at":"2026-05-03T03:52:34.811832+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use Pydantic defaults for backward-compatible schemas

Define default values in Pydantic models so records from earlier schema versions (missing new fields) deserialize without migration. Example: `new_field: str = 'default'`.

**Why:** Old JSON lacking new fields can load directly; no separate migration code needed.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKP","title":"Use Pydantic defaults for backward-compatible schemas","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811841+00:00","updated_at":"2026-05-03T03:52:34.811843+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Scan transitive dependencies when invalidating items

When invalidating a data item, recursively update all ancestors to point to final successors. Use depth limits to prevent infinite loops. Example: invalidate child → update parent → update grandparent, stop at depth limit.

**Why:** Prevents broken dependency chains in trees; loop limits protect against cycles.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKQ","title":"Scan transitive dependencies when invalidating items","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811850+00:00","updated_at":"2026-05-03T03:52:34.811852+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use atomic writes with rotate_backups for versioning

Use unconditional overwrite for small files; use atomic writes with rotation for larger ones to preserve history.

**Why:** Atomic writes prevent corruption on interruption; rotation provides natural versioning and recovery from corruption without separate backup logic.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKR","title":"Use atomic writes with rotate_backups for versioning","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811859+00:00","updated_at":"2026-05-03T03:52:34.811860+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use sha256(text)[:16] for synthetic API content IDs

When external APIs don't return content IDs, create synthetic ones using `sha256(text)[:16]`. Enables temporal tracking of content across API responses.

**Why:** Consistent hashing allows tracking whether the same content appears in different API calls or has changed.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKS","title":"Use sha256(text)[:16] for synthetic API content IDs","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811867+00:00","updated_at":"2026-05-03T03:52:34.811869+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Type signatures communicate breaking contract changes

Update function signatures to reflect stricter types (e.g., `phase: PipelineStage | Literal[""]`) before modifying callers. Existing calls with string literals continue working via StrEnum coercion; the signature is the integration point.

**Why:** Type signatures make contract changes visible to callers before implementation changes, enabling gradual adoption.

_Source: #6335 (review)_


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKT","title":"Type signatures communicate breaking contract changes","topic":null,"source_type":"review","source_issue":6335,"source_repo":null,"created_at":"2026-05-03T03:52:34.811876+00:00","updated_at":"2026-05-03T03:52:34.811877+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Never import optional deps at module level in tests

Always defer optional package imports to test method level, not file-top. Wrong: `from hindsight import Bank` at top; Right: `from hindsight import Bank` inside test method.

**Why:** Module-level imports run at collection time; missing optional packages fail the entire test file, hiding all tests from the report.


```json:entry
{"id":"01KQNZEVQVRHE57A588EWZXKKV","title":"Never import optional deps at module level in tests","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:52:34.811886+00:00","updated_at":"2026-05-03T03:52:34.811887+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
