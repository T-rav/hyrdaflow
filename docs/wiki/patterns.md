# Patterns


## Schema evolution with optional fields and type narrowing

Preserve backward compatibility through optional fields with sensible defaults and type narrowing on bare strings (safe if values already conform). Use StrEnum for auto-conversion. Pydantic v2 auto-coerces dicts from state.json; verify all call sites before narrowing union types. Establish single source of truth via canonical constants (e.g., `ALL_LIFECYCLE_LABEL_FIELDS`). Use metadata tags for categorization instead of enum variants. Make new fields optional with `.get()` defaults on read; no migration needed.

**Why:** Prevents deserialization failures and subtle logic bugs when callers expect different types than you assume.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJW6","title":"Schema evolution with optional fields and type narrowing","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404820+00:00","updated_at":"2026-05-03T03:56:15.404843+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Verify call sites before refactoring function signatures

Before changing function signatures, grep the codebase to find all call sites and confirm scope. For public functions, use `git grep` to verify zero remaining matches after refactoring. When return types change (e.g., `str | None` → `dict | None`), update all callers atomically in a single commit. Example: Before renaming a parameter or adding required arguments, run `git grep -l 'function_name' src/` and update each match.

**Why:** Missing even one call site causes `TypeError` at runtime, often caught only in production.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJW7","title":"Verify call sites before refactoring function signatures","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404881+00:00","updated_at":"2026-05-03T03:56:15.404883+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve public/semi-public method signatures during extraction

When tests or external code depend on a method signature, preserve it using thin delegation stubs, `__getattr__` facades, or mixin inheritance from shared base clients. Use optional parameters to gate composition logic when decomposing large methods rather than breaking the signature.

**Why:** Refactoring that breaks public contracts forces API consumers to break as well, increasing blast radius and breaking encapsulation.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJW8","title":"Preserve public/semi-public method signatures during extraction","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404895+00:00","updated_at":"2026-05-03T03:56:15.404897+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve error isolation during refactoring

Keep per-concern try/except blocks exactly as-is when extracting code to prevent failures in one concern from blocking others. Preserve early-return cases inline in the parent rather than extracting; extract to pure module-level functions first for independent testability.

**Why:** Splitting error handling across extracted code can mask failures and violate the assumption that isolated concerns don't cascade.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJW9","title":"Preserve error isolation during refactoring","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404909+00:00","updated_at":"2026-05-03T03:56:15.404911+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Mock at definition site, not import site

Mock at the definition site (e.g., `hindsight.tombstone_safe`) combined with deferred imports inside test methods—prevents import-time failures and keeps optional dependencies truly optional. When testing dependency injection, explicitly verify that the injected dependency is used instead of self-constructed.

**Why:** Import-site mocking fails if the module cannot be imported; definition-site mocking remains effective when the dependency is optional.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWA","title":"Mock at definition site, not import site","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404919+00:00","updated_at":"2026-05-03T03:56:15.404921+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use structural checks instead of isinstance() for protocol verification

Verify protocol implementation via structural subtype checks using `inspect.signature()` rather than `isinstance()`. When methods are moved during refactoring, retarget mock patches to the new location before refactoring.

**Why:** Structural checks allow duck-typed implementations to satisfy contracts; isinstance() requires explicit subclass relationships that may not exist.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWB","title":"Use structural checks instead of isinstance() for protocol verification","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404929+00:00","updated_at":"2026-05-03T03:56:15.404931+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Run existing tests unchanged after refactoring

After refactoring (especially extraction or decomposition), run all existing tests unchanged without modification. This is your primary regression test. Generated content in tests must not reference line numbers—use exact function/class names and string search for stability across refactors.

**Why:** Modifying tests during refactoring hides regressions; unchanged tests catch behavioral drift.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWC","title":"Run existing tests unchanged after refactoring","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404940+00:00","updated_at":"2026-05-03T03:56:15.404941+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use threading.Lock in thread pools, asyncio.Lock only for coroutines

Use `threading.Lock` when code runs in a thread pool (via `asyncio.to_thread()`) or is called from both sync and async contexts—`asyncio.Lock` is not thread-safe. Use `asyncio.Lock` only for coordinating pure coroutines. Extract `_unlocked()` helper variants to prevent re-entrant lock attempts.

**Why:** asyncio.Lock relies on event-loop context that is not preserved across thread boundaries, causing race conditions.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWD","title":"Use threading.Lock in thread pools, asyncio.Lock only for coroutines","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404949+00:00","updated_at":"2026-05-03T03:56:15.404951+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use crash-safe file I/O patterns for persistence

