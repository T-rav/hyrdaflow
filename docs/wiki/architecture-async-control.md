# Architecture Async Control

## Async Patterns: Wrappers, Context Managers, Callbacks, and Resource Lifecycle



When adding async support to sync I/O code, keep all sync methods unchanged and add a-prefixed async wrappers that delegate to sync methods via asyncio.to_thread(). This pattern (established in events.py) centralizes blocking-operation wrapping and preserves backward compatibility—existing sync callers continue unchanged while new async callers gradually migrate. Implement async context managers by adding `__aenter__` (return self), `__aexit__` (call close()), and `_closed: bool` flag in `__init__`. This pattern (established in DockerRunner) ensures clean resource shutdown semantics when wrapping clients that need guaranteed cleanup. When extracting async helpers, shared resources (like background tasks) may be awaited on the happy path but must be cancelled in the coordinator's error handler. Design the helper to handle its portion cleanly; keep lifecycle cleanup in the coordinator's `finally` block to ensure it runs regardless of how the helper exits. For done callbacks, follow the events.py pattern of defining module-level callback functions (e.g., _log_task_failure) rather than methods. This keeps callback logic portable, testable in isolation, and consistent across the codebase. Document expected signature and side effects clearly. See also: Orchestrator/Sequencer Design for coordinating async stages.

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WB","title":"Async Patterns: Wrappers, Context Managers, Callbacks, and Resource Lifecycle","content":"When adding async support to sync I/O code, keep all sync methods unchanged and add a-prefixed async wrappers that delegate to sync methods via asyncio.to_thread(). This pattern (established in events.py) centralizes blocking-operation wrapping and preserves backward compatibility—existing sync callers continue unchanged while new async callers gradually migrate. Implement async context managers by adding `__aenter__` (return self), `__aexit__` (call close()), and `_closed: bool` flag in `__init__`. This pattern (established in DockerRunner) ensures clean resource shutdown semantics when wrapping clients that need guaranteed cleanup. When extracting async helpers, shared resources (like background tasks) may be awaited on the happy path but must be cancelled in the coordinator's error handler. Design the helper to handle its portion cleanly; keep lifecycle cleanup in the coordinator's `finally` block to ensure it runs regardless of how the helper exits. For done callbacks, follow the events.py pattern of defining module-level callback functions (e.g., _log_task_failure) rather than methods. This keeps callback logic portable, testable in isolation, and consistent across the codebase. Document expected signature and side effects clearly. See also: Orchestrator/Sequencer Design for coordinating async stages.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.852290+00:00","updated_at":"2026-04-10T03:41:18.852298+00:00","valid_from":"2026-04-10T03:41:18.852290+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Background Loops and Skill Infrastructure: Audit Patterns and Wiring



