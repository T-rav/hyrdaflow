# Operational Audit Fix Issues

Batch file for `bd create --from-file`.

---

## Fix logger typo and adopt structured logging context injection

**Type:** bug
**Priority:** high
**Labels:** logging, observability

### Description

The operational audit identified two logging issues that should be fixed together:

1. **Logger naming typo** — `src/delta_verifier.py:10` uses `"hydra.delta_verifier"` instead of `"hydraflow.delta_verifier"`. Messages from this module don't appear under the hydraflow logger hierarchy.

2. **Structured logging underutilized** — `src/log.py:13-30` has a JSONFormatter supporting `issue`, `worker`, `pr`, `phase`, `batch`, `repo`, `session` fields, but only 1 call site (`src/planner.py:~110`) actually injects context via `extra={}`. All phase loops, runners, and PR operations should inject operational identifiers.

3. **Missing context in log messages** — `src/pr_manager.py`, `src/orchestrator.py`, `src/github_cache.py`, `src/events.py`, `src/post_merge_handler.py` log without issue/PR/repo context, making production tracing difficult.

4. **Log level misuse** — `src/issue_store.py:228-233` logs normal dedup at WARNING; `src/docker_runner.py:331-336` logs transient retries at WARNING.

5. **exc_info usage** — `src/events.py:50` uses `exc_info=exc` instead of `exc_info=True`. `src/docker_runner.py:343` swallows exception with no logging.

### Approach

- Fix the typo in delta_verifier.py
- Create a `ContextLogger` adapter pattern (or use LoggerAdapter) for phase/runner code
- Audit all WARNING-level logs for level appropriateness
- Fix exc_info patterns
- Add success-path logging for critical operations (push, create_pr, merge)

### Files

- `src/delta_verifier.py`
- `src/log.py`
- `src/orchestrator.py`
- `src/pr_manager.py`
- `src/github_cache.py`
- `src/events.py`
- `src/post_merge_handler.py`
- `src/issue_store.py`
- `src/docker_runner.py`
- `src/workspace.py`
- `src/base_runner.py`
- `src/planner.py`

---

## Add runtime log rotation

**Type:** bug
**Priority:** critical
**Labels:** ops, logging

### Description

Runtime logs (`hydraflow.log`) written by `src/log.py` have no rotation configured. Event logs have rotation (100MB cap, 30-day retention via `src/events.py:208-265`), but runtime logs grow unbounded — disk exhaustion risk for long-running instances.

The file handler in `setup_logging()` currently uses a plain handler. Need `RotatingFileHandler` or `TimedRotatingFileHandler`.

### Approach

- Replace the file handler in `src/log.py:setup_logging()` with `RotatingFileHandler`
- Use config values or sensible defaults (e.g., 10MB per file, 10 backups = 100MB cap)
- Optionally add `HYDRAFLOW_LOG_MAX_SIZE_MB` and `HYDRAFLOW_LOG_BACKUP_COUNT` env vars to config.py
- Add per-module log level override support via `HYDRAFLOW_LOG_LEVEL_<MODULE>` pattern

### Files

- `src/log.py`
- `src/config.py` (optional new env vars)

---

## Add startup dependency health checks

**Type:** enhancement
**Priority:** high
**Labels:** ops, resilience

### Description

HydraFlow does not validate external dependencies at startup. Missing or misconfigured tools cause runtime failures on first use instead of fast startup failures:

- `gh` CLI availability and authentication
- `git` CLI availability
- Docker daemon reachability (when `execution_mode=docker`)
- `claude`/`codex` CLI availability (based on configured tools)
- Disk space in `data_root` and `worktree_base`
- Repo root is a valid git repository

Currently these are only discovered when the first operation attempts to use them (e.g., first issue fetch, first worktree creation).

### Approach

- Add a `preflight_checks()` function called early in `server.py` / `orchestrator.py` startup
- Check each dependency, log results, fail fast with clear error messages
- Make checks configurable (skip with `HYDRAFLOW_SKIP_PREFLIGHT=true` for testing)
- Enrich `/healthz` endpoint to report dependency status

### Files

- `src/server.py`
- `src/orchestrator.py`
- `src/config.py`
- `src/dashboard_routes/_routes.py` (healthz enrichment)

---

## Harden error handling in Docker runner

**Type:** bug
**Priority:** high
**Labels:** error-handling, docker

### Description

Multiple error handling gaps in Docker runner:

