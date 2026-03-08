# ADR-0023: Implementation Retry Recovery Architecture

**Status:** Proposed
**Date:** 2026-03-08

## Context

HydraFlow's implement phase (`src/implement_phase.py`) manages a retry flow for
failed implementations. The current architecture follows a three-step pattern:

1. **`_check_attempt_cap()`** — Increments the per-issue attempt counter and
   checks against `max_issue_attempts`. On cap exceeded, retrieves the last
   error from `state.get_worker_result_meta()` and escalates to HITL.
2. **`_run_implementation()`** — Sets up the worktree/branch via
   `_setup_worktree_and_branch()`, runs the agent, and records metrics via
   `_record_impl_metrics()` (which persists `WorkerResultMeta` including error,
   commits, duration, and quality-fix rounds to `StateTracker`).
3. **`_handle_implementation_result()`** — Decides the outcome: zero-commit
   results escalate immediately to HITL, zero-diff results escalate similarly,
   PR creation failures keep the issue in the ready queue, and successful
   results transition to review.

Several gaps exist in the current retry recovery path:

- **No prior-failure context fed to the agent.** `get_worker_result_meta()`
  stores error details and commit counts from the previous attempt, but this
  context is never passed to the agent on retry. The agent starts each attempt
  blind to why the previous one failed, leading to repeated identical failures.
- **Zero-commit results bypass retry.** When the agent produces zero commits,
  `_handle_implementation_result()` escalates directly to HITL without giving
  the retry loop a chance. This is overly aggressive — a transient agent error
  or misunderstanding may resolve on a second attempt with better context.
- **Worktree reset asymmetry.** `_setup_worktree_and_branch()` only resets the
  worktree to `origin/main` when `review_feedback` is present (review-feedback
  retries). Regular implementation retries reuse the existing worktree state,
  which may contain partial or broken changes from the failed attempt. This
  inconsistency can cause the agent to build on top of broken code.

## Decision

Record and adopt the following architectural principles for implementation retry
recovery:

### 1. Feed prior-failure context to retry agents

When an implementation attempt fails and the issue re-enters the ready queue,
the next attempt should retrieve `WorkerResultMeta` from `StateTracker` and
include the prior error, commit count, and quality-fix history as context for
the agent. This gives the agent an opportunity to diagnose what went wrong and
take a different approach.

### 2. Allow zero-commit retries before HITL escalation

Instead of immediately escalating zero-commit results to HITL, treat them as
implementation failures eligible for retry (subject to `max_issue_attempts`).
Only escalate to HITL when the attempt cap is exceeded. This aligns zero-commit
handling with other failure modes and gives the retry loop a chance to recover.

### 3. Normalize worktree reset for all retries

Apply the same worktree reset logic (`git reset --hard origin/main`) for regular
implementation retries as for review-feedback retries. When an implementation
attempt fails and the issue is retried, the agent should start from a clean
`origin/main` rather than building on top of the previous failed attempt's
partial changes. The `reset_to_main` parameter in `_setup_worktree_and_branch()`
should be driven by whether the issue has a previous failed attempt, not only
by whether review feedback is present.

### Scope boundaries

- The retry recovery changes are scoped to the implement phase
  (`src/implement_phase.py`) and its interaction with `StateTracker`
  (`src/state.py`) and `AgentRunner` (`src/agent.py`).
- The review phase's own retry/escalation logic remains unchanged.
- The `max_issue_attempts` cap continues to serve as the upper bound for all
  retry paths, preventing infinite retry loops.

### Operational impact on HydraFlow workers

- Workers may see slightly longer issue lifecycles as zero-commit failures are
  retried instead of immediately escalated. This is expected to reduce HITL
  queue pressure by resolving transient failures automatically.
- Prior-failure context increases the prompt size for retry attempts, but the
  additional token cost is minimal compared to the cost of a wasted attempt.
- Worktree resets on retry add a `git fetch` + `git reset` overhead per retry,
  but this is negligible compared to the agent runtime.

## Consequences

**Positive**

- Agents receive actionable context about prior failures, increasing the
  likelihood of successful retries without human intervention.
- Zero-commit failures get a fair retry opportunity, reducing unnecessary HITL
  escalations and human toil.
- Consistent worktree reset behavior eliminates a class of bugs where retry
  agents inherit broken state from failed attempts.
- The retry flow becomes more predictable: all failure modes follow the same
  attempt-cap-then-escalate pattern.

**Negative / Trade-offs**

- Retrying zero-commit failures delays HITL escalation for genuinely stuck
  issues by one or more retry cycles, increasing wall-clock time to human
  intervention.
- Resetting the worktree on every retry discards any partial progress from the
  failed attempt. If the agent made useful partial changes, they are lost.
- Feeding prior-failure context to the agent adds complexity to the agent
  invocation path and requires changes to the `AgentRunner.run()` interface.

## Alternatives considered

1. **Keep zero-commit as immediate HITL escalation** — rejected because
   transient agent errors are common enough that a retry is worth the cost.
   The attempt cap still provides a safety net.
2. **Preserve partial worktree state on retry** — rejected because partial
   changes from a failed attempt are more likely to cause cascading failures
   than to provide useful scaffolding. A clean start is safer.
3. **Store prior-failure context externally (e.g., issue comment)** — rejected
   because `WorkerResultMeta` already stores this data in `StateTracker`. Using
   the existing persistence layer avoids duplication and keeps the agent
   interface cleaner.

## Related

- Source memory: [#2258 — Implementation retry recovery architecture](https://github.com/T-rav/hydra/issues/2258)
- Implementing issue: [#2264](https://github.com/T-rav/hydra/issues/2264)
- Key files: `src/implement_phase.py`, `src/state.py`, `src/agent.py`