Background loops (BaseBackgroundLoop subclasses) follow a standard pattern established by CodeGroomingLoop: (1) _run_audit() invokes a slash command; (2) parse severity-headed output into findings; (3) deduplicate via DedupStore per loop type (e.g., architecture_audit_dedup.json, test_audit_dedup.json); (4) file GitHub issues for Critical/High findings. Discovery via class definition pattern (BaseBackgroundLoop subclass with worker_name kwarg). Wiring requires 5 synchronized locations: config (interval + env override), service_registry (instantiation), orchestrator (bg_loop_registry dict), dashboard UI (_INTERVAL_BOUNDS and BACKGROUND_WORKERS), and constants.js. Omitting any location causes incomplete registration. Test discovery via test_loop_wiring_completeness.py. Skip sets track intentional deviations. Distinguish from per-PR skills: per-PR skills (architecture_compliance.py, test_quality.py) are lightweight single-prompt diff reviews focused on clear violations. Background loops invoke full multi-agent slash commands. Phase-filtered skill injection separates via registry (TOOL_PHASE_MAP data), injection (base runner coordination), execution unchanged. Tool presentation to LLM is filtered by phase but execution remains unchanged. Skills in multiple backends handled via marker-based checks (substring matching for '## Output') rather than exact structure enforcement. Two-file consolidation: Pydantic model definition for structure validation and dynamic JSONL writing for persistence must stay synchronized. Operator review gates dynamic skills due to prompt injection risk. See also: Layer Architecture for placement, Dynamic Discovery for command discovery.

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VW","title":"Background Loops and Skill Infrastructure: Audit Patterns and Wiring","content":"Background loops (BaseBackgroundLoop subclasses) follow a standard pattern established by CodeGroomingLoop: (1) _run_audit() invokes a slash command; (2) parse severity-headed output into findings; (3) deduplicate via DedupStore per loop type (e.g., architecture_audit_dedup.json, test_audit_dedup.json); (4) file GitHub issues for Critical/High findings. Discovery via class definition pattern (BaseBackgroundLoop subclass with worker_name kwarg). Wiring requires 5 synchronized locations: config (interval + env override), service_registry (instantiation), orchestrator (bg_loop_registry dict), dashboard UI (_INTERVAL_BOUNDS and BACKGROUND_WORKERS), and constants.js. Omitting any location causes incomplete registration. Test discovery via test_loop_wiring_completeness.py. Skip sets track intentional deviations. Distinguish from per-PR skills: per-PR skills (architecture_compliance.py, test_quality.py) are lightweight single-prompt diff reviews focused on clear violations. Background loops invoke full multi-agent slash commands. Phase-filtered skill injection separates via registry (TOOL_PHASE_MAP data), injection (base runner coordination), execution unchanged. Tool presentation to LLM is filtered by phase but execution remains unchanged. Skills in multiple backends handled via marker-based checks (substring matching for '## Output') rather than exact structure enforcement. Two-file consolidation: Pydantic model definition for structure validation and dynamic JSONL writing for persistence must stay synchronized. Operator review gates dynamic skills due to prompt injection risk. See also: Layer Architecture for placement, Dynamic Discovery for command discovery.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849543+00:00","updated_at":"2026-04-10T03:41:18.849544+00:00","valid_from":"2026-04-10T03:41:18.849543+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Label-Based Async Loop Routing via GitHub Labels



The system routes work through distinct concurrent async polling loops via GitHub issue labels (hydraflow-plan, hydraflow-discover, hydraflow-shape, etc.). Each loop: fetches issues with its label, processes them, swaps the label to route to the next phase. This pattern avoids persistent state management by leveraging GitHub as the queue and label transitions as the state machine. Event types (triage_routed, discover_complete, etc.) publish to EventLog and trigger state transitions. Source fields in events (discover, shape, plan) establish cross-references for worker creation and transcript routing. New event types require multi-layer synchronization: reducer event handlers (worker creation), EVENT_TO_STAGE mapping, SOURCE_TO_STAGE routing, and transcript routing logic. See also: Orchestrator/Sequencer Design for coordination patterns, Layer Architecture for event handling placement.

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VX","title":"Label-Based Async Loop Routing via GitHub Labels","content":"The system routes work through distinct concurrent async polling loops via GitHub issue labels (hydraflow-plan, hydraflow-discover, hydraflow-shape, etc.). Each loop: fetches issues with its label, processes them, swaps the label to route to the next phase. This pattern avoids persistent state management by leveraging GitHub as the queue and label transitions as the state machine. Event types (triage_routed, discover_complete, etc.) publish to EventLog and trigger state transitions. Source fields in events (discover, shape, plan) establish cross-references for worker creation and transcript routing. New event types require multi-layer synchronization: reducer event handlers (worker creation), EVENT_TO_STAGE mapping, SOURCE_TO_STAGE routing, and transcript routing logic. See also: Orchestrator/Sequencer Design for coordination patterns, Layer Architecture for event handling placement.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849547+00:00","updated_at":"2026-04-10T03:41:18.849548+00:00","valid_from":"2026-04-10T03:41:18.849547+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Idempotency Guards Prevent Redundant Side Effects



