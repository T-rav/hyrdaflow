# Architecture-Async-Control


## A-prefixed async wrappers delegate sync I/O to asyncio.to_thread()

Add async wrappers (e.g., `async def a_read()`) that delegate to sync methods via `asyncio.to_thread()`, keeping all sync methods unchanged. Pattern from events.py: sync callers continue unchanged; async callers migrate gradually.

**Why:** Centralizes blocking-operation wrapping and preserves backward compatibility without duplicating sync logic.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ264","title":"A-prefixed async wrappers delegate sync I/O to asyncio.to_thread()","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:18:02.224291+00:00","updated_at":"2026-05-03T04:18:02.224607+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Async context managers: add __aenter__, __aexit__, _closed flag

Implement `__aenter__` (return self), `__aexit__` (call close()), and `_closed: bool` flag in `__init__`. Pattern from DockerRunner (src/docker_runner.py:357–361). See also: Async cleanup—context manager protocol for httpx.AsyncClient.

**Why:** Ensures clean resource shutdown semantics when wrapping clients needing guaranteed cleanup; enables async with syntax.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ265","title":"Async context managers: add __aenter__, __aexit__, _closed flag","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:18:02.224676+00:00","updated_at":"2026-05-03T04:18:02.224678+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Async helper extraction: keep shared-resource cleanup in coordinator finally

Extracted async helpers handle their portion cleanly; keep lifecycle cleanup in the coordinator's `finally` block. Shared resources (background tasks) awaited on happy path but cancelled in coordinator's error handler.

**Why:** Ensures cleanup runs regardless of helper exit path; prevents leaked resources.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ266","title":"Async helper extraction: keep shared-resource cleanup in coordinator finally","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:18:02.224698+00:00","updated_at":"2026-05-03T04:18:02.224700+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Done callbacks: use module-level functions, not methods

Define callbacks as module-level functions (e.g., `_log_task_failure`) rather than methods. Pattern from events.py. Document expected signature and side effects clearly. See also: Async patterns—callback construction order and callbacks decouple components.

**Why:** Keeps callback logic portable, testable in isolation, and consistent across the codebase.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ267","title":"Done callbacks: use module-level functions, not methods","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:18:02.224714+00:00","updated_at":"2026-05-03T04:18:02.224716+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Label-based async loop routing via GitHub issue labels

Routes work through concurrent polling loops via labels (hydraflow-plan, hydraflow-discover, etc.). Each loop: fetch with label → process → swap label. Event types (triage_routed, discover_complete) publish to EventLog and trigger state transitions. Source fields establish cross-references.

**Why:** Avoids persistent state; leverages GitHub as queue and labels as state machine.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ268","title":"Label-based async loop routing via GitHub issue labels","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:18:02.224730+00:00","updated_at":"2026-05-03T04:18:02.224732+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Clarity score routing: fast path vs multi-stage maturation pipeline

clarity_score ≥ 7: skip Discover and Shape, go directly Triage → Plan. clarity_score < 7: route through Discover → Shape → Plan. Three-stage pipeline: Discover (research), Shape (design + selection), Plan (execution).

**Why:** Separates research, synthesis, and planning concerns with human decision points between stages.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ269","title":"Clarity score routing: fast path vs multi-stage maturation pipeline","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:18:02.224744+00:00","updated_at":"2026-05-03T04:18:02.224745+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Side-effect consumption pattern: initialize, populate, expose, clear

Runners capture side effects (e.g., `_last_recalled_items`) initialized at method entry, populated during execution, exposed via `_consume_*()` getter, cleared after consumption. Phases convert to domain models and persist.

**Why:** Prevents item leakage when runner instances reused concurrently; threads context between stages via explicit consumption.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26A","title":"Side-effect consumption pattern: initialize, populate, expose, clear","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:18:02.224755+00:00","updated_at":"2026-05-03T04:18:02.224756+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Callback construction order: state → snapshot → router → tracker

`_publish_queue_update_nowait` invokes `self._snapshot.get_queue_stats()`. Build order: state dicts, snapshot (used by callback), router and tracker (receive callback). See also: Async patterns—done callbacks and callbacks decouple components.

**Why:** Reordering breaks with AttributeError; dependencies must be satisfied top-down.

_Source: #6327 (plan)_


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26B","title":"Callback construction order: state → snapshot → router → tracker","topic":null,"source_type":"plan","source_issue":6327,"source_repo":null,"created_at":"2026-05-03T04:18:02.224786+00:00","updated_at":"2026-05-03T04:18:02.224788+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Callbacks decouple isolated components from orchestrator state

