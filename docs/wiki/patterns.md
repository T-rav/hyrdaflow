# Patterns


## Backward compatibility and schema evolution

Schema changes must preserve backward compatibility through optional fields with sensible defaults, type narrowing on bare strings (safe if values already conform), and StrEnum coercion for auto-conversion. Pydantic v2 auto-coerces raw dicts from state.json into typed models with no migration validators. Distinguish bare `str` fields (safe to narrow) from union types like `str | None` (require union narrowing) and verify all call sites before narrowing types via exhaustive grep-based audits. Establish single source of truth via canonical constants (e.g., `ALL_LIFECYCLE_LABEL_FIELDS`); functions derive from this single source rather than duplicating label lists. Use metadata tags instead of enum variants for categorizing items in shared banks (e.g., `{"source": "adr_council"}`)—avoids syncing enum changes across type checks, prompts, and display order. Make new fields optional with sensible defaults on read (e.g., `.get("scope", "repo")`); no migration needed. Reference canonical constants in reset code, never magic numbers. Preserve exact retry counter state and escalation conditions during schema evolution when refactoring state machine dispatchers.

See also: Refactoring and testing practices — call site verification; Concurrency and I/O safety — metadata tag usage and atomic write patterns; Memory management — metadata tag usage and schema versioning.


```json:entry
{"id":"01KQ11A4G90JQVA2ZA7FT25K9Q","title":"Backward compatibility and schema evolution","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T15:38:18.766106+00:00","updated_at":"2026-04-18T15:38:18.766115+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Refactoring and testing practices

**Refactoring**: Before changing function signatures, grep the codebase to find all call sites and confirm scope. For public functions, use `git grep` to verify zero remaining matches after refactoring. Changes to widely-used utilities require exhaustive caller audits—missing even one call site causes `TypeError` at runtime. When return types change (e.g., `str | None` → `dict | None`), all callers must be updated atomically in a single commit. Preserve public/semi-public method signatures using thin delegation stubs, `__getattr__` facades, or mixin inheritance from shared base clients when tests/external code depend on extracted code; use optional parameters to gate composition logic when decomposing large methods. Extract pure transform functions first—they lack mutable closure state and are lowest-risk candidates. Error isolation preservation: preserve per-concern try/except blocks exactly as-is to prevent failures in one concern from blocking others. Keep early-return cases inline in parent rather than extracting. Extract to pure module-level functions before moving to new classes for independent testability. Pre-compute loop variables outside iteration (e.g., `event_type = str(...)`). Remove vestigial variables from incomplete features, guards for dead paths, and functions with trivial implementations if they have no production callers. Extract duplicated JSONL-reading logic to shared `_load_jsonl(path, label)` helpers to prevent divergence and ensure consistency across refactors.

**Testing**: Mock at the definition site (e.g., `hindsight.tombstone_safe`) not the import site, combined with deferred imports inside test methods—prevents import-time failures and keeps optional dependencies truly optional. When testing dependency injection, explicitly verify that the injected dependency is used instead of self-constructed. Verify protocol implementation via structural subtype checks (signature inspection with `inspect.signature()`) rather than `isinstance()`. When methods are moved during refactoring, retarget mock patches to the new location before refactoring to preserve mock interception at the facade level. Both parametrized tests and explicit named spot-check methods improve readability. Supply async variants of sync methods with a-prefix (arecord_outcome, aupdate_scores) following Python conventions. Generated content (test skeletons, comments) must not reference line numbers—use exact function/class names and string search for stability across refactors. Meta-tests scan the codebase for anti-patterns and fail if found (e.g., `sys.path.insert` outside conftest.py). Run existing tests unchanged after refactoring as the primary regression test.

See also: Backward compatibility and schema evolution — type narrowing and state preservation; Concurrency and I/O safety — error isolation and crash-safe patterns; State machine transitions — test preservation and dispatcher refactoring.


```json:entry
{"id":"01KQ11A4G90JQVA2ZA7FT25K9R","title":"Refactoring and testing practices","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T15:38:18.766124+00:00","updated_at":"2026-04-18T15:38:18.766125+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Concurrency and I/O safety

Use `threading.Lock` when code runs in a thread pool (via `asyncio.to_thread()`) or is called from both sync and async contexts—`asyncio.Lock` is not thread-safe. Use `asyncio.Lock` only for coordinating pure coroutines without thread-pool involvement. For concurrent file I/O with brief lock hold times, `threading.Lock` is appropriate. Extract `_unlocked()` helper variants to prevent re-entrant lock attempts when lock-holding methods call each other. For crash-safe I/O: use `file_util.append_jsonl()` wrapped in `file_lock()` for JSONL appends (includes `flush()` and `os.fsync()`). Use `file_util.atomic_write()` for critical state file updates (writes to temp, then `os.replace()` atomically). Use `os.replace()` for atomic JSONL rewrites when content is small. All three patterns prevent partial writes and crash-induced corruption. Lock files (zero-byte sentinels) are durable and not cleaned up—overhead is negligible. Concurrent append-while-rewrite races are accepted at low frequency (hourly) but document as a load-bearing constraint.

For state mutations in asyncio (e.g., StateTracker), synchronous methods guarantee safe interleaving—locking is needed at the file level (via `file_lock()`), not the in-memory object level. Claim-then-merge for async queue processing: atomically claim items (clear/load), release lock, perform async work, re-acquire lock, reload for new items, merge with remaining, atomically write. Prevents lost entries when `write_all` overwrites file during async gap. Preserved tracing context lifecycle: set/clear or begin/end pairs MUST execute within single try/finally block to prevent trace state leaks. If accidentally split during refactoring, trace state leaks across issues/iterations. Fast synchronous I/O safe directly in async context when latency is negligible and lock contention is low. Call state cleanup unconditionally to purge stale state even when primary work set is empty. Event publishing stays coupled with condition checks in the same method—separating event logic from condition checks creates code paths where gates block but events don't fire, breaking observability.

See also: Refactoring and testing practices — error isolation preservation; Memory management — atomic write patterns and crash-safe file operations.


```json:entry
{"id":"01KQ11A4G90JQVA2ZA7FT25K9S","title":"Concurrency and I/O safety","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T15:38:18.766127+00:00","updated_at":"2026-04-18T15:38:18.766128+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## State machine transitions

When extracting phase result classification or handling logic, preserve exact retry counter state and escalation conditions (like epic-child label swaps) from the original flow. These behavioral subtleties directly impact correctness of phase state transitions. Dry-run mode must not emit state-changing events (e.g., TRIAGE_ROUTING) to ensure dry-run has no observable side effects. Phase result routing through dispatch patterns must maintain the immutable return contract exactly (tuple[str, str | None] for parse()). Event/worker mappings must precede skip detection—EVENT_TO_STAGE and SOURCE_TO_STAGE mappings must be implemented together with skip detection logic. Run existing tests unchanged after refactoring as the primary regression test to validate behavior preservation.

See also: Backward compatibility and schema evolution — retry counter state preservation; Refactoring and testing practices — call site verification and test preservation; Concurrency and I/O safety — state mutation patterns.


```json:entry
{"id":"01KQ11A4G90JQVA2ZA7FT25K9T","title":"State machine transitions","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T15:38:18.766130+00:00","updated_at":"2026-04-18T15:38:18.766131+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Memory management

**Budget allocation**: Must be pre-allocated upfront before prompt assembly in `_inject_memory()` since post-hoc surplus reclamation is impossible. Use a two-round allocator: round one gives each section its minimum, round two distributes remaining budget proportionally by label-keyed priority (from `_DEFAULT_PRIORITIES`). The allocator sets budget caps as hard maxes, not predicted lengths—sections may use less due to summarization wrapping. Budget allocations must be explicitly consumed after calling `get_allocation()`. Wiki budget (`max_repo_wiki_chars`) is separate from memory budget and must be deducted from memory surplus BEFORE redistributing. Accept minor waste from unused memory budget rather than implementing complex multi-pass strategies.

**Loading and caching**: Lazy-load memory context on explicit user action (section expand) rather than pre-fetching—avoids N+1 API calls on HITL list views. Use lazy-load-first (Hindsight recall) + append-only (JSONL events) for separated concerns over unified storage. In-memory cache, not file-backed, for process-lifetime scope. Client-side filtering compensates for server API limitations: over-request (limit + flagged count, capped at 2x) and discard stale locally.

**Deduplication and scoring**: Use consistent SHA-256 hashing (truncated to 16 chars) for dedup keys and recall hit tracking. Optional dedup parameter with `None` default preserves legacy behavior; passing `bank_labels=None` triggers original first-seen-wins logic. Dedup via asymmetric similarity `len(words & existing) / max(len(words), 1)` with configurable threshold (default 0.85, word-set overlap >70% avoids semantic LLM calls); higher threshold means fewer items removed. Batch load scoring data once per operation (call `MemoryScorer.load_item_scores()` once, reuse for all items) rather than per-item. Use consistent integer ID mapping across MemoryScorer.evict_items and MemorySyncWorker via formula: `abs(hash(str(item.get("id", ""))) % (10**9))`. Stable sort preserves original relevance order for equal combined scores.

**Preference learning**: Full preference learning pathway: regex match → ConversationTurn.signal → MEMORY_SUGGESTION block → MemorySuggester → dual-write (JSONL + Hindsight) → Bank.LEARNINGS → recall_safe wrapper → turn 0 prompt injection. Regex signal classification has documented priority-ordering bias (first-match-wins) causing false positives; future improvements could use LLM-based classification. Use full preference stats method (expose via public `get_preference_stats()`) to avoid route coupling to ShapePhase internal counters. Distinguish ephemeral vs persistent metrics in dashboard: recall attempt/hit counters are session-level (reset on restart), while signal distribution derives from persisted state.json. In-memory ephemeral metrics acceptable for operational dashboards; defer to StateTracker if persistence becomes required. Recall hit rate is simple proxy: recall_hits when Bank.LEARNINGS returns results, misses when empty.

**Hindsight integration**: `HindsightClient.retain()` coerces all metadata values via `str(v)`, so warnings/flags must be string `"true"`, not boolean `True`. Check via `metadata.get("warning") == "true"` which safely handles missing keys. Metadata-based filtering in sync workers uses tags (e.g., `adr_status: "superseded"`) to exclude items. When source is missing in historical entries, apply Tier 3 default (1.0x weight) via bank-based heuristics. Central injection in `retain_safe()` and `schedule_retain()` uses `setdefault`-style logic to avoid scattered coupling and non-breaking schema versioning.

**Staleness and contradiction**: Conservative contradiction detection: keyword heuristics with first-match-wins bias and 40% topic overlap threshold to reduce false positives. O(n²) pairwise comparison acceptable when n ≤ 50 items across 5 banks. Resolution priority: (1) provenance—human-sourced wins over agent-sourced regardless of timestamp; (2) recency—newer wins when equal provenance. Staleness detection emits events/logs rather than mutating state, allowing reversibility and operator visibility. Skip resources without timestamp metadata rather than flagging as stale. Stale store cleanup during periodic audits removes entries that no longer match current JSONL index to bound storage growth.

**Eviction and cleanup**: Memory eviction must update both item_scores.json and items.jsonl atomically. Operator-friendly admin output (e.g., `run_compact()`) should include total counts, candidate counts, and per-category breakdowns (auto_evict=N, needs_curation=N, keep=N). Track original positions before re-ranking to compute boost/demotion statistics. Metrics definition must sync across all computation paths (compute_rolling_averages, detect_regressions, and any other consumers). Establish consistent data enrichment expectations: functions should have consistent requirements about whether input is pre-enriched or self-enriching. Complete resource cleanup before setting closed flags (e.g., set cleanup state flags only after `aclose()` completes). Idempotent `close()` via `_closed` flag guard prevents double cleanup. Memory fingerprinting via `SHA-256(memory.display_text[:500])[:16]` is stable but monitors for orphan fingerprints if formatting changes. Dual-file persistence: JSONL for append-only logs, atomic JSON for computed state. Best-effort consistency for concurrent file-backed state: threading.Lock prevents corruption within single process, multi-process races acceptable since metrics are advisory.

See also: Concurrency and I/O safety — atomic write patterns and crash-safe file operations; Backward compatibility and schema evolution — metadata tag usage.


```json:entry
{"id":"01KQ11A4G90JQVA2ZA7FT25K9V","title":"Memory management","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T15:38:18.766132+00:00","updated_at":"2026-04-18T15:38:18.766133+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Documentation and ADR consistency

Keep CLAUDE.md and README in sync—they may diverge on details (e.g., 'five concurrent async loops' vs actual implementation). ADR files must have corresponding README entries to be canonically referenceable—files without README entries become invisible. When renaming fixtures/command files, preserve namespace prefixes (hf. or hf-) for consistency. Skill prompts replicated across four backend locations (src/diff_sanity.py, .claude/commands/, .pi/skills/, .codex/skills/) must stay in sync; missed updates cause inconsistent LLM behavior.

See also: Backward compatibility and schema evolution — schema documentation; Refactoring and testing practices — documentation standards.


```json:entry
{"id":"01KQ11A4G90JQVA2ZA7FT25K9W","title":"Documentation and ADR consistency","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T15:38:18.766135+00:00","updated_at":"2026-04-18T15:38:18.766136+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Kill-Switch Convention — enabled_cb at Top of _do_work

Every BaseBackgroundLoop subclass MUST gate _do_work on self._enabled_cb(self._worker_name) at the top of the method and return {'status': 'disabled'} when the callback returns False (ADR-0049). The base class's run() loop already gates enabled_cb before scheduling work, but that guard is bypassed in three real scenarios: (1) startup catchup path (_should_run_catchup → _execute_cycle calls _do_work without the sleep-time enabled_cb check); (2) direct test invocations of _do_work; (3) any future scheduler refactor. The in-body check makes the kill-switch behavior visible in tests that invoke _do_work directly via enabled_cb=lambda _: False. A config field (e.g. staging_enabled) may exist for dark-launch but must be an AND with enabled_cb, not a replacement; enabled_cb is the FIRST check. Verification: grep -l 'async def _do_work' src/*_loop.py | xargs grep -L 'self._enabled_cb' — any loop in the output is violating. See also: Trust Fleet Pattern; HITL Escalation Channel.


```json:entry
{"id":"01KQ11A4G670SNNXM1DDZ98XHZ","title":"Kill-Switch Convention — enabled_cb at Top of _do_work","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:40:54.022832+00:00","updated_at":"2026-04-25T00:40:54.022833+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## HITL Escalation Channel — `hitl-escalation` Label

Trust loops never page humans by any channel other than filing a GitHub issue with the `hitl-escalation` label (ADR-0045). A loop that cannot recover files exactly one escalation issue and stops re-filing until the operator resolves it. The escalation body must promise: 'closing this issue clears the attempt counter (§3.2 lifecycle)' — the promise is honored by _reconcile_closed_escalations on the next tick (which calls clear/reset on the relevant state counter when it sees the closed issue). Threshold-based escalation (e.g. principles_audit fires once at attempt threshold, not every tick after) requires checking the current counter BEFORE incrementing — past-threshold ticks must be no-ops until reconcile resets. Anomalies file with specific sub-labels (rc-red-attribution-unsafe, principles-stuck, flake-tracker-stuck, etc.) so operator queries can target a class. See also: DedupStore + Reconcile Pattern; Kill-Switch Convention.


```json:entry
{"id":"01KQ11A4G670SNNXM1DDZ98XJ1","title":"HITL Escalation Channel — `hitl-escalation` Label","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:40:54.022851+00:00","updated_at":"2026-04-25T00:40:54.022852+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Avoided Patterns

Common mistakes agents make in the HydraFlow codebase. These are semantic rules that linters and type checkers cannot catch — they require understanding the project's conventions and prior incidents. Read this doc before editing the areas each rule calls out.

This is the canonical location for avoided patterns. `CLAUDE.md` links here; do not duplicate rules back into `CLAUDE.md`. Sensors (`src/sensor_enricher.py`) and audit agents (`.claude/commands/hf.audit-code.md`) read this doc to coach agents during failures.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBA","title":"Avoided Patterns","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793202+00:00","updated_at":"2026-04-25T00:47:19.793203+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Underscore-prefixed names imported across modules

If a symbol is imported from another module, it is part of that module's public API and must not start with `_`. The leading underscore is Python's "module-internal" convention; crossing the boundary lies about the contract and trips pyright's `reportPrivateUsage` / unused-symbol warnings.

**Wrong:**

```python
# src/plugin_skill_registry.py
def _parse_plugin_spec(spec: str) -> tuple[str, str]: ...

# src/preflight.py
from plugin_skill_registry import _parse_plugin_spec  # crosses the boundary
```

**Right:**

```python
# src/plugin_skill_registry.py
def parse_plugin_spec(spec: str) -> tuple[str, str]: ...

# src/preflight.py
from plugin_skill_registry import parse_plugin_spec
```

**Why:** Pyright flags private-symbol imports and "defined but not used" warnings for `_`-prefixed names whose only consumers are other modules. Promotion to public is also a signal to future readers that the symbol is a load-bearing contract, not an implementation detail.

**How to check:** Any symbol imported across module boundaries must not start with `_`. If it does, rename or refactor in the same change.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBG","title":"Underscore-prefixed names imported across modules","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793253+00:00","updated_at":"2026-04-25T00:47:19.793254+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## `_name` for unused loop variables (prefer bare `_`)

Python's informal "unused by intent" convention is a bare `_`, not `_name`. Pyright and some strict linters treat `_name` as a named variable that happens to start with `_` and flag it as unused regardless.

**Wrong:**

```python
for _lang, name, marketplace in specs:
    install(name, marketplace)
# Pyright: "_lang" is not accessed
```

**Right:**

```python
for _, name, marketplace in specs:
    install(name, marketplace)
```

**Why:** Bare `_` is universally understood as "throwaway"; `_name` is not. Reserve `_name` only when documentation value is meaningful enough to keep a name alive. Otherwise use bare `_`.

**How to check:** `rg "for _[a-z]" src/` — each match should justify why the underscore-prefixed name is more readable than bare `_`.

---


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBM","title":"`_name` for unused loop variables (prefer bare `_`)","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793276+00:00","updated_at":"2026-04-25T00:47:19.793277+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Run and dev

```bash
make run            # Start backend + Vite frontend dev server
make dry-run        # Dry run (log actions without executing)
make clean          # Remove all worktrees and state
make status         # Show current HydraFlow state
make hot            # Send config update to running instance
```


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBS","title":"Run and dev","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793441+00:00","updated_at":"2026-04-25T00:47:19.793443+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## UI Development Standards

The React dashboard (`ui/`) uses inline styles in JSX. Follow these conventions.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PCE","title":"UI Development Standards","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793785+00:00","updated_at":"2026-04-25T00:47:19.793786+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## DRY principle

- Shared constants (`ACTIVE_STATUSES`, `PIPELINE_STAGES`) live in `ui/src/constants.js` — never duplicate.
- Type definitions in `ui/src/types.js`.
- Colors are CSS custom properties in `ui/index.html` `:root`, accessed via `ui/src/theme.js` — always use `theme.*` tokens, never raw hex or rgb values.
- Extract shared styles to reusable objects when used 3+ times.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PCG","title":"DRY principle","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793796+00:00","updated_at":"2026-04-25T00:47:19.793797+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Workflow for every code change

1. Create a worktree: `git worktree add ../hydraflow-worktrees/<name> origin/main`
2. Create a branch in the worktree: `git checkout -b <branch-name> origin/main`
3. Make changes, commit, and push the branch
4. Create a PR via `gh pr create`
5. Clean up: `git worktree remove ../hydraflow-worktrees/<name>`

**Do NOT use the `EnterWorktree` tool** — it auto-cleans up and loses work. Use manual `git worktree add` commands.


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PCM","title":"Workflow for every code change","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793868+00:00","updated_at":"2026-04-25T00:47:19.793868+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Conventions

- **Default location:** `../hydraflow-worktrees/` (sibling to repo root)
- **Naming:** `issue-{issue_number}/` for issue work, descriptive names for other changes
- **Config:** `worktree_base` field in `HydraFlowConfig` (`src/config.py`)
- **Cleanup:** `make clean` removes all worktrees and state
- Worktrees get independent venvs (`uv sync`), symlinked `.env`, and pre-commit hooks
- Stale worktrees from merged PRs should be periodically pruned with `git worktree prune`


```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PCN","title":"Conventions","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793873+00:00","updated_at":"2026-04-25T00:47:19.793874+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Sentry Alert Configuration for HydraFlow

# Sentry Alert Configuration for HydraFlow


```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249N","title":"Sentry Alert Configuration for HydraFlow","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794326+00:00","updated_at":"2026-04-25T00:47:19.794327+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Why This Is "Harnessed"

- No autonomous mutation of prompts/skills in-repo.
- Observation data is lightweight and local to the project.
- Retros produce explicit artifacts for human review.
- Promotion into durable memory still goes through `/hf.memory` and HITL.


```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249T","title":"Why This Is \"Harnessed\"","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794403+00:00","updated_at":"2026-04-25T00:47:19.794403+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
