# Operational Audit — Implementation Plan

Plan for fixing the 44 findings from the HydraFlow operational audit (2026-03-25).
Findings grouped into 10 Beads issues, prioritized P0–P2, ordered by execution sequence.

## Execution Order

Issues are ordered by dependency and risk — fix critical bugs first, then harden, then enhance.

### Phase 1: Critical Fixes (P0)

These fix active production risks — stuck issues and disk exhaustion.

#### 1. `ops-audit-fixes-g566` — Fix error handling in PR manager and escalation paths

**Audit findings:** #4, #5, #6, #15

**Changes:**

| File | Change |
|------|--------|
| `src/pr_manager.py:708-714` | Return `"UNKNOWN"` sentinel from `get_pr_state()` on failure instead of `""`. Update all callers to handle the sentinel. |
| `src/review_phase.py` | Wrap `_escalator()` calls in try/except. On failure: log error, apply `hydraflow-hitl` label directly as fallback. |
| `src/implement_phase.py` | Same escalator wrapping. |
| `src/orchestrator.py:867,1156,1175,1255` | After `asyncio.gather(..., return_exceptions=True)`, iterate results and log any that are exceptions. |
| `src/hitl_phase.py:177` | Same gather-result inspection. |
| `src/pr_manager.py` (multiple methods) | Audit all `run_subprocess` calls. Upgrade `push_branch`, `create_pr`, `merge_pr`, `get_pr_state`, `swap_pipeline_labels` to use `run_subprocess_with_retry`. |

**Tests:** Add test for `get_pr_state()` returning `"UNKNOWN"` on subprocess failure. Test escalator fallback path. Test gather-result logging.

---

#### 2. `ops-audit-fixes-izcu` — Add runtime log rotation

**Audit finding:** #9

**Changes:**

| File | Change |
|------|--------|
| `src/log.py:setup_logging()` | Replace `FileHandler` with `RotatingFileHandler(maxBytes=10*1024*1024, backupCount=10)`. |
| `src/config.py` | Add `log_max_size_mb` (default 10) and `log_backup_count` (default 10) to `_ENV_INT_OVERRIDES`. |

**Tests:** Unit test that `setup_logging()` creates a `RotatingFileHandler` when file path is configured.

---

### Phase 2: High-Priority Hardening (P1)

Fix concurrency bugs, add resilience patterns, improve observability.

#### 3. `ops-audit-fixes-gipv` — Fix logger typo and adopt structured logging

**Audit findings:** #1, #2, #3, #21, #31, #32, #33, #41

**Changes:**

| File | Change |
|------|--------|
| `src/delta_verifier.py:10` | Fix `"hydra.delta_verifier"` → `"hydraflow.delta_verifier"` |
| `src/log.py` | Add `ContextLoggerAdapter` class wrapping `logging.LoggerAdapter` with `issue`, `pr`, `repo`, `phase`, `worker` context. |
| `src/orchestrator.py` | Use `ContextLoggerAdapter` in loop bodies with phase context. |
| `src/pr_manager.py` | Inject issue/PR context in all log calls. Add success-path logging for push, create_pr, merge. |
| `src/github_cache.py` | Add repo slug to cache poll failure logs. |
| `src/events.py:50` | Fix `exc_info=exc` → `exc_info=True`. |
| `src/docker_runner.py:343` | Add `logger.warning("Docker reconnect failed", exc_info=True)` instead of bare continue. |
| `src/issue_store.py:228-233` | Downgrade dedup log from WARNING to DEBUG. |
| `src/docker_runner.py:331-336` | Downgrade transient retry log from WARNING to INFO. |
| `src/workspace.py` | Add completion logs for fetch, merge, venv creation. |
| `src/post_merge_handler.py` | Add epic number context to failure logs. |
| `src/base_runner.py` | Add attempt count context to auth retry messages. |

**Tests:** Test that `ContextLoggerAdapter` injects expected fields. Test log level correctness for dedup and retry paths.

---

#### 4. `ops-audit-fixes-v1rc` — Harden Docker runner error handling

**Audit findings:** #3, #24, #25

**Changes:**

| File | Change |
|------|--------|
| `src/docker_runner.py:327-344` | Replace `except Exception: pass` with `except Exception: logger.debug(...)` on first ping, `logger.warning(...)` on retries. |
| `src/docker_runner.py:609-616` | Move `self._containers.add(container)` to after successful `container.start()`. |
| `src/docker_runner.py:557-563,644-652,662-664` | Elevate cleanup failure logging from debug to warning. |