Pass `cancel_fn` and `resume_fn` callbacks instead of direct state access. Example: CreditPauseManager accepts callbacks to trigger pause/resume.

**Why:** Avoids circular dependencies while allowing extracted components to coordinate with orchestration layer.

_Source: #6323 (plan)_


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26C","title":"Callbacks decouple isolated components from orchestrator state","topic":null,"source_type":"plan","source_issue":6323,"source_repo":null,"created_at":"2026-05-03T04:18:02.224803+00:00","updated_at":"2026-05-03T04:18:02.224804+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Orchestrator pattern: extracted helpers return values for threading

Extracted helpers return values needed by downstream logic. Orchestrator captures these and threads them to consuming functions (e.g., metrics collection).

**Why:** Maintains clean value flow without side effects.

_Source: #6355 (plan)_


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26D","title":"Orchestrator pattern: extracted helpers return values for threading","topic":null,"source_type":"plan","source_issue":6355,"source_repo":null,"created_at":"2026-05-03T04:18:02.224815+00:00","updated_at":"2026-05-03T04:18:02.224817+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Config tuples replace copy-paste blocks with parameterized loops

Replace repeated similar blocks with list-of-tuples: `[(Bank.TRIBAL, "learnings", "memory"), ...]`. Each position holds enum, label, dict key.

**Why:** Scales to N similar blocks; makes parameterization explicit and maintainable.

_Source: #6350 (plan)_


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26E","title":"Config tuples replace copy-paste blocks with parameterized loops","topic":null,"source_type":"plan","source_issue":6350,"source_repo":null,"created_at":"2026-05-03T04:18:02.224826+00:00","updated_at":"2026-05-03T04:18:02.224828+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Polling loops must sleep when service disabled

Check boolean flag (e.g., `_pipeline_enabled`) and sleep when disabled. Pattern: _polling_loop (line 940).

**Why:** Prevents tight loops attempting operations against uninitialized resources.

_Source: #6360 (plan)_


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26F","title":"Polling loops must sleep when service disabled","topic":null,"source_type":"plan","source_issue":6360,"source_repo":null,"created_at":"2026-05-03T04:18:02.224837+00:00","updated_at":"2026-05-03T04:18:02.224839+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Context manager protocol: wrap httpx.AsyncClient with __aenter__/__aexit__

Add `__aenter__`/`__aexit__` to classes wrapping `httpx.AsyncClient`, delegating `__aexit__` to existing `close()`. Follow pattern from DockerRunner (src/docker_runner.py:357–361). See also: Async cleanup—general context manager pattern and httpx.AsyncClient.aclose() idempotency.

**Why:** Enables async with syntax and proper cleanup; type-safe implementation.

_Source: #6362 (plan)_


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26G","title":"Context manager protocol: wrap httpx.AsyncClient with __aenter__/__aexit__","topic":null,"source_type":"plan","source_issue":6362,"source_repo":null,"created_at":"2026-05-03T04:18:02.224847+00:00","updated_at":"2026-05-03T04:18:02.224849+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## httpx.AsyncClient.aclose() is idempotent and safe for multiple calls

Multiple `aclose()` calls on httpx clients are no-ops on already-closed clients. Safe for multiple cleanup paths (e.g., orchestrator and ServiceRegistry both closing).

**Why:** Eliminates need for guard flags or state tracking.

_Source: #6362 (plan)_


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26H","title":"httpx.AsyncClient.aclose() is idempotent and safe for multiple calls","topic":null,"source_type":"plan","source_issue":6362,"source_repo":null,"created_at":"2026-05-03T04:18:02.224860+00:00","updated_at":"2026-05-03T04:18:02.224862+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## ServiceRegistry (composition root) needs async aclose() method

Add `async def aclose()` to ServiceRegistry to close owned resources (e.g., `self.hindsight`). Place as first method on dataclass. See also: Async cleanup—httpx.AsyncClient context manager protocol.

**Why:** Enables caller to clean up composition root in one call.

_Source: #6362 (plan)_


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26J","title":"ServiceRegistry (composition root) needs async aclose() method","topic":null,"source_type":"plan","source_issue":6362,"source_repo":null,"created_at":"2026-05-03T04:18:02.224871+00:00","updated_at":"2026-05-03T04:18:02.224876+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Sentry integration: ERROR+ only triggers alerts (WARNING bypasses)