1. **Silent exception swallowing** — `src/docker_runner.py:327-344` catches `Exception: pass` on Docker reconnect with no logging. Operators can't diagnose why Docker reconnect failed.

2. **Container tracking leak** — `src/docker_runner.py:609-616` adds container to tracking set before `start()`. If start raises, container is tracked but never managed.

3. **Cleanup failures silent** — `src/docker_runner.py:557-563,644-652,662-664` catches `Exception` at debug level during container removal. Orphaned containers possible.

### Approach

- Replace bare `except Exception: pass` with logged warnings including exception details
- Move container tracking add to after successful `start()`
- Elevate cleanup failure logging from debug to warning
- Add container orphan detection on startup (list containers with hydraflow label, kill stale ones)

### Files

- `src/docker_runner.py`

---

## Fix error handling in PR manager and escalation paths

**Type:** bug
**Priority:** critical
**Labels:** error-handling, pipeline

### Description

Critical error handling gaps that can cause stuck issues:

1. **`get_pr_state()` returns `""` on failure** — `src/pr_manager.py:708-714`. Callers checking `if state == "CLOSED"` can't distinguish "unknown" from "open". Issues can get stuck.

2. **Escalation calls unprotected** — `_escalator()` in review_phase.py and implement_phase.py has no try/except. If escalation fails, the issue hangs permanently in its current state.

3. **`asyncio.gather` results not inspected** — `src/orchestrator.py:867,1156,1175,1255` and `src/hitl_phase.py:177` use `return_exceptions=True` but never check returned results. Task failures silently discarded.

4. **Inconsistent retry policy** — Some pr_manager paths use `run_subprocess_with_retry()`, others use bare `run_subprocess()`. Transient GitHub 503s cause immediate failure in unretried paths.

### Approach

- Return a sentinel/enum from `get_pr_state()` instead of empty string (e.g., `"UNKNOWN"`)
- Wrap escalation calls in try/except with logging and fallback (re-label as HITL)
- Add result inspection after `asyncio.gather(..., return_exceptions=True)` — log any exceptions
- Audit all `run_subprocess` calls in pr_manager and upgrade critical ones to `run_subprocess_with_retry`

### Files

- `src/pr_manager.py`
- `src/review_phase.py`
- `src/implement_phase.py`
- `src/orchestrator.py`
- `src/hitl_phase.py`

---

## Add circuit breakers and backoff to GitHub API and background loops

**Type:** enhancement
**Priority:** high
**Labels:** resilience, error-handling

### Description

Several components lack circuit breaker patterns and can fail indefinitely:

1. **GitHub cache** — `src/github_cache.py:132-163` has no circuit breaker. If GitHub is down, poller hammers API forever. `get_open_prs()` returns empty list on failure (indistinguishable from "no PRs").

2. **Background loops** — `src/base_background_loop.py:106-150` catches `Exception` and keeps looping forever. No circuit breaker for fundamentally broken loops.

3. **Orchestrator loop restarts** — `src/orchestrator.py:760-775` restarts crashed loops with no circuit breaker. Fundamentally broken loops spin forever.

4. **Rate limit cooldown** — `src/subprocess_util.py:56-78` uses flat 60s cooldown with no exponential backoff on repeated rate limits.

5. **Credit probe** — `src/subprocess_util.py:153-189` returns `True` (assume available) on network errors.

### Approach

- Add a simple circuit breaker class (consecutive failure count → open state → half-open probe → close)
- Apply to GitHub cache poller, background loops, and orchestrator loop restarts
- Add exponential backoff to rate limit cooldown (60s → 120s → 240s, capped)
- Make credit probe return `False` on network errors (fail-safe)
- Add cache age indicator to `get_open_prs()` return so callers know staleness

### Files

- `src/github_cache.py`
- `src/base_background_loop.py`
- `src/orchestrator.py`
- `src/subprocess_util.py`
- New: `src/circuit_breaker.py`

---

## Harden label swap atomicity and concurrency safety

**Type:** bug
**Priority:** high
**Labels:** concurrency, pipeline

### Description

Race conditions in the issue pipeline:

1. **Label swap not atomic** — `src/pr_manager.py:818-843` adds new label then removes old ones sequentially. Between add and remove, concurrent polling could re-queue the issue. Eager-transition protection (`src/issue_store.py:339-377`) starts AFTER the swap, not during.

2. **IssueStore GIL reliance** — `src/issue_store.py:432-468` `_take_from_queue()` relies on CPython GIL for thread safety (acknowledged in code comment). Fragile.