**Tests:** Test that container is not tracked when `start()` raises. Test that cleanup failures are logged.

---

#### 5. `ops-audit-fixes-inw6` — Harden label swap atomicity

**Audit findings:** #11, #12, #13, #23

**Changes:**

| File | Change |
|------|--------|
| `src/issue_store.py` / `src/phase_utils.py` | Call `enqueue_transition()` BEFORE `swap_pipeline_labels()` so eager-transition protection is active during the swap window. |
| `src/orchestrator.py:387-395` | Acquire `_active_issues_lock` in `_sync_active_issue_numbers()`. |
| `src/epic.py:130,188-197` | Add `asyncio.Lock` to protect `_active_closings` set. |
| `src/issue_store.py:432-468` | Add comment documenting GIL dependency and future-proofing note. |

**Tests:** Test that `enqueue_transition` prevents re-routing during label swap. Test locked state sync.

---

#### 6. `ops-audit-fixes-i0f4` — Add circuit breakers and backoff

**Audit findings:** #14, #16, #17, #26, #27

**Changes:**

| File | Change |
|------|--------|
| New: `src/circuit_breaker.py` | Simple circuit breaker: `max_failures` threshold → open state → `reset_timeout` → half-open probe → close. ~50 lines. |
| `src/github_cache.py` | Wrap poll() in circuit breaker. Add `cache_age_seconds` to return values so callers know staleness. |
| `src/base_background_loop.py` | Add consecutive failure counter. After N consecutive failures (configurable, default 10), pause loop for backoff period and emit SYSTEM_ALERT. |
| `src/orchestrator.py:760-775` | Add circuit breaker to loop restart logic. After 5 consecutive restarts within 5 minutes, stop the loop and emit SYSTEM_ALERT. |
| `src/subprocess_util.py:56-78` | Replace flat 60s cooldown with exponential backoff: 60s → 120s → 240s → 480s cap. |
| `src/subprocess_util.py:153-189` | Return `False` on network errors in `probe_credit_availability()` (fail-safe). |

**Tests:** Unit tests for circuit breaker state machine. Test exponential backoff sequence. Test probe returns False on network error.

---

#### 7. `ops-audit-fixes-j0xs` — Add startup dependency health checks

**Audit findings:** #8, #34

**Changes:**

| File | Change |
|------|--------|
| New: `src/preflight.py` | `run_preflight_checks(config) -> list[CheckResult]` — checks gh, git, docker (if needed), agent CLIs, disk space, repo validity. Returns pass/warn/fail per check. |
| `src/server.py` | Call `run_preflight_checks()` after config load, before starting dashboard/orchestrator. Log results. Fail fast on critical failures. |
| `src/config.py` | Add `HYDRAFLOW_SKIP_PREFLIGHT` bool override (default False). |
| `src/dashboard_routes/_routes.py` | Add preflight results to `/healthz` response under `preflight` key. |

**Tests:** Test each check in isolation (mock subprocess calls). Test skip-preflight flag.

---

#### 8. `ops-audit-fixes-6tpn` — Enrich /healthz and add stall detection

**Audit findings:** #7, #20, #28, #29, #30

**Changes:**

| File | Change |
|------|--------|
| `src/dashboard_routes/_routes.py` | Extend `/healthz` with: GitHub cache age, state file writable, queue depths per stage, HITL backlog count/oldest age, worker pool utilization. Add `?verbose=true` for full dump. |
| `src/orchestrator.py` | Add stall detection: track HITL escalation rate over sliding window. If >50% of completed issues in last 30 minutes escalated, emit SYSTEM_ALERT. |
| `src/issue_store.py` | Add method to report queue ages (oldest item per stage). |
| `src/github_cache.py` | Expose `last_successful_poll` timestamp. |

**Tests:** Test healthz returns enriched fields. Test stall detection threshold. Test queue age reporting.

---

#### 9. `ops-audit-fixes-88hb` — State backup and event log rotation

**Audit findings:** #10, #30, #43

**Changes:**