Add idempotency guards by checking outcome state at handler entry: `if state.get_outcome(issue_number) == MERGED: return`. This prevents redundant side effects (label swaps, counter increments, hook re-execution) from race conditions or retries. Log at info level when guard triggers for observability. Test three cases: (1) outcome already exists—side effects don't execute, (2) no prior outcome—normal flow, (3) non-MERGED outcome—normal flow. Use test helper pattern: `_setup_*()` method returning setup object with `.call()` method for test invocation. This pattern ensures idempotent handlers don't over-suppress valid operations. See also: Pre-Flight Validation for related validation patterns, State Persistence for outcome storage.

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VY","title":"Idempotency Guards Prevent Redundant Side Effects","content":"Add idempotency guards by checking outcome state at handler entry: `if state.get_outcome(issue_number) == MERGED: return`. This prevents redundant side effects (label swaps, counter increments, hook re-execution) from race conditions or retries. Log at info level when guard triggers for observability. Test three cases: (1) outcome already exists—side effects don't execute, (2) no prior outcome—normal flow, (3) non-MERGED outcome—normal flow. Use test helper pattern: `_setup_*()` method returning setup object with `.call()` method for test invocation. This pattern ensures idempotent handlers don't over-suppress valid operations. See also: Pre-Flight Validation for related validation patterns, State Persistence for outcome storage.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849551+00:00","updated_at":"2026-04-10T03:41:18.849552+00:00","valid_from":"2026-04-10T03:41:18.849551+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Clarity Score Routing: Fast Path vs Multi-Stage Maturation



The discovery phase routes issues in two tracks based on clarity_score: (1) clarity_score >= 7: skip Discover and Shape, go directly from Triage to Plan (fast path); (2) clarity_score < 7: route through Discover → Shape pipeline for multi-turn maturation (slow path). Three-stage pipeline design: Discover gathers product research context, Shape runs multi-turn design conversation and presents options for human selection, Plan begins after direction is chosen. This staged approach separates research, synthesis, and planning concerns with human decision points between stages.

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0VZ","title":"Clarity Score Routing: Fast Path vs Multi-Stage Maturation","content":"The discovery phase routes issues in two tracks based on clarity_score: (1) clarity_score >= 7: skip Discover and Shape, go directly from Triage to Plan (fast path); (2) clarity_score < 7: route through Discover → Shape pipeline for multi-turn maturation (slow path). Three-stage pipeline design: Discover gathers product research context, Shape runs multi-turn design conversation and presents options for human selection, Plan begins after direction is chosen. This staged approach separates research, synthesis, and planning concerns with human decision points between stages.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.849555+00:00","updated_at":"2026-04-10T03:41:18.849557+00:00","valid_from":"2026-04-10T03:41:18.849555+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Side Effect Consumption Pattern for Context Threading



Runners capture mutable side effects (e.g., `_last_recalled_items`, `_last_context_stats`) that must be explicitly consumed via getter methods after execution and cleared at method entry. This pattern prevents item leakage when runner instances are reused concurrently across issues. Pattern: (1) initialize side-effect variable in __init__ or at method entry; (2) populate during execution; (3) expose via `_consume_*()` method returning the value; (4) clear state after consumption in caller. Phases consume runner outputs, convert to domain models, and persist. This separates data production (runners) from I/O (phases) while threading context between stages via explicit consumption. See also: Functional Design for pure data threading, State Persistence for persistence patterns.

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0WD","title":"Side Effect Consumption Pattern for Context Threading","content":"Runners capture mutable side effects (e.g., `_last_recalled_items`, `_last_context_stats`) that must be explicitly consumed via getter methods after execution and cleared at method entry. This pattern prevents item leakage when runner instances are reused concurrently across issues. Pattern: (1) initialize side-effect variable in __init__ or at method entry; (2) populate during execution; (3) expose via `_consume_*()` method returning the value; (4) clear state after consumption in caller. Phases consume runner outputs, convert to domain models, and persist. This separates data production (runners) from I/O (phases) while threading context between stages via explicit consumption. See also: Functional Design for pure data threading, State Persistence for persistence patterns.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-10T03:41:18.852318+00:00","updated_at":"2026-04-10T03:41:18.852320+00:00","valid_from":"2026-04-10T03:41:18.852318+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Callback Construction Order: State → Snapshot → Router → Tracker



`_publish_queue_update_nowait` callback invokes `self._snapshot.get_queue_stats()`. Sub-components are constructed in order of dependency: state dicts first, then snapshot (used by publish_fn), then router and tracker (which receive publish_fn as a callback). Reordering breaks with AttributeError.

_Source: #6327 (plan)_

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X6","title":"Callback Construction Order: State → Snapshot → Router → Tracker","content":"`_publish_queue_update_nowait` callback invokes `self._snapshot.get_queue_stats()`. Sub-components are constructed in order of dependency: state dicts first, then snapshot (used by publish_fn), then router and tracker (which receive publish_fn as a callback). Reordering breaks with AttributeError.","topic":null,"source_type":"plan","source_issue":6327,"source_repo":null,"created_at":"2026-04-10T05:07:55.384592+00:00","updated_at":"2026-04-10T05:07:55.384593+00:00","valid_from":"2026-04-10T05:07:55.384592+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Use callbacks to decouple isolated components from orchestrator state