Configure `LoggingIntegration(event_level=logging.ERROR)` in server.py. Only ERROR and above reach Sentry; WARNING records stay in structured logs only.

**Why:** Prevents false-positive alerts from transient/handled errors while preserving them in structured logs.

_Source: #6359 (plan)_


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26K","title":"Sentry integration: ERROR+ only triggers alerts (WARNING bypasses)","topic":null,"source_type":"plan","source_issue":6359,"source_repo":null,"created_at":"2026-05-03T04:18:02.224886+00:00","updated_at":"2026-05-03T04:18:02.224887+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Fatal error hierarchy: AuthenticationError and CreditExhaustedError propagate

Catch fatal errors first in except clauses: AuthenticationError, CreditExhaustedError propagate; all others suppressed. Pattern in base_background_loop.py:141, orchestrator.py:948, phase_utils.py:392.

**Why:** Preserves fatal errors while suppressing handled exceptions; canonical across codebase.

_Source: #6360 (plan)_


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26M","title":"Fatal error hierarchy: AuthenticationError and CreditExhaustedError propagate","topic":null,"source_type":"plan","source_issue":6360,"source_repo":null,"created_at":"2026-05-03T04:18:02.224898+00:00","updated_at":"2026-05-03T04:18:02.224900+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Background loops: five-step audit pattern

(1) _run_audit() invokes slash command; (2) parse severity-headed output into findings; (3) deduplicate via DedupStore (architecture_audit_dedup.json, test_audit_dedup.json); (4) file GitHub issues for Critical/High; (5) track via discovery. Pattern from CodeGroomingLoop. See also: Async patterns—background loop wiring.

**Why:** Establishes repeatable, discoverable audit infrastructure.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26N","title":"Background loops: five-step audit pattern","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:18:02.224909+00:00","updated_at":"2026-05-03T04:18:02.224911+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Background loop wiring: synchronize 5 locations

Wiring requires config (interval + env override), service_registry (instantiation), orchestrator (bg_loop_registry dict), dashboard UI (_INTERVAL_BOUNDS, BACKGROUND_WORKERS), constants.js. Test discovery via test_loop_wiring_completeness.py. See also: Async patterns—background loop five-step audit pattern.

**Why:** Prevents silent registration failures.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26P","title":"Background loop wiring: synchronize 5 locations","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:18:02.224919+00:00","updated_at":"2026-05-03T04:18:02.224921+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Background loops vs per-PR skills: distinct patterns

Per-PR skills (architecture_compliance.py, test_quality.py): lightweight single-prompt diff reviews focused on clear violations. Background loops: invoke full multi-agent slash commands for deeper analysis.

**Why:** Separates lightweight inline feedback from comprehensive polling audits.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26Q","title":"Background loops vs per-PR skills: distinct patterns","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:18:02.224930+00:00","updated_at":"2026-05-03T04:18:02.224932+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Phase-filtered skill injection: tool filtering only, execution unchanged

Tool presentation to LLM filtered by phase (TOOL_PHASE_MAP), but execution unchanged. Injection via base runner coordination.

**Why:** Reduces cognitive load on agent without altering runner behavior.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26R","title":"Phase-filtered skill injection: tool filtering only, execution unchanged","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:18:02.224941+00:00","updated_at":"2026-05-03T04:18:02.224942+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Multiple backend skills: use marker-based checks, not strict structure

Handle skills in multiple backends via substring matching for '## Output' rather than exact structure enforcement.

**Why:** Allows flexible backend variations without brittle parsing.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26S","title":"Multiple backend skills: use marker-based checks, not strict structure","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:18:02.224950+00:00","updated_at":"2026-05-03T04:18:02.224952+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Two-file consolidation: Pydantic model and JSONL persistence must sync

Pydantic model definition for structure validation and dynamic JSONL writing for persistence must stay synchronized.

**Why:** Schema drift causes deserialization failures and lost audit data.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26T","title":"Two-file consolidation: Pydantic model and JSONL persistence must sync","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:18:02.224961+00:00","updated_at":"2026-05-03T04:18:02.224963+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Operator review gates dynamic skills due to prompt injection risk

Dynamic skills (with user-supplied content) require operator review before deployment.

**Why:** Prevents prompt injection attacks via user-controlled input in skill definitions.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26V","title":"Operator review gates dynamic skills due to prompt injection risk","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T04:18:02.224970+00:00","updated_at":"2026-05-03T04:18:02.224972+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