Use `file_util.append_jsonl()` wrapped in `file_lock()` for JSONL appends (includes `flush()` and `os.fsync()`). Use `file_util.atomic_write()` for critical state file updates (writes to temp, then `os.replace()` atomically). Use `os.replace()` for atomic JSONL rewrites when content is small. Lock files are zero-byte sentinels; overhead is negligible.

**Why:** Unprotected writes crash mid-flush and corrupt state; crash-safe patterns ensure atomicity and recoverability.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWE","title":"Use crash-safe file I/O patterns for persistence","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404959+00:00","updated_at":"2026-05-03T03:56:15.404961+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use claim-then-merge for async queue processing

Atomically claim items (clear/load), release lock, perform async work, re-acquire lock, reload for new items, merge with remaining, atomically write. Prevents lost entries when `write_all` overwrites file during async gap.

**Why:** Releasing the lock during async work creates a race window where other writers overwrite queued items.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWF","title":"Use claim-then-merge for async queue processing","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404969+00:00","updated_at":"2026-05-03T03:56:15.404971+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve tracing context lifecycle with try/finally

Set/clear or begin/end pairs for trace context MUST execute within a single try/finally block to prevent trace state leaks. If accidentally split during refactoring, trace state leaks across issues/iterations.

**Why:** Incomplete cleanup leaves stale trace state attached to the next request, corrupting observability logs.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWG","title":"Preserve tracing context lifecycle with try/finally","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404979+00:00","updated_at":"2026-05-03T03:56:15.404981+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Keep event publishing coupled with condition checks

Event publishing stays coupled with condition checks in the same method—do not separate event logic from condition checks. Separating them creates code paths where gates block but events don't fire, breaking observability.

**Why:** Decoupled publishing hides silent failures and makes debugging impossible when conditions change without emitting signals.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWH","title":"Keep event publishing coupled with condition checks","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.404992+00:00","updated_at":"2026-05-03T03:56:15.404994+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Preserve retry state during phase result extraction

When extracting phase result classification or handling logic, preserve exact retry counter state and escalation conditions (like epic-child label swaps) from the original flow. Dry-run mode must not emit state-changing events (e.g., TRIAGE_ROUTING). Run existing tests unchanged after refactoring as the primary regression test.

**Why:** Behavioral subtleties directly impact correctness of phase state transitions and deterministic escalation.


