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


## Advisor pattern layers Opus reviewer over Sonnet executor on review surfaces

Each review surface (`pr_review`, `pre_merge_spec_check`, `adr_review`, `visual_gate`, `wiki_ingest`) can have up to three advisor roles wrapping the executor: a pre-flight planner (Opus subagent producing a `ReviewPlan`), a mid-flight consultant (executor's `Task`-tool call when stuck on a judgment call), and a post-verify gate (Opus subagent that can VETO the executor's verdict). Per-surface tiering in `src/review_advisor.py:_SURFACE_DEFAULTS` decides which roles fire per surface, so cheap surfaces stay cheap while load-bearing ones get the full advisory stack.

**Why:** Replaces the missing human merge gate (ADR-0042) with a layered second-pair-of-eyes that catches false negatives the executor misses. See ADR-0059.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26W","title":"Advisor pattern layers Opus reviewer over Sonnet executor on review surfaces","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-08T00:00:00.000000+00:00","updated_at":"2026-05-08T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Advisor uses Claude Code subagent dispatch — never the Anthropic SDK directly

All LLM invocations from HydraFlow runtime (advisor included) go through Claude Code's subagent dispatch — either subprocess agents (`runner` / `agent.py` patterns) or in-session `Task` tool with `model=` override. A direct `from anthropic import` in HydraFlow source is an architectural violation.

**Why:** Inherits Claude Code's auth, billing, transcripts, and observability boundary; avoids splitting the runtime's LLM lane.


