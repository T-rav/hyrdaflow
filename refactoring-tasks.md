# Refactoring Task List — Code Decomposition

Review of the phase runners, orchestrator, `pr_manager.py`, and `issue_store.py` to identify
logic clusters that should become their own classes or focused methods.

---

## Priority 1 — DRY: Eliminate Duplicated Code

### [ ] Extract `HarnessFailureRecorder`
**Problem:** `_record_harness_failure()` is copy-pasted identically across three phase files.

| File | Lines |
|------|-------|
| `plan_phase.py` | ~238–263 |
| `implement_phase.py` | ~313–338 |
| `review_phase.py` | ~766–794 |

**Solution:** Single class injected into each phase via constructor.
```python
class HarnessFailureRecorder:
    def __init__(self, harness_insights: HarnessInsightStore) -> None: ...
    def record(self, issue: Task, result: AgentResult, phase: str) -> None: ...
```
Saves ~70 LOC and ensures consistent behaviour across all three phases.

---

## Priority 2 — High Impact: Large Method Decomposition

### [ ] Extract `CIFixOrchestrator` from `review_phase.py`
**Problem:** `wait_and_fix_ci()` (~96 lines) mixes CI polling, fix-agent execution, and HITL escalation.

**Solution:**
```python
class CIFixOrchestrator:
    async def run(self, pr: PRInfo, issue: Task) -> CIFixResult: ...
    async def _poll_and_fix(self, pr: PRInfo) -> tuple[bool, str]: ...
    async def _escalate(self, pr: PRInfo, issue: Task, logs: str) -> None: ...
```

### [ ] Extract `HITLItemBuilder` from `pr_manager.py`
**Problem:** `list_hitl_items()` (~89 lines) mixes issue fetching, deduplication, branch-name
generation, PR lookup, and `HITLItem` assembly — 9 try/except blocks inline.

**Solution:**
```python
class HITLItemBuilder:
    async def build(self, labels: list[str]) -> list[HITLItem]: ...
    async def _fetch_issues(self, labels: list[str]) -> list[GitHubIssue]: ...
    async def _lookup_pr(self, issue: GitHubIssue) -> PRInfo | None: ...
    def _assemble_item(self, issue: GitHubIssue, pr: PRInfo | None) -> HITLItem: ...
```

### [ ] Extract `LoopExceptionHandler` from `orchestrator.py`
**Problem:** `_handle_loop_exception()` dispatches on exception type and contains auth, credit,
and generic recovery paths all inline.

**Solution:**
```python
class LoopExceptionHandler:
    async def handle(self, exc: BaseException, loop_name: str) -> LoopAction: ...
    async def _handle_auth_failure(self, exc: AuthError) -> LoopAction: ...
    async def _handle_credit_exhaustion(self, exc: CreditError) -> LoopAction: ...
    async def _handle_generic(self, exc: Exception, loop_name: str) -> LoopAction: ...
```

### [ ] Extract `WorkerAttemptValidator` from `implement_phase.py`
**Problem:** `_check_attempt_cap()` (~38 lines) mixes cap-exceeded detection, HITL escalation,
state recording, and comment posting.

**Solution:**
```python
class WorkerAttemptValidator:
    async def check(self, issue: Task, attempt: int) -> WorkerResult | None:
        """Returns a terminal WorkerResult if capped, else None to continue."""
```

---

## Priority 3 — Cohesion: Mixed-Level Methods

### [ ] Extract `PlanResultHandler` from `plan_phase.py`
**Problem:** The inner `_plan_one()` (~177 lines) handles 8 distinct outcomes inline: already
satisfied, success (with sub-issue filing), retry failure, memory suggestions, transcript
summarisation.

**Solution:**
```python
class PlanResultHandler:
    async def handle_already_satisfied(self, issue: Task, result: PlanResult) -> None: ...
    async def handle_success(self, issue: Task, result: PlanResult) -> None: ...
    async def handle_retry_failed(self, issue: Task, result: PlanResult) -> None: ...
    async def _file_sub_issues(self, issues: list[SubIssue]) -> None: ...
    async def _post_transcript_summary(self, issue: Task, result: PlanResult) -> None: ...
```

### [ ] Extract `ReviewRoutingStrategy` from `review_phase.py`
**Problem:** `_review_one_inner()` (~111 lines) handles setup, skip-guard, merge, review
execution, self-fix loop, metrics, verdict routing, and worktree cleanup at the same level.