```json:entry
{"id":"01KQNZNK5CTPJHBXJBAJZ5XJWJ","title":"Preserve retry state during phase result extraction","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405002+00:00","updated_at":"2026-05-03T03:56:15.405003+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Maintain immutable return contracts in phase routing

Phase result routing through dispatch patterns must maintain the immutable return contract exactly (`tuple[str, str | None]` for `parse()`). Event/worker mappings must precede skip detection—implement `EVENT_TO_STAGE` and `SOURCE_TO_STAGE` together with skip detection logic.

**Why:** Changing return types or mapping precedence breaks downstream dispatch logic and causes state machine hangs.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DHZ","title":"Maintain immutable return contracts in phase routing","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405016+00:00","updated_at":"2026-05-03T03:56:15.405018+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Two-round memory budget allocation

Pre-allocate budget upfront before prompt assembly in `_inject_memory()`. Round one: each section gets its minimum. Round two: remaining budget distributes proportionally by priority (from `_DEFAULT_PRIORITIES`). Allocator sets hard maxes, not predicted lengths. Wiki budget is separate and deducted before redistribution. Consume allocations explicitly after `get_allocation()`.

**Why:** Post-hoc surplus reclamation is impossible; pre-allocation prevents over-spending and balances sections fairly.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ0","title":"Two-round memory budget allocation","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405027+00:00","updated_at":"2026-05-03T03:56:15.405028+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Lazy-load memory context on user action

Lazy-load memory context on explicit user action (section expand) rather than pre-fetching—avoids N+1 API calls on HITL list views. Use in-memory cache, not file-backed, for process-lifetime scope. Client-side filtering compensates for server API limitations: over-request (limit + flagged count, capped at 2x) and discard stale locally.

**Why:** Eager loading creates unbounded API calls and latency; lazy loading makes list views fast while expanding detail is still fast.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ1","title":"Lazy-load memory context on user action","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405037+00:00","updated_at":"2026-05-03T03:56:15.405038+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dedup memory items via SHA-256 hashing with threshold

Use consistent SHA-256 hashing (truncated to 16 chars) for dedup keys and recall hit tracking. Optional dedup parameter with `None` default preserves legacy behavior. Dedup via asymmetric similarity: `len(words & existing) / max(len(words), 1)` with configurable threshold (default 0.85). Higher threshold means fewer items removed.

**Why:** Semantic dedup via LLM is expensive; word-set overlap >70% catches practical duplicates without drift.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ2","title":"Dedup memory items via SHA-256 hashing with threshold","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405061+00:00","updated_at":"2026-05-03T03:56:15.405062+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Batch load scoring data once per operation

Load scoring data once per operation and reuse: call `MemoryScorer.load_item_scores()` once, reuse for all items rather than per-item. Use consistent integer ID mapping via formula: `abs(hash(str(item.get("id", ""))) % (10**9))`. Stable sort preserves original relevance order for equal scores.

**Why:** Per-item scoring multiplies I/O cost by item count; batch loading is linear and deterministic.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ3","title":"Batch load scoring data once per operation","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405071+00:00","updated_at":"2026-05-03T03:56:15.405075+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Full preference learning pathway

Regex match → ConversationTurn.signal → MEMORY_SUGGESTION block → MemorySuggester → dual-write (JSONL + Hindsight) → Bank.LEARNINGS → recall_safe wrapper → turn 0 prompt injection. Expose via public `get_preference_stats()` to avoid route coupling. Distinguish ephemeral vs persistent metrics: recall attempt/hit counters are session-level; signal distribution derives from persisted state.json.

**Why:** Full pathway ensures learned preferences flow through observation → storage → inference; partial pipelines break the feedback loop.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ4","title":"Full preference learning pathway","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405085+00:00","updated_at":"2026-05-03T03:56:15.405087+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Coerce Hindsight metadata values to strings

`HindsightClient.retain()` coerces all metadata values via `str(v)`, so warnings/flags must be string `"true"`, not boolean `True`. Check via `metadata.get("warning") == "true"` which safely handles missing keys. When source is missing in historical entries, apply Tier 3 default (1.0x weight). Use `setdefault`-style logic in central injection points.

**Why:** Hindsight's string coercion loses type information; string literals prevent silent conversion bugs.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ5","title":"Coerce Hindsight metadata values to strings","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405095+00:00","updated_at":"2026-05-03T03:56:15.405097+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Conservative contradiction detection with priority

Use keyword heuristics with 40% topic overlap threshold to reduce false positives. O(n²) pairwise comparison is acceptable when n ≤ 50 items. Resolution priority: (1) provenance—human-sourced wins over agent-sourced regardless of timestamp; (2) recency—newer wins with equal provenance. Skip resources without timestamp metadata. Stale cleanup during audits removes entries no longer matching current index.

**Why:** Semantic LLM-based detection is expensive; keyword heuristics catch obvious contradictions with low false-positive rate.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ6","title":"Conservative contradiction detection with priority","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405105+00:00","updated_at":"2026-05-03T03:56:15.405107+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Memory eviction updates both item scores and items atomically

Memory eviction must update both `item_scores.json` and `items.jsonl` atomically. Admin output (e.g., `run_compact()`) should include total counts, candidate counts, and per-category breakdowns. Track original positions before re-ranking to compute boost/demotion statistics. Metrics definition must sync across all computation paths.

**Why:** Partial eviction leaves orphan scores or items, corrupting dedup keys and recall statistics.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ7","title":"Memory eviction updates both item scores and items atomically","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405115+00:00","updated_at":"2026-05-03T03:56:15.405117+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Dual-file persistence: JSONL + atomic JSON

Use JSONL for append-only logs (e.g., events, observations), atomic JSON for computed state (e.g., item_scores.json, state.json). threading.Lock prevents corruption within single process; multi-process races acceptable since metrics are advisory. Complete resource cleanup before setting closed flags; idempotent `close()` via `_closed` flag guard prevents double cleanup.

**Why:** JSONL append is crash-safe; atomic JSON prevents partial-write state corruption. Dual-file separation isolates concerns.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ8","title":"Dual-file persistence: JSONL + atomic JSON","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405124+00:00","updated_at":"2026-05-03T03:56:15.405126+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Documentation consistency across CLAUDE.md and README

Keep CLAUDE.md and README in sync—they may diverge on details. ADR files must have corresponding README entries to be canonically referenceable; files without README entries become invisible. When renaming fixtures/command files, preserve namespace prefixes (hf. or hf-). Skill prompts replicated across four locations must stay in sync.

**Why:** Divergent documentation confuses users and creates hidden code paths that decay unnoticed.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJ9","title":"Documentation consistency across CLAUDE.md and README","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405134+00:00","updated_at":"2026-05-03T03:56:15.405135+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Kill-Switch Convention — enabled_cb at top of _do_work

Every `BaseBackgroundLoop` subclass MUST gate `_do_work` on `self._enabled_cb(self._worker_name)` at the top of the method, returning `{'status': 'disabled'}` when false (ADR-0049). This guards against startup catchup, direct test invocation, and future scheduler refactors. A config field (e.g., staging_enabled) is an AND with enabled_cb, not a replacement. Verify: `grep -l 'async def _do_work' src/*_loop.py | xargs grep -L 'self._enabled_cb'`.

**Why:** Enabled_cb at the call site is bypassed by catchup paths; in-body checks make kill-switch behavior testable.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJA","title":"Kill-Switch Convention — enabled_cb at top of _do_work","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405143+00:00","updated_at":"2026-05-03T03:56:15.405147+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## HITL Escalation Channel — hitl-escalation label

Trust loops never page humans except by filing a GitHub issue with the `hitl-escalation` label (ADR-0045). File exactly one escalation issue and stop re-filing until the operator resolves it. Body must promise: 'closing this issue clears the attempt counter'. Threshold-based escalation checks the counter BEFORE incrementing—past-threshold ticks are no-ops until reconciliation. Anomalies file with sub-labels (rc-red-attribution-unsafe, principles-stuck) for operator targeting.

**Why:** Multiple escalation issues overwhelm operators; single issue + counter reset via closure enforces discipline.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJB","title":"HITL Escalation Channel — hitl-escalation label","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405157+00:00","updated_at":"2026-05-03T03:56:15.405158+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Underscore-prefixed names are not public imports

If a symbol is imported from another module, it is part of that module's public API and must not start with `_`. Leading underscore is Python's 'module-internal' convention; crossing the boundary trips pyright's `reportPrivateUsage` warnings. Right: `from plugin_skill_registry import parse_plugin_spec` (rename from `_parse_plugin_spec`).

**Why:** Private-symbol imports confuse readers about intent and fail strict linter checks.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJC","title":"Underscore-prefixed names are not public imports","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405166+00:00","updated_at":"2026-05-03T03:56:15.405177+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Use bare _ for truly unused loop variables

Python's convention for unused variables is bare `_`, not `_name`. Pyright treats `_name` as a named variable and flags it as unused regardless. Right: `for _, name, marketplace in specs: ...` Wrong: `for _lang, name, marketplace in specs: ...`

**Why:** Bare `_` is universally understood; `_name` is ambiguous and fails linting.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJD","title":"Use bare _ for truly unused loop variables","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405186+00:00","updated_at":"2026-05-03T03:56:15.405188+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## DRY principle for frontend constants and styles

Shared constants live in `ui/src/constants.js`, type definitions in `ui/src/types.js`. Colors are CSS custom properties in `ui/index.html` `:root`, accessed via `ui/src/theme.js`—always use `theme.*` tokens, never raw hex or rgb values. Extract shared styles to reusable objects when used 3+ times.

**Why:** Duplication causes maintenance burden and style drift; single-source-of-truth constants sync across the UI.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJE","title":"DRY principle for frontend constants and styles","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405199+00:00","updated_at":"2026-05-03T03:56:15.405201+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Worktree workflow and conventions

Worktrees live at `../hydraflow-worktrees/` (sibling to repo root). Name by issue: `issue-{number}/` or descriptively for other changes. Worktrees get independent venvs (`uv sync`), symlinked `.env`, and pre-commit hooks. Stale worktrees from merged PRs should be pruned periodically with `git worktree prune`. Cleanup: `make clean` removes all worktrees and state.

**Why:** Standard naming and location make worktree state discoverable and prevent scattered work.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJF","title":"Worktree workflow and conventions","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405209+00:00","updated_at":"2026-05-03T03:56:15.405210+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Run and dev commands

`make run` starts backend + Vite frontend. `make dry-run` shows actions without executing. `make clean` removes all worktrees and state. `make status` shows current HydraFlow state. `make hot` sends config update to running instance.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJG","title":"Run and dev commands","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405218+00:00","updated_at":"2026-05-03T03:56:15.405220+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Why memory/observation is harnessed, not autonomous

No autonomous mutation of prompts/skills in-repo. Observation data is lightweight and local. Retros produce explicit artifacts for human review. Promotion into durable memory goes through `/hf.memory` and HITL.

**Why:** Harnessed design prevents drift and maintains human visibility into what the system learns.


```json:entry
{"id":"01KQNZNK5DWPQ75W9HBCJX2DJH","title":"Why memory/observation is harnessed, not autonomous","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-03T03:56:15.405227+00:00","updated_at":"2026-05-03T03:56:15.405229+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```


## Telemetry layer — OTel for traces, Sentry for exceptions

HydraFlow uses **OpenTelemetry → Honeycomb** for distributed tracing (per-phase / per-loop-tick / per-port-call spans with `hf.*` business attributes for BubbleUp-ready dimensionality) and **Sentry** for automatic uncaught-exception capture and stack-trace fingerprinting. The two are layered, not overlapping. Sentry's `before_send` hook filters transient errors; OTel decorators (`@runner_span()`, `@loop_span()`, `@port_span(name)`) emit spans that wrap business calls without altering control flow — every span operation is wrapped in `_safe_*` helpers that swallow telemetry exceptions while always re-raising business exceptions. `init_otel(config)` is called once from `server.py:main()` after `_init_sentry()`. When `config.otel_enabled=False`, the decorator stack is byte-identical to no decorators (regression-tested). All `hf.*` attributes flow through `add_hf_context()` — single source of truth, enforced by `tests/architecture/test_otel_invariants.py`. See ADR-0055 for the full architectural decision.

**Why:** Two telemetry channels with explicit roles prevent the failure mode where a single channel becomes "everything but really good at nothing." Sentry catches what we forgot to instrument; OTel gives us causal traces we can query and BubbleUp on. Phase B's anomaly-detection loop will read from Honeycomb; the question of whether to retire Sentry is deferred to that point with 30 days of data.


```json:entry
{"id":"01KQOTEL55HC2026B0PHASEA001","title":"Telemetry layer — OTel for traces, Sentry for exceptions","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-06T20:50:00.000000+00:00","updated_at":"2026-05-06T20:50:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```


## Branch protection — rulesets that enforce the two-tier model (ADR-0042)

`main` and `staging` are protected by GitHub **rulesets** (the modern replacement for classic branch protection rules), not by classic branch-protection settings. Always read these via `gh api /repos/T-rav/hydraflow/rulesets/<id>`, never via the classic `/branches/<name>/protection` endpoint (it returns 404 even when the branch is protected).

| Ruleset | ID | Target | Allowed merge methods | Required status checks |
|---|---|---|---|---|
| `main protect` | `15468404` | `~DEFAULT_BRANCH` (`main`) | `["merge"]` only — squash is rejected (ADR-0042 §Decision: squash from a long-lived integration branch produces a growing-diff regression). RC promotion uses `gh pr merge --merge`. | Full standard CI set + RC promotion gate: `Tests`, `Lint & Format`, `Type Check`, `Security Scan`, `Smoke Tests`, `Scenario Tests`, `Regression Tests`, `Principles Audit`, `ADR gate`, `quality (.)`, `quality (src/ui)`, **`Resolve RC PR`**, **`Browser Scenarios`**, **`Trust Gate (adversarial corpus, fixture mode)`**, **`Sandbox (rc/* promotion PR full suite)`**. The bold four are the MockWorld + e2e gate that only applies to `rc/* → main` PRs. |
| `staging protect` | `16066429` | `refs/heads/staging` | `["squash", "merge"]` — agent PRs squash by default; merges accepted for cross-branch fixups. | Full standard CI set + `Sandbox (PR→staging fast subset)`. The 11 standard checks above plus the staging-specific sandbox subset. No RC-only checks (those are conditional and would block on SKIPPED). |

Both rulesets also enforce: no deletion, no force-push, PR required (no direct pushes), code-quality severity=`errors`, code-scanning CodeQL high-or-higher.

Repo-level settings:
- `default_branch=main` (release reference; integration is `staging`)
- `allow_auto_merge=true` — required for `gh pr merge --auto` and for `StagingPromotionLoop` to queue auto-merges on RC PRs
- `allow_squash_merge=true`, `allow_merge_commit=true`, `allow_rebase_merge=true` — methods are gated per-branch by ruleset, not at repo level

To audit drift: `gh api /repos/T-rav/hydraflow/rulesets/15468404 | jq .rules` and same for `16066429`. Diff against [`docs/adr/0042-two-tier-branch-release-promotion.md`](../adr/0042-two-tier-branch-release-promotion.md).

**Why:** Encoding the decision in two rulesets (rather than docs alone) means the GitHub UI itself rejects squash-into-main and direct-push violations — convention that becomes infrastructure. The required-check sets enforce that nothing reaches `main` without the full MockWorld + e2e sandbox suite, and nothing reaches `staging` without the full standard CI gate.


```json:entry
{"id":"01KQRULESET2026B0PHASE2002","title":"Branch protection — rulesets that enforce the two-tier model (ADR-0042)","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-05-07T03:55:00.000000+00:00","updated_at":"2026-05-07T03:55:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```