```json:entry
{"id":"01KQP0XFBGMB32VFGNPV8GZ26X","title":"Advisor uses Claude Code subagent dispatch — never the Anthropic SDK directly","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-08T00:00:00.000000+00:00","updated_at":"2026-05-08T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## EpicMonitorLoop — stale epic detection and progress refresh

`EpicMonitorLoop` is a caretaker background loop (tick default 30 min, `HYDRAFLOW_EPIC_MONITOR_INTERVAL`) that detects stale epics and refreshes the in-memory progress cache. Each cycle it calls `EpicManager.check_stale_epics()` to flag epics with no recent child-issue movement, then `EpicManager.refresh_cache()` to pull current state for all tracked epics. The result dict exposes `stale_count` and `tracked_epics` for telemetry.

**When it runs:** Every `epic_monitor_interval` seconds (default 1800). Honoured by the ADR-0049 kill-switch gate at the top of `_do_work`; set `HYDRAFLOW_EPIC_MONITOR_ENABLED=false` for deploy-time disable.

**What it produces:** No label mutations or GitHub API writes — this loop is read-only. It updates the in-memory `EpicManager` cache that `EpicSweeperLoop` and the dashboard epic-progress route rely on.

**How it interacts:** Feeds the `EpicSweeperLoop` indirectly via the shared `EpicManager` cache. The sweeper decides whether to close; the monitor decides whether to mark stale. Separating them means stale detection can run twice as often as the heavier sweep operation.

**Gotchas:** `refresh_cache()` is async; forgetting the `await` returns an unawaited coroutine with no error, silently leaving the cache stale. The loop does not publish events — dashboard consumers poll `EpicManager.get_all_progress()` directly.


```json:entry
{"id":"01KRBX2N4QP7VW8FGH3J5YD0M1","title":"EpicMonitorLoop — stale epic detection and progress refresh","topic":null,"source_type":"compiled","source_issue":8764,"source_repo":null,"created_at":"2026-05-12T00:00:00.000000+00:00","updated_at":"2026-05-12T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```


## EpicSweeperLoop — auto-close completed epics

`EpicSweeperLoop` is a caretaker background loop (tick default 1 h, `HYDRAFLOW_EPIC_SWEEP_INTERVAL`) that auto-closes epics whose every sub-issue is resolved. Each cycle it fetches up to 50 open issues carrying the `epic_label`, collects sub-issue refs from two sources — formal `EpicState.child_issues` entries and `#NNN` checkbox refs parsed from the body — then verifies each ref is closed. If all are closed it checks all checkboxes, posts an auto-close comment, optionally adds the `fixed_label`, and closes the epic via `PRPort`.

**When it runs:** Every `epic_sweep_interval` seconds (600–86400 range; default 3600). ADR-0049 kill-switch gate at top of `_do_work`.

**What it produces:** GitHub API mutations — updated epic body, a comment, optional label addition, and issue close. Returns `{checked, swept, total_open_epics}` for telemetry.

**How it interacts:** Reads `StateTracker.get_epic_state()` for formal children and calls `parse_epic_sub_issues()` (from `epic.py`) for body refs. Uses `IssueFetcherPort.fetch_issue_by_number()` to verify each sub-issue state and `PRPort` for all mutations.

**Gotchas / limits:** The 50-issue fetch cap is intentional but logged as a warning when hit — if a repo has more than 50 open epics, some will be skipped each cycle. A stale body ref (sub-issue deleted from GitHub) causes the sweep to skip that epic with a warning rather than closing it. Remove stale refs from the body to unblock auto-close. Per-epic exceptions are caught and logged; one bad epic does not abort the whole sweep.


```json:entry
{"id":"01KRBX2N4QP7VW8FGH3J5YD0M2","title":"EpicSweeperLoop — auto-close completed epics","topic":null,"source_type":"compiled","source_issue":8765,"source_repo":null,"created_at":"2026-05-12T00:00:00.000000+00:00","updated_at":"2026-05-12T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```


## RetrospectiveLoop — durable-queue pattern analysis

`RetrospectiveLoop` is a background loop (tick default 30 min, `HYDRAFLOW_RETROSPECTIVE_INTERVAL`) that drains a durable JSONL work queue and runs three types of analysis: retrospective pattern detection (`RETRO_PATTERNS`), review insight pattern analysis with issue filing (`REVIEW_PATTERNS`), and stale improvement-proposal verification with HITL escalation (`VERIFY_PROPOSALS`). Producers — `PostMergeHandler` and `ReviewPhase` — append items; the loop acknowledges each item only after successful processing, so crashes leave items eligible for replay.

**When it runs:** Every `retrospective_interval` seconds (60–86400; default 1800). ADR-0049 kill-switch gate at top of `_do_work`. Respects `stop_event` between items to enable clean shutdown mid-batch.

**What it produces:** Filed GitHub issues (`[Review Insight]` and `[HITL]` labels), updated `ReviewInsightStore` state, and `RETROSPECTIVE_UPDATE` events on the `EventBus`. Returns `{processed, patterns_filed, stale_proposals}`.

**How it interacts:** Reads from `RetrospectiveQueue` (JSONL at `data_root`), writes to `ReviewInsightStore`, calls `PRPort.create_issue()` for new pattern issues, and publishes to `EventBus`. The `prs` dependency is optional — missing it suppresses issue filing with a warning rather than crashing.

**Gotchas:** Items that raise are retried on the next cycle (not acknowledged). This means pattern analysis for a failing item repeats; ensure `_handle_retro_patterns` is idempotent. `_handle_review_patterns` tracks proposed categories via `ReviewInsightStore.mark_category_proposed()` to avoid duplicate issue filing across cycles.


```json:entry
{"id":"01KRBX2N4QP7VW8FGH3J5YD0M3","title":"RetrospectiveLoop — durable-queue pattern analysis","topic":null,"source_type":"compiled","source_issue":8766,"source_repo":null,"created_at":"2026-05-12T00:00:00.000000+00:00","updated_at":"2026-05-12T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```


## RunsGCLoop — artifact retention enforcement

`RunsGCLoop` is a caretaker background loop (tick default 1 h, `HYDRAFLOW_RUNS_GC_INTERVAL`) that purges expired and oversized run artifacts produced by `RunRecorder`. Each cycle runs two passes: `purge_expired(artifact_retention_days)` removes artifacts older than the configured TTL (default 30 days, `HYDRAFLOW_ARTIFACT_RETENTION_DAYS`) and `purge_oversized(artifact_max_size_mb)` drops the oldest artifacts once total storage exceeds the size cap (default 500 MB, `HYDRAFLOW_ARTIFACT_MAX_SIZE_MB`).

**When it runs:** Every `runs_gc_interval` seconds (default 3600). ADR-0049 kill-switch gate at top of `_do_work`.

**What it produces:** File-system deletions only; no GitHub API calls. Returns `{expired_purged, oversized_purged, total_runs, total_mb, issues}` from `RunRecorder.get_storage_stats()`. Logs a single INFO line per cycle only when something was purged — quiet cycles produce no output.

**How it interacts:** Entirely mediated through `RunRecorder`; the loop itself holds no file handles. Other loops and runners write artifacts; this loop deletes the old ones. No event publishing.

**Gotchas:** The two purge passes are independent — a cycle can trigger both. Retention check runs first (time-based), then size cap (oldest-first). If the retention window is tight and the pipeline is busy, the size cap may also fire on the same cycle. Set `artifact_max_size_mb` conservatively for disk-constrained environments.


```json:entry
{"id":"01KRBX2N4QP7VW8FGH3J5YD0M4","title":"RunsGCLoop — artifact retention enforcement","topic":null,"source_type":"compiled","source_issue":8767,"source_repo":null,"created_at":"2026-05-12T00:00:00.000000+00:00","updated_at":"2026-05-12T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```


## SecurityPatchLoop — Dependabot alert triage and issue filing

`SecurityPatchLoop` is a caretaker background loop (tick default 1 h, `HYDRAFLOW_SECURITY_PATCH_INTERVAL`) that polls open Dependabot alerts and files a GitHub issue for each actionable, unduplicated vulnerability. An alert is actionable when it meets the configured severity threshold (`HYDRAFLOW_SECURITY_PATCH_SEVERITY_THRESHOLD`, default `high`; options: `critical`, `high`, `medium`, `low`) and has a `first_patched_version` available. `DedupStore` (persisted at `data_root/memory/security_patch_dedup.json`) prevents refiling the same alert number across cycles.

**When it runs:** Every `security_patch_interval` seconds (default 3600). ADR-0049 kill-switch gate. Skips all work in `dry_run` mode.

**What it produces:** GitHub issues with title `[Security] <summary> in <pkg>` and label `security`. Returns `{total_alerts, filed, skipped_dedup, skipped_unfixable, skipped_severity}`.

**How it interacts:** Calls `PRPort.get_dependabot_alerts(state="open")` and `PRPort.create_issue()`. No label-state-machine involvement — the filed issue is an unmanaged advisory, not a pipeline issue.

**Gotchas:** Severity ranking is explicit (`critical=0`, `high=1`, `medium=2`, `low=3`); unknown severity strings map to rank 99 (treated as below threshold). Dedup key is the Dependabot alert `number` field as a string — alerts without a `number` field are silently skipped. The `DedupStore` is reconciled-on-close; a crash mid-cycle may re-file an alert that was filed but not yet persisted.


```json:entry
{"id":"01KRBX2N4QP7VW8FGH3J5YD0M5","title":"SecurityPatchLoop — Dependabot alert triage and issue filing","topic":null,"source_type":"compiled","source_issue":8769,"source_repo":null,"created_at":"2026-05-12T00:00:00.000000+00:00","updated_at":"2026-05-12T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```


## HITLController and HITLPhase — correction lifecycle

`HITLController` is a thin orchestrator facade that owns the public correction API: `submit_correction(issue, text)`, `provide_human_input(issue, answer)`, `skip_issue(issue)`, and `get_status(issue)`. It delegates all stateful work to `HITLPhase`, which owns the full async correction lifecycle. On each `do_work()` tick it fetches open HITL issues via `IssueFetcher`, then calls `HITLPhase.process_corrections()` to drain the pending-corrections dict.

`HITLPhase.process_corrections()` snapshots and clears the pending dict atomically (preventing re-entrancy), then fans out one `asyncio.Task` per pending issue, bounded by `max_hitl_workers` semaphore. For each issue the phase: fetches the issue, looks up the recorded escalation cause and origin label, creates or reuses the worktree, swaps the pipeline label to `hitl_active_label`, runs `HITLRunner.run()` with the correction text, and then on success pushes the branch, returns the issue to its pre-escalation origin label (recorded in `StateTracker.get_hitl_origin()`), resets attempt counters, and auto-files a `[Memory]` lesson capturing the correction principle. On failure the issue label stays at `hitl_label` and a failure comment is posted for the operator to retry.

**Gotchas:** The origin label is consumed on success (`remove_hitl_origin`) — if the same issue re-escalates, the origin is gone and the issue stays on `hitl_label` rather than routing back to its stage. Keep worktrees on failure (`Preserve worktrees on HITL failure` in gotchas.md) for post-mortem inspection. `CreditExhaustedError`, `AuthenticationError`, and `MemoryError` are re-raised out of `_process_one_hitl` and bubble to the orchestrator.


```json:entry
{"id":"01KRBX2N4QP7VW8FGH3J5YD0M6","title":"HITLController and HITLPhase — correction lifecycle","topic":null,"source_type":"compiled","source_issue":8815,"source_repo":null,"created_at":"2026-05-12T00:00:00.000000+00:00","updated_at":"2026-05-12T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```