3. **Orchestrator state sync unlocked** — `src/orchestrator.py:387-395` reads `_active_impl_issues` and `_active_review_issues` without acquiring `_active_issues_lock`.

4. **Epic recursion guard unprotected** — `src/epic.py:130,188-197` uses `_active_closings` set without locking.

### Approach

- Move `enqueue_transition()` call to BEFORE `swap_pipeline_labels()` so protection is active during the swap window
- Add explicit lock acquisition in `_sync_active_issue_numbers()`
- Add asyncio.Lock to epic `_active_closings` guard
- Document the GIL dependency in issue_store with a comment about future-proofing

### Files

- `src/pr_manager.py`
- `src/issue_store.py`
- `src/orchestrator.py`
- `src/epic.py`
- `src/phase_utils.py`

---

## Enrich /healthz endpoint and add stall detection

**Type:** enhancement
**Priority:** high
**Labels:** observability, ops

### Description

The `/healthz` endpoint only checks `orchestrator.running` boolean. It does not verify actual component health. Additionally, there's no stall detection — the pipeline can't detect if most issues are failing.

Gaps:
- No GitHub API connectivity check
- No state file accessibility check
- No queue health (depth, age) reporting
- No worker pool utilization visibility
- No per-worker "currently processing issue X" visibility
- HITL backlog can grow unbounded with no alerting threshold
- No stall/deadlock detection

### Approach

- Extend `/healthz` with component-level checks: GitHub API reachable, state file writable, cache age, queue depths
- Add a `ready` field that reflects actual operational readiness (not just "running")
- Add stall detection: if >X% of issues in last Y minutes escalated to HITL, emit SYSTEM_ALERT
- Add HITL backlog age/count to health response
- Add optional `/healthz?verbose=true` for full diagnostic dump
- Add per-worker current-issue tracking to pipeline stats

### Files

- `src/dashboard_routes/_routes.py`
- `src/orchestrator.py`
- `src/issue_store.py`
- `src/github_cache.py`

---

## Add state.json backup and event log background rotation

**Type:** enhancement
**Priority:** high
**Labels:** ops, resilience

### Description

Two state management gaps:

1. **state.json is single point of failure** — `src/state/__init__.py:81-124`. No backups or versioning. Loss = all in-flight issues forgotten, HITL corrections discarded, lifetime stats partially lost. Corruption handler resets to empty `StateData()`.

2. **Event log rotation only at startup** — `src/events.py:208-265`. Long-running instances accumulate events until next restart. No background cleanup.

3. **No schema versioning** — Model changes could break old state.json on upgrade.

### Approach

- Add periodic state backup: copy state.json to state.json.bak every N minutes (configurable)
- Keep last 3 backups (state.json.bak.1, .bak.2, .bak.3)
- On corruption, attempt restore from most recent backup before resetting to empty
- Add schema version field to StateData for future migration support
- Move event log rotation to a background task (run every 6 hours or on size threshold)

### Files

- `src/state/__init__.py`
- `src/events.py`
- `src/config.py` (new: state_backup_interval, state_backup_count)
- `src/file_util.py`

---

## Add per-agent runtime metrics and HITL backlog management

**Type:** enhancement
**Priority:** medium
**Labels:** observability, metrics

### Description

Operational visibility gaps:

1. **No per-agent runtime tracking** — Only lifetime aggregates exist (`total_implementation_seconds`). Individual issue processing duration, token usage, and cost are not captured.

2. **No proactive alerting** — Everything is pull/event-based. No Slack, PagerDuty, or email integration.

3. **HITL backlog unbounded** — Stale HITL issues remain forever unless manually closed. No timeout, auto-purge, or alerting threshold.

4. **No E2E issue latency** — Can't measure triage-to-merge duration per issue.

### Approach

- Track per-issue timing: start/end timestamp per phase, total E2E duration
- Store in session log and expose via `/api/metrics`
- Add HITL backlog management: configurable max age (e.g., 7 days), auto-close with comment after threshold
- Add optional webhook for alerts (generic POST to configurable URL on SYSTEM_ALERT events)
- Add E2E latency to pipeline stats and metrics snapshots

### Files

- `src/models.py`
- `src/metrics_manager.py`
- `src/orchestrator.py`
- `src/hitl_phase.py`
- `src/events.py`
- `src/config.py`
- `src/dashboard_routes/_routes.py`
