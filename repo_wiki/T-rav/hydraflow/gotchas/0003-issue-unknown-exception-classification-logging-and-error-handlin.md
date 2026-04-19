---
id: 0003
topic: gotchas
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T15:40:17.674465+00:00
status: active
---

# Exception Classification, Logging, and Error Handling

Distinguish bug exceptions (TypeError, AttributeError, KeyError, ValueError, IndexError) from transient errors (RuntimeError, OSError, CalledProcessError, httpx network exceptions) using log_exception_with_bug_classification() or is_likely_bug(). Use logger.exception() only for genuine bugs; transient operational failures use logger.warning(..., exc_info=True). In finally blocks, use log_exception_with_bug_classification() instead of reraise to preserve finally semantics.

For HTTP errors, use reraise_on_credit_or_bug() to selectively re-raise critical exceptions (AuthenticationError, CreditExhaustedError, MemoryError) while logging transient failures. Subprocess exceptions: TimeoutExpired and CalledProcessError are siblings, not parent-child—both must be caught separately. Read-path methods return safe defaults; write-path methods propagate TimeoutExpired to prevent silent data loss.

Logging strategy follows docs/agents/sentry.md: transient failures log at WARNING; LoggingIntegration(event_level=logging.ERROR) prevents spurious Sentry alerts. Data-integrity violations log at ERROR. Avoid silent `except Exception: pass`; use reraise_on_credit_or_bug(exc) + logger.warning(..., exc_info=True). When migrating from logger.exception() to logger.warning(), explicitly add exc_info=True or tracebacks disappear.

In retry loops, wrap per-item API calls in try/except so one item's failure doesn't abort the cycle. In background loops, classify exceptions: fatal (auth/credit) propagates, bugs (local logic) propagate, transient (per-item runtime) logged as warnings. When a loop encounters 5 consecutive failures of the same type, circuit breaker publishes SYSTEM_ALERT exactly once.

Post-merge orchestration runs sequential operations: merge→verify→retrospect→epic check→state record→event publish→cleanup. Exception handling only catches (RuntimeError, OSError, ValueError); others propagate. Use run_with_fatal_guard pattern from phase_utils for consistent logging.

Async/await: Omitting await on async methods returns unawaited coroutines that silently never execute—Pyright flags these during make typecheck. asyncio.create_task() calls without stored references get garbage-collected, silently dropping exceptions. Store all create_task results and add done callbacks for logging. Implement safe background task pattern: add private `_background_tasks: set[asyncio.Task[None]]`. Register cleanup callback before logging callback. When re-raising fatal errors from async tasks, revert dependent state flags (e.g., _pipeline_enabled = False) BEFORE raising to ensure state consistency.

See also: Telemetry — apply exception classification to distinguish bugs from transient errors; Memory System — apply same classification during memory injection; State Persistence — exception handling during state transitions.