| File | Change |
|------|--------|
| `src/state/__init__.py` | Add `backup()` method: copy state.json → state.json.bak, rotate .bak.1/.bak.2/.bak.3. Call from `save()` every N minutes (configurable). On corruption, attempt restore from backups before resetting. |
| `src/state/__init__.py` | Add `schema_version: int = 1` field to `StateData` for future migration. |
| `src/events.py` | Add background rotation: check size/age every 6 hours (or configurable), rotate if needed. Currently rotation only runs at startup. |
| `src/config.py` | Add `state_backup_interval` (default 300s), `state_backup_count` (default 3). |
| `src/file_util.py` | Add `rotate_backups(path, count)` utility. |

**Tests:** Test backup rotation keeps correct count. Test restore-from-backup on corruption. Test schema version field presence.

---

### Phase 3: Enhancements (P2)

#### 10. `ops-audit-fixes-4g6w` — Per-agent metrics and HITL backlog management

**Audit findings:** #18, #19, #20

**Changes:**

| File | Change |
|------|--------|
| `src/models.py` | Add `IssueTimeline` model: per-phase start/end timestamps, total E2E duration. |
| `src/orchestrator.py` | Record phase timestamps as issues transition through pipeline. |
| `src/metrics_manager.py` | Include E2E latency stats (p50, p95, avg) in snapshots. |
| `src/hitl_phase.py` | Add HITL backlog management: configurable max age (default 7 days). Auto-close stale HITL issues with comment. |
| `src/events.py` | Add optional webhook: POST to configurable URL on SYSTEM_ALERT events. |
| `src/config.py` | Add `hitl_max_age_days`, `alert_webhook_url`. |
| `src/dashboard_routes/_routes.py` | Expose per-issue timeline in `/api/pipeline` and E2E latency in `/api/metrics`. |

**Tests:** Test timeline recording. Test HITL auto-close after max age. Test webhook fires on SYSTEM_ALERT.

---

## Finding Coverage Matrix

| Finding # | Severity | Issue |
|-----------|----------|-------|
| 1 | Critical | `gipv` (logging) |
| 2 | Critical | `gipv` (logging) |
| 3 | Critical | `v1rc` (docker) |
| 4 | Critical | `g566` (PR manager) |
| 5 | Critical | `g566` (PR manager) |
| 6 | Critical | `g566` (PR manager) |
| 7 | Critical | `6tpn` (healthz) |
| 8 | Critical | `j0xs` (preflight) |
| 9 | Critical | `izcu` (log rotation) |
| 10 | Critical | `88hb` (state backup) |
| 11 | High | `inw6` (concurrency) |
| 12 | High | `inw6` (concurrency) |
| 13 | High | `inw6` (concurrency) |
| 14 | High | `i0f4` (circuit breakers) |
| 15 | High | `g566` (PR manager) |
| 16 | High | `i0f4` (circuit breakers) |
| 17 | High | `i0f4` (circuit breakers) |
| 18 | High | `4g6w` (metrics) |
| 19 | High | `4g6w` (metrics) |
| 20 | High | `6tpn` + `4g6w` |
| 21 | High | `gipv` (logging) |
| 22 | Medium | `inw6` (concurrency) |
| 23 | Medium | `inw6` (concurrency) |
| 24 | Medium | `v1rc` (docker) |
| 25 | Medium | `v1rc` (docker) |
| 26 | Medium | `i0f4` (circuit breakers) |
| 27 | Medium | `i0f4` (circuit breakers) |
| 28 | Medium | `6tpn` (healthz) |
| 29 | Medium | `6tpn` (healthz) |
| 30 | Medium | `88hb` (event rotation) |
| 31 | Medium | `gipv` (logging) |
| 32 | Medium | `gipv` (logging) |
| 33 | Medium | `gipv` (logging) |
| 34 | Medium | `j0xs` (preflight) |
| 35 | Medium | `inw6` (concurrency) |
| 36 | Medium | `j0xs` (preflight) |
| 37 | Low | Accepted risk (CPython GIL) |
| 38 | Low | Accepted risk (CPython GIL) |
| 39 | Low | `v1rc` (docker — grouped) |
| 40 | Low | `v1rc` (docker — grouped) |
| 41 | Low | `gipv` (logging) |
| 42 | Low | `izcu` (log rotation) |
| 43 | Low | `88hb` (state backup) |
| 44 | Low | Documented (hot reload limitations) |

All 44 findings covered. Findings #37, #38, #44 are accepted risks or documentation items.