CreditPauseManager accepts `cancel_fn` and `resume_fn` callbacks instead of directly accessing loop task dicts. This avoids circular dependencies between manager and supervisor while allowing the manager to trigger orchestration actions (pause all loops, recreate them on resume). Apply this pattern whenever an extracted component needs to coordinate with the orchestration layer.

_Source: #6323 (plan)_

```json:entry
{"id":"01KQ11A4G7XE7SDHTKBKF7S0X0","title":"Use callbacks to decouple isolated components from orchestrator state","content":"CreditPauseManager accepts `cancel_fn` and `resume_fn` callbacks instead of directly accessing loop task dicts. This avoids circular dependencies between manager and supervisor while allowing the manager to trigger orchestration actions (pause all loops, recreate them on resume). Apply this pattern whenever an extracted component needs to coordinate with the orchestration layer.","topic":null,"source_type":"plan","source_issue":6323,"source_repo":null,"created_at":"2026-04-10T04:47:03.630696+00:00","updated_at":"2026-04-10T04:47:03.630699+00:00","valid_from":"2026-04-10T04:47:03.630696+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Return Value Threading in Orchestrator Pattern



When extracting helpers from a large method, extracted helpers should return values needed by downstream logic. The orchestrator captures these returns and threads them to consuming functions (e.g., metrics collection). This maintains clean value flow without side effects.

_Source: #6355 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPX","title":"Return Value Threading in Orchestrator Pattern","content":"When extracting helpers from a large method, extracted helpers should return values needed by downstream logic. The orchestrator captures these returns and threads them to consuming functions (e.g., metrics collection). This maintains clean value flow without side effects.","topic":null,"source_type":"plan","source_issue":6355,"source_repo":null,"created_at":"2026-04-10T07:14:58.678259+00:00","updated_at":"2026-04-10T07:14:58.678259+00:00","valid_from":"2026-04-10T07:14:58.678259+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Config tuples enable clean parameterized loops



Replace copy-paste blocks with a list-of-tuples configuration like `[(Bank.TRIBAL, "learnings", "memory"), ...]` where each tuple drives one loop iteration. Each position in the tuple holds enum value, display label, and dict key. This pattern scales to N similar blocks and makes the parameterization explicit and maintainable.

_Source: #6350 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQPQ","title":"Config tuples enable clean parameterized loops","content":"Replace copy-paste blocks with a list-of-tuples configuration like `[(Bank.TRIBAL, \"learnings\", \"memory\"), ...]` where each tuple drives one loop iteration. Each position in the tuple holds enum value, display label, and dict key. This pattern scales to N similar blocks and makes the parameterization explicit and maintainable.","topic":null,"source_type":"plan","source_issue":6350,"source_repo":null,"created_at":"2026-04-10T06:55:39.084060+00:00","updated_at":"2026-04-10T06:55:39.084061+00:00","valid_from":"2026-04-10T06:55:39.084060+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Polling loops must sleep when service disabled



Polling loops that run against a service should always check a boolean flag (e.g., _pipeline_enabled) and sleep when disabled. This prevents tight loops that attempt operations against uninitialized resources. See _polling_loop (line 940) pattern.

_Source: #6360 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ2","title":"Polling loops must sleep when service disabled","content":"Polling loops that run against a service should always check a boolean flag (e.g., _pipeline_enabled) and sleep when disabled. This prevents tight loops that attempt operations against uninitialized resources. See _polling_loop (line 940) pattern.","topic":null,"source_type":"plan","source_issue":6360,"source_repo":null,"created_at":"2026-04-10T07:37:26.758846+00:00","updated_at":"2026-04-10T07:37:26.758853+00:00","valid_from":"2026-04-10T07:37:26.758846+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Context manager protocol for async resource pooling



Add `__aenter__`/`__aexit__` to classes wrapping `httpx.AsyncClient`, delegating `__aexit__` to an existing `close()` method. Follow the exact pattern from `DockerRunner` (src/docker_runner.py:357-361) for type-safe implementation. This enables `async with` syntax and proper cleanup.

_Source: #6362 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ3","title":"Context manager protocol for async resource pooling","content":"Add `__aenter__`/`__aexit__` to classes wrapping `httpx.AsyncClient`, delegating `__aexit__` to an existing `close()` method. Follow the exact pattern from `DockerRunner` (src/docker_runner.py:357-361) for type-safe implementation. This enables `async with` syntax and proper cleanup.","topic":null,"source_type":"plan","source_issue":6362,"source_repo":null,"created_at":"2026-04-10T07:44:23.400349+00:00","updated_at":"2026-04-10T07:44:23.400389+00:00","valid_from":"2026-04-10T07:44:23.400349+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## httpx.AsyncClient.aclose() is idempotent and safe



httpx clients handle multiple `aclose()` calls gracefully (no-op on already-closed). Safe for multiple cleanup paths (e.g., orchestrator and ServiceRegistry both closing hindsight). Eliminates need for guard flags or state tracking.

_Source: #6362 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ4","title":"httpx.AsyncClient.aclose() is idempotent and safe","content":"httpx clients handle multiple `aclose()` calls gracefully (no-op on already-closed). Safe for multiple cleanup paths (e.g., orchestrator and ServiceRegistry both closing hindsight). Eliminates need for guard flags or state tracking.","topic":null,"source_type":"plan","source_issue":6362,"source_repo":null,"created_at":"2026-04-10T07:44:23.400455+00:00","updated_at":"2026-04-10T07:44:23.400460+00:00","valid_from":"2026-04-10T07:44:23.400455+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Service composition root needs async cleanup method



ServiceRegistry (composition root) should have an `async def aclose()` method that closes owned resources like `self.hindsight`. Keep it as the first method on the dataclass. Enables caller to clean up composition root in one call.

_Source: #6362 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ7","title":"Service composition root needs async cleanup method","content":"ServiceRegistry (composition root) should have an `async def aclose()` method that closes owned resources like `self.hindsight`. Keep it as the first method on the dataclass. Enables caller to clean up composition root in one call.","topic":null,"source_type":"plan","source_issue":6362,"source_repo":null,"created_at":"2026-04-10T07:44:23.400484+00:00","updated_at":"2026-04-10T07:44:23.400487+00:00","valid_from":"2026-04-10T07:44:23.400484+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Sentry integration: ERROR+ only triggers alerts



LoggingIntegration(event_level=logging.ERROR) in server.py means only ERROR and above are sent to Sentry. WARNING-level records bypass Sentry entirely. Use this configuration pattern to prevent false-positive alerts from transient/handled errors while preserving them in structured logs.

_Source: #6359 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ0","title":"Sentry integration: ERROR+ only triggers alerts","content":"LoggingIntegration(event_level=logging.ERROR) in server.py means only ERROR and above are sent to Sentry. WARNING-level records bypass Sentry entirely. Use this configuration pattern to prevent false-positive alerts from transient/handled errors while preserving them in structured logs.","topic":null,"source_type":"plan","source_issue":6359,"source_repo":null,"created_at":"2026-04-10T07:33:04.050924+00:00","updated_at":"2026-04-10T07:33:04.050927+00:00","valid_from":"2026-04-10T07:33:04.050924+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Fatal error hierarchy—propagate vs. suppress



AuthenticationError and CreditExhaustedError are fatal and must propagate; all other exceptions are suppressed. This pattern is canonical across the codebase (base_background_loop.py:141, orchestrator.py:948, phase_utils.py:392). Always catch fatal errors first in except clauses before a generic Exception fallback.

_Source: #6360 (plan)_

```json:entry
{"id":"01KQ11A4G8FNMGPZN5Y298JQQ1","title":"Fatal error hierarchy—propagate vs. suppress","content":"AuthenticationError and CreditExhaustedError are fatal and must propagate; all other exceptions are suppressed. This pattern is canonical across the codebase (base_background_loop.py:141, orchestrator.py:948, phase_utils.py:392). Always catch fatal errors first in except clauses before a generic Exception fallback.","topic":null,"source_type":"plan","source_issue":6360,"source_repo":null,"created_at":"2026-04-10T07:37:26.758732+00:00","updated_at":"2026-04-10T07:37:26.758748+00:00","valid_from":"2026-04-10T07:37:26.758732+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