**Solution:** Split into focused helpers.
```python
class ReviewSkipGuard:
    def should_skip(self, pr: PRInfo, last_sha: str | None) -> bool: ...

class ReviewVerdictRouter:
    async def route(self, verdict: ReviewVerdict, pr: PRInfo, issue: Task) -> None: ...
    async def _handle_approve(self, ...) -> None: ...
    async def _handle_request_changes(self, ...) -> None: ...
    async def _handle_comment(self, ...) -> None: ...
```

### [ ] Extract `IssueRouter` from `issue_store.py`
**Problem:** `_route_issues()` (~68 lines) builds the label map, caches tasks, determines stages,
removes stale entries, and moves tasks between queues.

**Solution:**
```python
class IssueRouter:
    def route(self, tasks: list[Task], queues: dict[str, deque]) -> None: ...
    def _determine_stage(self, task: Task, label_map: dict) -> str | None: ...
    def _remove_stale(self, queues: dict, current_ids: set[int]) -> None: ...
    def _move_to_stage(self, task: Task, stage: str, queues: dict) -> None: ...
```

### [ ] Extract `CreditPauseManager` from `orchestrator.py`
**Problem:** `_pause_for_credits()` (~68 lines) mixes lock acquisition, reset-time calculation,
logging, event publishing, subprocess termination, and sleep.

**Solution:**
```python
class CreditPauseManager:
    async def pause_until_reset(self, reset_at: datetime) -> None: ...
    def _calculate_sleep_duration(self, reset_at: datetime) -> float: ...
    async def _terminate_subprocesses(self) -> None: ...
    async def _publish_pause_event(self, duration: float) -> None: ...
```

---

## Priority 4 — Polish: Utility Formalisation

### [ ] Extract `CommentFormatter` from `pr_manager.py`
**Problem:** `_chunk_body()` and `_cap_body()` are private static helpers but should be a
standalone utility since comment formatting is a distinct, testable concern.

```python
class CommentFormatter:
    MAX_COMMENT_CHARS: int = ...
    def format(self, body: str) -> list[str]: ...  # returns chunks
    def cap(self, body: str) -> str: ...
```

### [ ] Extract `CIFailureLogCollector` from `pr_manager.py`
**Problem:** `fetch_ci_failure_logs()` (~66 lines) mixes check fetching, run-ID URL parsing,
and per-run log fetching.

```python
class CIFailureLogCollector:
    async def collect(self, pr_number: int) -> str: ...
    async def _get_failed_run_ids(self, pr_number: int) -> list[str]: ...
    async def _fetch_log(self, run_id: str) -> str: ...
```

### [ ] Extract `GitHubMetricsAggregator` from `pr_manager.py`
**Problem:** `_count_open_issues_by_label()`, `_count_closed_issues()`, `_count_merged_prs()`
repeat the same `gh search` → parse → return count pattern.

```python
class GitHubMetricsAggregator:
    async def count_open_by_label(self, label: str) -> int: ...
    async def count_closed(self, label: str, since: datetime) -> int: ...
    async def count_merged_prs(self, label: str, since: datetime) -> int: ...
    async def _run_search(self, query: str) -> int: ...  # shared parse logic
```

### [ ] Extract `RecoveryManager` from `orchestrator.py`
**Problem:** Crash-recovery logic (restoring state, building interrupted-issue lists) is inline
in the orchestrator startup path.

```python
class RecoveryManager:
    def restore(self, state: StateTracker, store: IssueStore) -> list[Task]: ...
    def _build_interrupted_issues(self, state: StateTracker) -> list[Task]: ...
```

---

## Already Well-Designed (No Action Needed)

- `task_source.py` — clean protocol interfaces, good abstraction model
- `phase_utils.py` — focused, composable utilities
- `triage_phase.py` — short and coherent after recent refactor

---

## Suggested Implementation Order

```
1. HarnessFailureRecorder       ← eliminates real duplication, low risk
2. CIFixOrchestrator            ← biggest complexity win in review_phase
3. HITLItemBuilder              ← isolates fragile gh-CLI parsing
4. LoopExceptionHandler         ← simplifies orchestrator restart logic
5. WorkerAttemptValidator       ← cleaner implement_phase worker flow
6. PlanResultHandler            ← reduces plan_phase to readable outline
7. ReviewSkipGuard + Router     ← splits review_one_inner sensibly
8. IssueRouter                  ← decouples routing from store
9. CreditPauseManager           ← cleaner orchestrator credit handling
10. CommentFormatter            ← testable in isolation
11. CIFailureLogCollector       ← isolates CI log parsing
12. GitHubMetricsAggregator     ← DRY across three count methods
13. RecoveryManager             ← clean startup path
```
