# Gotchas

## Code Quality, Imports, Types, and Refactoring


Verify imports are present and not circular before adding type annotations. Use TYPE_CHECKING guards with `from __future__ import annotations` for forward references. Before removing imports, grep for runtime references (isinstance, assignments) to prevent NameError. Run ruff to auto-fix import ordering.

Import ordering follows isort rules: stdlib (alphabetically, including pathlib), then third-party, then local. Use `is None` and `is not None` for optional objects, especially callables and stores. Type ignore comments can hide real bugs—investigate before suppressing.

Protocol conformance: method signatures must exactly match protocol definitions. When updating port signatures, sync all implementations simultaneously—one task, not staggered. When refactoring classes, enforce acceptance criteria of ≤400 lines and ≤15 public methods. Count carefully: remaining non-delegated methods + delegation stubs can exceed budget even after extraction.

Preserve edge cases like label ordering and removal order semantics. When removing multiple code blocks from same file, delete bottom-to-top (highest line numbers first) to avoid line-number shifting.

See also: Testing — validate type changes with ruff and typecheck; Infrastructure — type-checking applies to parser signatures.

```json:entry
{"id":"01KQ11NX7WPWJKP571R69KMCPT","title":"Code Quality, Imports, Types, and Refactoring","content":"Verify imports are present and not circular before adding type annotations. Use TYPE_CHECKING guards with `from __future__ import annotations` for forward references. Before removing imports, grep for runtime references (isinstance, assignments) to prevent NameError. Run ruff to auto-fix import ordering.\n\nImport ordering follows isort rules: stdlib (alphabetically, including pathlib), then third-party, then local. Use `is None` and `is not None` for optional objects, especially callables and stores. Type ignore comments can hide real bugs—investigate before suppressing.\n\nProtocol conformance: method signatures must exactly match protocol definitions. When updating port signatures, sync all implementations simultaneously—one task, not staggered. When refactoring classes, enforce acceptance criteria of ≤400 lines and ≤15 public methods. Count carefully: remaining non-delegated methods + delegation stubs can exceed budget even after extraction.\n\nPreserve edge cases like label ordering and removal order semantics. When removing multiple code blocks from same file, delete bottom-to-top (highest line numbers first) to avoid line-number shifting.\n\nSee also: Testing — validate type changes with ruff and typecheck; Infrastructure — type-checking applies to parser signatures.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T15:40:17.674355+00:00","updated_at":"2026-04-18T15:40:17.674424+00:00","valid_from":"2026-04-18T15:40:17.674355+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Testing — Mocking, Serialization, and File Verification


Always patch functions at their definition site (e.g., `hindsight.retain_safe`), not import site. Deferred imports break module-level mocks. Never attach methods dynamically to mock objects; use unittest.mock.patch() at definition site to validate actual function signatures and catch keyword argument typos.

Files referenced in issues may not exist (e.g., shared_prompt_prefix.py). Always verify file existence before planning changes using git history and grep.

For serialization testing, validate both model_dump_json()→model_validate_json() (serialization fidelity) and save/load cycles (full integration). JSON tests catch serialization bugs; integration tests catch type coercion and persistence issues.

Use explicit assertions on structured markers rather than narrative content to ensure test stability across agent output format changes. ID generation must have test coverage verifying consistency across lookups—ensure plans_dir keys and filename extractions use the same ID logic. Join factory metrics by issue_number, not pr_number.

When removing test imports/files referencing deleted code, run tests to surface incomplete cleanup. Always run `make test` and `make quality-lite` before declaring work complete—test failures naturally surface incomplete cleanup and hidden dependencies.

See also: Code Quality — type-checking applies to validators and imports; ID Generation — ID extraction and generation must be consistent; Infrastructure — parser assertions validate against realistic multi-paragraph output.

```json:entry
{"id":"01KQ11NX7WPWJKP571R69KMCPV","title":"Testing — Mocking, Serialization, and File Verification","content":"Always patch functions at their definition site (e.g., `hindsight.retain_safe`), not import site. Deferred imports break module-level mocks. Never attach methods dynamically to mock objects; use unittest.mock.patch() at definition site to validate actual function signatures and catch keyword argument typos.\n\nFiles referenced in issues may not exist (e.g., shared_prompt_prefix.py). Always verify file existence before planning changes using git history and grep.\n\nFor serialization testing, validate both model_dump_json()→model_validate_json() (serialization fidelity) and save/load cycles (full integration). JSON tests catch serialization bugs; integration tests catch type coercion and persistence issues.\n\nUse explicit assertions on structured markers rather than narrative content to ensure test stability across agent output format changes. ID generation must have test coverage verifying consistency across lookups—ensure plans_dir keys and filename extractions use the same ID logic. Join factory metrics by issue_number, not pr_number.\n\nWhen removing test imports/files referencing deleted code, run tests to surface incomplete cleanup. Always run `make test` and `make quality-lite` before declaring work complete—test failures naturally surface incomplete cleanup and hidden dependencies.\n\nSee also: Code Quality — type-checking applies to validators and imports; ID Generation — ID extraction and generation must be consistent; Infrastructure — parser assertions validate against realistic multi-paragraph output.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T15:40:17.674453+00:00","updated_at":"2026-04-18T15:40:17.674457+00:00","valid_from":"2026-04-18T15:40:17.674453+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Exception Classification, Logging, and Error Handling


Distinguish bug exceptions (TypeError, AttributeError, KeyError, ValueError, IndexError) from transient errors (RuntimeError, OSError, CalledProcessError, httpx network exceptions) using log_exception_with_bug_classification() or is_likely_bug(). Use logger.exception() only for genuine bugs; transient operational failures use logger.warning(..., exc_info=True). In finally blocks, use log_exception_with_bug_classification() instead of reraise to preserve finally semantics.

For HTTP errors, use reraise_on_credit_or_bug() to selectively re-raise critical exceptions (AuthenticationError, CreditExhaustedError, MemoryError) while logging transient failures. Subprocess exceptions: TimeoutExpired and CalledProcessError are siblings, not parent-child—both must be caught separately. Read-path methods return safe defaults; write-path methods propagate TimeoutExpired to prevent silent data loss.

Logging strategy follows docs/agents/sentry.md: transient failures log at WARNING; LoggingIntegration(event_level=logging.ERROR) prevents spurious Sentry alerts. Data-integrity violations log at ERROR. Avoid silent `except Exception: pass`; use reraise_on_credit_or_bug(exc) + logger.warning(..., exc_info=True). When migrating from logger.exception() to logger.warning(), explicitly add exc_info=True or tracebacks disappear.

In retry loops, wrap per-item API calls in try/except so one item's failure doesn't abort the cycle. In background loops, classify exceptions: fatal (auth/credit) propagates, bugs (local logic) propagate, transient (per-item runtime) logged as warnings. When a loop encounters 5 consecutive failures of the same type, circuit breaker publishes SYSTEM_ALERT exactly once.

Post-merge orchestration runs sequential operations: merge→verify→retrospect→epic check→state record→event publish→cleanup. Exception handling only catches (RuntimeError, OSError, ValueError); others propagate. Use run_with_fatal_guard pattern from phase_utils for consistent logging.

Async/await: Omitting await on async methods returns unawaited coroutines that silently never execute—Pyright flags these during make typecheck. asyncio.create_task() calls without stored references get garbage-collected, silently dropping exceptions. Store all create_task results and add done callbacks for logging. Implement safe background task pattern: add private `_background_tasks: set[asyncio.Task[None]]`. Register cleanup callback before logging callback. When re-raising fatal errors from async tasks, revert dependent state flags (e.g., _pipeline_enabled = False) BEFORE raising to ensure state consistency.

See also: Telemetry — apply exception classification to distinguish bugs from transient errors; Memory System — apply same classification during memory injection; State Persistence — exception handling during state transitions.

```json:entry
{"id":"01KQ11NX7WPWJKP571R69KMCPW","title":"Exception Classification, Logging, and Error Handling","content":"Distinguish bug exceptions (TypeError, AttributeError, KeyError, ValueError, IndexError) from transient errors (RuntimeError, OSError, CalledProcessError, httpx network exceptions) using log_exception_with_bug_classification() or is_likely_bug(). Use logger.exception() only for genuine bugs; transient operational failures use logger.warning(..., exc_info=True). In finally blocks, use log_exception_with_bug_classification() instead of reraise to preserve finally semantics.\n\nFor HTTP errors, use reraise_on_credit_or_bug() to selectively re-raise critical exceptions (AuthenticationError, CreditExhaustedError, MemoryError) while logging transient failures. Subprocess exceptions: TimeoutExpired and CalledProcessError are siblings, not parent-child—both must be caught separately. Read-path methods return safe defaults; write-path methods propagate TimeoutExpired to prevent silent data loss.\n\nLogging strategy follows docs/agents/sentry.md: transient failures log at WARNING; LoggingIntegration(event_level=logging.ERROR) prevents spurious Sentry alerts. Data-integrity violations log at ERROR. Avoid silent `except Exception: pass`; use reraise_on_credit_or_bug(exc) + logger.warning(..., exc_info=True). When migrating from logger.exception() to logger.warning(), explicitly add exc_info=True or tracebacks disappear.\n\nIn retry loops, wrap per-item API calls in try/except so one item's failure doesn't abort the cycle. In background loops, classify exceptions: fatal (auth/credit) propagates, bugs (local logic) propagate, transient (per-item runtime) logged as warnings. When a loop encounters 5 consecutive failures of the same type, circuit breaker publishes SYSTEM_ALERT exactly once.\n\nPost-merge orchestration runs sequential operations: merge→verify→retrospect→epic check→state record→event publish→cleanup. Exception handling only catches (RuntimeError, OSError, ValueError); others propagate. Use run_with_fatal_guard pattern from phase_utils for consistent logging.\n\nAsync/await: Omitting await on async methods returns unawaited coroutines that silently never execute—Pyright flags these during make typecheck. asyncio.create_task() calls without stored references get garbage-collected, silently dropping exceptions. Store all create_task results and add done callbacks for logging. Implement safe background task pattern: add private `_background_tasks: set[asyncio.Task[None]]`. Register cleanup callback before logging callback. When re-raising fatal errors from async tasks, revert dependent state flags (e.g., _pipeline_enabled = False) BEFORE raising to ensure state consistency.\n\nSee also: Telemetry — apply exception classification to distinguish bugs from transient errors; Memory System — apply same classification during memory injection; State Persistence — exception handling during state transitions.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T15:40:17.674465+00:00","updated_at":"2026-04-18T15:40:17.674467+00:00","valid_from":"2026-04-18T15:40:17.674465+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## State Persistence, Configuration, and Resource Cleanup


Config validators (e.g., labels_must_not_be_empty covering all label fields) serve as source of truth for audit fields. Mismatch between validator field set and audit field enumeration indicates a bug. When fixing label removal bugs, add regression tests explicitly verifying those fields by name. Fixing code doesn't retroactively clean existing issues—post-deployment manual cleanup may be needed.

When adding new list[str] label fields to HydraFlowConfig, always add as optional ConfigFactory.create() parameters with sensible defaults. Omitting causes TypeError. Add test that ConfigFactory.create() accepts all label fields. Validate collection fields accessed by index—downstream code accesses [0] without null-checking. Constructor parameters must require before optional: use `param: Type | None = None` with fallback logic.

For state persistence, use append-only reflection files (JSONL) to accumulate data across retries, avoiding schema migrations. Mark entries with structural boundaries (timestamps, phase separators). Implement explicit cleanup methods at logical boundaries to prevent unbounded growth. Wrap all JSONL I/O in try/except OSError; append operations must be idempotent to survive partial writes. Use file_util.atomic_write() instead of Path.write_text() to prevent JSON corruption from crashes mid-write. Hard size caps (e.g., 10MB) provide secondary guards. trim_jsonl operates on raw lines without JSON parsing; corrupt/malformed records survive trimming intentionally.

For schema evolution, new Pydantic model fields with `field: Type = default_value` allow existing state files to load without error. TypedDict(total=False) enables backward-compatible event payloads where all fields are optional. Frozen Pydantic models require object.__setattr__ for mutation—critical in overrides (numeric, bool, literal) to avoid breaking setter logic. Cross-field validation must run after numeric overrides but before bool/literal overrides.

When persisting to multiple banks (repo-specific + universal), use single Write-Ahead Log (WAL) to capture all writes together for atomic failure recovery. Type coercion across serialization boundaries: HindsightClient coerces metadata values to strings during retain while local JSONL keeps int. Wrap type conversions in try/except catching (TypeError, ValueError) with fallback to None.

Idempotency guards protect against duplicate calls and retries, not concurrent execution. Per-issue locking at orchestrator level prevents true concurrency. When removing config fields, removed env-var overrides should be silently ignored. Validate field removal by letting tests fail on missing attributes. When HydraFlow manages itself (repo_root == HydraFlow repo), use hash-based or idempotent installation to skip if identical. Critical in multi-execution-mode systems.

When extracting methods that compute intermediate state needed by failure paths, return tuples `(success, mergeable)` rather than recomputing. State transitions create atomicity windows for exceptions: when exceptions occur after successful state transition (e.g., label swap) but before cleanup, issues can get stuck in intermediate states. Mitigation: wrap transition+operation+cleanup in try/except that reverses transitions on non-fatal exceptions. Track resource creation state to enable safe cleanup—only attempt destroy if setup successfully created the resource. HITL workflows should destroy worktrees only on success, preserving them on failure to enable post-mortem debugging.

See also: Exception Classification — exception handling during state transitions; Testing — validate schema evolution with serialization tests.

```json:entry
{"id":"01KQ11NX7WPWJKP571R69KMCPX","title":"State Persistence, Configuration, and Resource Cleanup","content":"Config validators (e.g., labels_must_not_be_empty covering all label fields) serve as source of truth for audit fields. Mismatch between validator field set and audit field enumeration indicates a bug. When fixing label removal bugs, add regression tests explicitly verifying those fields by name. Fixing code doesn't retroactively clean existing issues—post-deployment manual cleanup may be needed.\n\nWhen adding new list[str] label fields to HydraFlowConfig, always add as optional ConfigFactory.create() parameters with sensible defaults. Omitting causes TypeError. Add test that ConfigFactory.create() accepts all label fields. Validate collection fields accessed by index—downstream code accesses [0] without null-checking. Constructor parameters must require before optional: use `param: Type | None = None` with fallback logic.\n\nFor state persistence, use append-only reflection files (JSONL) to accumulate data across retries, avoiding schema migrations. Mark entries with structural boundaries (timestamps, phase separators). Implement explicit cleanup methods at logical boundaries to prevent unbounded growth. Wrap all JSONL I/O in try/except OSError; append operations must be idempotent to survive partial writes. Use file_util.atomic_write() instead of Path.write_text() to prevent JSON corruption from crashes mid-write. Hard size caps (e.g., 10MB) provide secondary guards. trim_jsonl operates on raw lines without JSON parsing; corrupt/malformed records survive trimming intentionally.\n\nFor schema evolution, new Pydantic model fields with `field: Type = default_value` allow existing state files to load without error. TypedDict(total=False) enables backward-compatible event payloads where all fields are optional. Frozen Pydantic models require object.__setattr__ for mutation—critical in overrides (numeric, bool, literal) to avoid breaking setter logic. Cross-field validation must run after numeric overrides but before bool/literal overrides.\n\nWhen persisting to multiple banks (repo-specific + universal), use single Write-Ahead Log (WAL) to capture all writes together for atomic failure recovery. Type coercion across serialization boundaries: HindsightClient coerces metadata values to strings during retain while local JSONL keeps int. Wrap type conversions in try/except catching (TypeError, ValueError) with fallback to None.\n\nIdempotency guards protect against duplicate calls and retries, not concurrent execution. Per-issue locking at orchestrator level prevents true concurrency. When removing config fields, removed env-var overrides should be silently ignored. Validate field removal by letting tests fail on missing attributes. When HydraFlow manages itself (repo_root == HydraFlow repo), use hash-based or idempotent installation to skip if identical. Critical in multi-execution-mode systems.\n\nWhen extracting methods that compute intermediate state needed by failure paths, return tuples `(success, mergeable)` rather than recomputing. State transitions create atomicity windows for exceptions: when exceptions occur after successful state transition (e.g., label swap) but before cleanup, issues can get stuck in intermediate states. Mitigation: wrap transition+operation+cleanup in try/except that reverses transitions on non-fatal exceptions. Track resource creation state to enable safe cleanup—only attempt destroy if setup successfully created the resource. HITL workflows should destroy worktrees only on success, preserving them on failure to enable post-mortem debugging.\n\nSee also: Exception Classification — exception handling during state transitions; Testing — validate schema evolution with serialization tests.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T15:40:17.674477+00:00","updated_at":"2026-04-18T15:40:17.674480+00:00","valid_from":"2026-04-18T15:40:17.674477+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## ID Generation, Representation, and Pipeline Ordering


Use consistent ID generation logic everywhere files are keyed (e.g., plans_dir / f'issue-{issue.id}.md') to avoid silent lookup failures. Define prefix lengths as constants (discover=9, shape=6) and centralize extraction to prevent off-by-one slice errors that silently produce NaN. Join factory metrics and reviews by issue_number (not pr_number). Issue number propagation before memory injection enables outcome correlation across phases; reset to 0 after injection.

Avoid implicit heuristics like `if fname not in content` for self-exclusion. Pass explicit parameters (self_fname) to filter functions instead—this makes logic clearer and prevents silent edge cases. Collision detection must explicitly exclude self before reporting to avoid misleading messages.

Representation gaps indicate multiple object models in codebase. Example: ReviewRunner uses Task.id while phase_utils.publish_review_status uses pr.issue_number for same concept. Document which representation a helper uses and scope it appropriately. Mixed usage should be consolidated to single representation or explicitly mapped.

Stage progression logic relying on array indices (currentStage from PIPELINE_STAGES position) is fragile. New stages inserted at incorrect positions silently break progression if only status values are verified in tests. When adding pipeline stages, verify both stage ordering and progression logic—order matters even if status values are correct.

For skip detection, only trigger when stage at index ≥3 (plan or later) has non-pending status. If issue is in triage (triage=active, discover/shape=pending), discover/shape must remain pending, not marked skipped.

Phase progression occurs via predictable label mutations (discover→shape, shape→plan). Clarity scoring gates entry: high-clarity issues (≥7) go directly to planning; vague issues route to discovery first. This deterministic approach makes phase progression observable in issue history, eliminating hidden state and making system auditable.

See also: Testing — ID generation must have test coverage verifying consistency across lookups.

```json:entry
{"id":"01KQ11NX7WPWJKP571R69KMCPY","title":"ID Generation, Representation, and Pipeline Ordering","content":"Use consistent ID generation logic everywhere files are keyed (e.g., plans_dir / f'issue-{issue.id}.md') to avoid silent lookup failures. Define prefix lengths as constants (discover=9, shape=6) and centralize extraction to prevent off-by-one slice errors that silently produce NaN. Join factory metrics and reviews by issue_number (not pr_number). Issue number propagation before memory injection enables outcome correlation across phases; reset to 0 after injection.\n\nAvoid implicit heuristics like `if fname not in content` for self-exclusion. Pass explicit parameters (self_fname) to filter functions instead—this makes logic clearer and prevents silent edge cases. Collision detection must explicitly exclude self before reporting to avoid misleading messages.\n\nRepresentation gaps indicate multiple object models in codebase. Example: ReviewRunner uses Task.id while phase_utils.publish_review_status uses pr.issue_number for same concept. Document which representation a helper uses and scope it appropriately. Mixed usage should be consolidated to single representation or explicitly mapped.\n\nStage progression logic relying on array indices (currentStage from PIPELINE_STAGES position) is fragile. New stages inserted at incorrect positions silently break progression if only status values are verified in tests. When adding pipeline stages, verify both stage ordering and progression logic—order matters even if status values are correct.\n\nFor skip detection, only trigger when stage at index ≥3 (plan or later) has non-pending status. If issue is in triage (triage=active, discover/shape=pending), discover/shape must remain pending, not marked skipped.\n\nPhase progression occurs via predictable label mutations (discover→shape, shape→plan). Clarity scoring gates entry: high-clarity issues (≥7) go directly to planning; vague issues route to discovery first. This deterministic approach makes phase progression observable in issue history, eliminating hidden state and making system auditable.\n\nSee also: Testing — ID generation must have test coverage verifying consistency across lookups.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T15:40:17.674486+00:00","updated_at":"2026-04-18T15:40:17.674492+00:00","valid_from":"2026-04-18T15:40:17.674486+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Telemetry — Sample Size Validation and Outcome Tracking


Minimum sample sizes prevent statistical misleading and enable reliable recommendations. For telemetry, use thresholds like 10 for regressions and window_size for rolling averages; for memory quality assessment, return empty results when recall data is insufficient. Always expose sample_size alongside metrics (fp_rate, recall quality) to flag sparse data—1/2=50% is noisy with high over-interpretation risk.

Record each retry attempt separately to capture timing and retry patterns, but aggregate using (skill_name, issue_number) with only final attempt's outcome for pass-rate calculations. Naive per-attempt counting inflates failure rates. In retry loops with state accumulators, pass current-attempt to telemetry (not accumulator) to avoid contaminating aggregates with stale failure signals from previous attempts.

Outcomes attach to digest snapshots, not individual recalled items. Cap issue_ids per recall hit at 50 entries to bridge outcomes with actual recall events. Blocking skill failures trigger agent retries until they pass, so passed=False records are rare; non-blocking skills are primary false-positive candidates.

See also: Exception Classification — classify failures to distinguish bugs from transient errors.

```json:entry
{"id":"01KQ11NX7WPWJKP571R69KMCPZ","title":"Telemetry — Sample Size Validation and Outcome Tracking","content":"Minimum sample sizes prevent statistical misleading and enable reliable recommendations. For telemetry, use thresholds like 10 for regressions and window_size for rolling averages; for memory quality assessment, return empty results when recall data is insufficient. Always expose sample_size alongside metrics (fp_rate, recall quality) to flag sparse data—1/2=50% is noisy with high over-interpretation risk.\n\nRecord each retry attempt separately to capture timing and retry patterns, but aggregate using (skill_name, issue_number) with only final attempt's outcome for pass-rate calculations. Naive per-attempt counting inflates failure rates. In retry loops with state accumulators, pass current-attempt to telemetry (not accumulator) to avoid contaminating aggregates with stale failure signals from previous attempts.\n\nOutcomes attach to digest snapshots, not individual recalled items. Cap issue_ids per recall hit at 50 entries to bridge outcomes with actual recall events. Blocking skill failures trigger agent retries until they pass, so passed=False records are rare; non-blocking skills are primary false-positive candidates.\n\nSee also: Exception Classification — classify failures to distinguish bugs from transient errors.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T15:40:17.674498+00:00","updated_at":"2026-04-18T15:40:17.674501+00:00","valid_from":"2026-04-18T15:40:17.674498+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Memory System — Filtering, Budget Allocation, and Query Optimization


Filter evicted memories on both content prefix ('[EVICTED]') AND metadata status ('status: evicted'). Dual filtering ensures tombstones never leak into agent prompts even if one filter has bugs. Apply filters at recall time in _inject_memory() before formatting. Treat budget allocation as cap, not target. Cross-section dedup runs after truncation, so final prompt may be smaller than allocated budget. Dedup savings below budget ceiling are acceptable and expected—not failure case.

For prompt feedback sections with exemplars, place exemplars before remediation hints to ensure exemplars survive truncation. Phase-specific query customization should prepend context (`f"{prefix}, {context}"`) rather than replace it. Narrowing queries too much degrades recall quality. Additive prefixes guide semantic search while preserving original issue context needed for relevance matching. Relevance score boost uses in-place mutation (mem.relevance_score *= 1.15)—monitor this constraint during dependency upgrades.

See also: Exception Classification — classify failures in memory injection to distinguish bugs from transient errors.

```json:entry
{"id":"01KQ11NX7WPWJKP571R69KMCQ0","title":"Memory System — Filtering, Budget Allocation, and Query Optimization","content":"Filter evicted memories on both content prefix ('[EVICTED]') AND metadata status ('status: evicted'). Dual filtering ensures tombstones never leak into agent prompts even if one filter has bugs. Apply filters at recall time in _inject_memory() before formatting. Treat budget allocation as cap, not target. Cross-section dedup runs after truncation, so final prompt may be smaller than allocated budget. Dedup savings below budget ceiling are acceptable and expected—not failure case.\n\nFor prompt feedback sections with exemplars, place exemplars before remediation hints to ensure exemplars survive truncation. Phase-specific query customization should prepend context (`f\"{prefix}, {context}\"`) rather than replace it. Narrowing queries too much degrades recall quality. Additive prefixes guide semantic search while preserving original issue context needed for relevance matching. Relevance score boost uses in-place mutation (mem.relevance_score *= 1.15)—monitor this constraint during dependency upgrades.\n\nSee also: Exception Classification — classify failures in memory injection to distinguish bugs from transient errors.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T15:40:17.674506+00:00","updated_at":"2026-04-18T15:40:17.674509+00:00","valid_from":"2026-04-18T15:40:17.674506+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## ADR Enforcement, Commit Hooks, and Skills Management


Enforcement ADRs need explicit tier-to-mechanism mapping (pre-commit hook, linter, test suite, manual review) with distinct statuses for items with tracking issues vs. those requiring new issues. Consequences sections must cross-check tracking status against decision tables—verify item-by-item that all proposed items have clear tracking. Avoid conflating 'tracked' with 'needs issue'.

Commit message validation should only block commits that *attempt* specific format incorrectly (e.g., Fix instead of Fixes). Allow plain commits without issue refs, WIP prefixes, merge commits, reverts, and auto-generated commits. This avoids blocking agents that make multiple intermediate commits during implementation.

New dynamic skills start with blocking=False to avoid breaking workflows. Skills graduate to blocking=True only after ≥20 runs with ≥95% success rate. This policy ensures new automated checks are proven before failing builds.

Extract workflow concepts (TDD, systematic debugging, review rigor) and hardcode them in PHASE_SKILL_GUIDANCE dict rather than dynamically loading from filesystem. This avoids dependency on superpowers installation path and keeps system self-contained. New phases need dict entries, not filesystem discovery. TOOL_PHASE_MAP registration is ongoing maintenance burden—add lint test warning on unknown commands in .claude/commands/ to catch unregistered tools before shipping.

```json:entry
{"id":"01KQ11NX7WPWJKP571R69KMCQ1","title":"ADR Enforcement, Commit Hooks, and Skills Management","content":"Enforcement ADRs need explicit tier-to-mechanism mapping (pre-commit hook, linter, test suite, manual review) with distinct statuses for items with tracking issues vs. those requiring new issues. Consequences sections must cross-check tracking status against decision tables—verify item-by-item that all proposed items have clear tracking. Avoid conflating 'tracked' with 'needs issue'.\n\nCommit message validation should only block commits that *attempt* specific format incorrectly (e.g., Fix instead of Fixes). Allow plain commits without issue refs, WIP prefixes, merge commits, reverts, and auto-generated commits. This avoids blocking agents that make multiple intermediate commits during implementation.\n\nNew dynamic skills start with blocking=False to avoid breaking workflows. Skills graduate to blocking=True only after ≥20 runs with ≥95% success rate. This policy ensures new automated checks are proven before failing builds.\n\nExtract workflow concepts (TDD, systematic debugging, review rigor) and hardcode them in PHASE_SKILL_GUIDANCE dict rather than dynamically loading from filesystem. This avoids dependency on superpowers installation path and keeps system self-contained. New phases need dict entries, not filesystem discovery. TOOL_PHASE_MAP registration is ongoing maintenance burden—add lint test warning on unknown commands in .claude/commands/ to catch unregistered tools before shipping.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T15:40:17.674515+00:00","updated_at":"2026-04-18T15:40:17.674517+00:00","valid_from":"2026-04-18T15:40:17.674515+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Infrastructure — Events, Dispatch, and Parser Implementation


Alpine's minimal tooling excludes Python and standard utilities. Use portable shell commands like `dd if=/dev/zero bs=1M count=32 of=/dev/null` or `head -c` to consume memory in constrained environments, avoiding allocation failures from missing interpreter tools.

Event dispatch dicts benefit from separating truly silent events from events that produce no display output but set a result value (e.g., agent_end, turn_end set result but print nothing). Use _SILENT_WITH_RESULT frozenset checked before _SILENT_EVENTS to correctly route these cases. Handlers must have uniform signatures (event: dict) -> str to avoid type checker errors. This pattern complements exception-based signaling in background loops where fatal errors propagate via exception and supervisor routes the outcome.

When a general method returns insufficient data for specific use case, create separate specialized method rather than overloading general one. Example: `list_issues_by_label` returns basic issue metadata; `get_issue_updated_at()` handles timestamps separately. This keeps methods focused and avoids coupling unrelated concerns.

Explicitly document top 3-5 failure risks in plan phase before implementation. This identifies potential issues early and guides implementer decisions. Pre-mortems catch mistakes before code review and establish concrete failure modes to guard against during implementation.

Validate parsers against realistic multi-paragraph agent output containing both prose and structured markers—not bare marker strings. Test assertions focus on markers themselves, not prose wording, so transcript updates don't break tests. Maintain explicit assertions on structured markers rather than narrative content. Explicit `## Output Format` sections in markdown skill definitions (with 'do not modify without updating parser' warnings) make the contract visible. Maintain SKILL_MARKERS mapping for consistency and add test cases verifying all 4 backend copies match.

When extracting from Claude CLI transcripts, modified files, or external formats, use best-effort regex with try/except wrapping—never raise on parse failure. Log warnings when extraction finds zero matches on non-empty input to catch format drift early. Fall back to empty lists or default values on JSONDecodeError and other parsing errors. Leverage existing utilities like delta_verifier.parse_file_delta() and task_graph.extract_phases() instead of reimplementing.

CLI command framework passes $ARGUMENTS as everything after command name—verify scope routing with both single-word and multi-word arguments. Markdown splitting on '\n- ' double-prefixes first item ('- - ')—_split_md_items() helper must explicitly fix this edge case.

See also: Code Quality — type-checking applies to parser signatures; Testing — parser assertions validate against realistic multi-paragraph output.

```json:entry
{"id":"01KQ11NX7X22EWJCR8DMZTS2PG","title":"Infrastructure — Events, Dispatch, and Parser Implementation","content":"Alpine's minimal tooling excludes Python and standard utilities. Use portable shell commands like `dd if=/dev/zero bs=1M count=32 of=/dev/null` or `head -c` to consume memory in constrained environments, avoiding allocation failures from missing interpreter tools.\n\nEvent dispatch dicts benefit from separating truly silent events from events that produce no display output but set a result value (e.g., agent_end, turn_end set result but print nothing). Use _SILENT_WITH_RESULT frozenset checked before _SILENT_EVENTS to correctly route these cases. Handlers must have uniform signatures (event: dict) -> str to avoid type checker errors. This pattern complements exception-based signaling in background loops where fatal errors propagate via exception and supervisor routes the outcome.\n\nWhen a general method returns insufficient data for specific use case, create separate specialized method rather than overloading general one. Example: `list_issues_by_label` returns basic issue metadata; `get_issue_updated_at()` handles timestamps separately. This keeps methods focused and avoids coupling unrelated concerns.\n\nExplicitly document top 3-5 failure risks in plan phase before implementation. This identifies potential issues early and guides implementer decisions. Pre-mortems catch mistakes before code review and establish concrete failure modes to guard against during implementation.\n\nValidate parsers against realistic multi-paragraph agent output containing both prose and structured markers—not bare marker strings. Test assertions focus on markers themselves, not prose wording, so transcript updates don't break tests. Maintain explicit assertions on structured markers rather than narrative content. Explicit `## Output Format` sections in markdown skill definitions (with 'do not modify without updating parser' warnings) make the contract visible. Maintain SKILL_MARKERS mapping for consistency and add test cases verifying all 4 backend copies match.\n\nWhen extracting from Claude CLI transcripts, modified files, or external formats, use best-effort regex with try/except wrapping—never raise on parse failure. Log warnings when extraction finds zero matches on non-empty input to catch format drift early. Fall back to empty lists or default values on JSONDecodeError and other parsing errors. Leverage existing utilities like delta_verifier.parse_file_delta() and task_graph.extract_phases() instead of reimplementing.\n\nCLI command framework passes $ARGUMENTS as everything after command name—verify scope routing with both single-word and multi-word arguments. Markdown splitting on '\\n- ' double-prefixes first item ('- - ')—_split_md_items() helper must explicitly fix this edge case.\n\nSee also: Code Quality — type-checking applies to parser signatures; Testing — parser assertions validate against realistic multi-paragraph output.","topic":null,"source_type":"compiled","source_issue":null,"source_repo":null,"created_at":"2026-04-18T15:40:17.674522+00:00","updated_at":"2026-04-18T15:40:17.674525+00:00","valid_from":"2026-04-18T15:40:17.674522+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## `logger.error(value)` without a format string


Logging calls must pass a format string as the first argument and the variable as the second. Passing a variable directly treats the variable as the format template — if it ever contains `%s`, `%d`, or `{...}`, logging either misformats or raises `TypeError` at runtime.

**Wrong:**

```python
for failure in failures:
    logger.error(failure)  # failure is the format string — unsafe
```

**Right:**

```python
for failure in failures:
    logger.error("%s", failure)
```

**Why:** Latent logging-injection bug. `logger.error("got error: %s")` with a user-controlled string containing `%d` raises `TypeError: not enough arguments for format string` at runtime, not during testing. The `logger.error("%s", value)` form defers formatting to the logging machinery which handles it safely.

**How to check:** `rg "logger\.(error|warning|info|debug)\(\w+\)" src/` — every match should have a literal string as the first argument.

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBJ","title":"`logger.error(value)` without a format string","content":"Logging calls must pass a format string as the first argument and the variable as the second. Passing a variable directly treats the variable as the format template — if it ever contains `%s`, `%d`, or `{...}`, logging either misformats or raises `TypeError` at runtime.\n\n**Wrong:**\n\n```python\nfor failure in failures:\n    logger.error(failure)  # failure is the format string — unsafe\n```\n\n**Right:**\n\n```python\nfor failure in failures:\n    logger.error(\"%s\", failure)\n```\n\n**Why:** Latent logging-injection bug. `logger.error(\"got error: %s\")` with a user-controlled string containing `%d` raises `TypeError: not enough arguments for format string` at runtime, not during testing. The `logger.error(\"%s\", value)` form defers formatting to the logging machinery which handles it safely.\n\n**How to check:** `rg \"logger\\.(error|warning|info|debug)\\(\\w+\\)\" src/` — every match should have a literal string as the first argument.","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793265+00:00","updated_at":"2026-04-25T00:47:19.793266+00:00","valid_from":"2026-04-25T00:47:19.793265+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Per-worker model overrides


Each background worker that dispatches an LLM call has its own `HYDRAFLOW_*_MODEL` env var so it can be tuned independently for cost. Most loops are logic-only (no LLM call) and don't appear here.

| Loop | Config field | Env var | Default |
|------|--------------|---------|---------|
| `report_issue_loop` | `report_issue_model` | `HYDRAFLOW_REPORT_ISSUE_MODEL` | `opus` |
| `sentry_loop` | `sentry_model` | `HYDRAFLOW_SENTRY_MODEL` | `opus` |
| `code_grooming_loop` | `code_grooming_model` | `HYDRAFLOW_CODE_GROOMING_MODEL` | `sonnet` |
| `adr_reviewer_loop` (council) | `adr_review_model` | `HYDRAFLOW_ADR_REVIEW_MODEL` | `sonnet` |
| tribal-memory judge | `memory_judge_model` | `HYDRAFLOW_MEMORY_JUDGE_MODEL` | `haiku` |
| memory_sync compaction | `memory_compaction_model` | `HYDRAFLOW_MEMORY_COMPACTION_MODEL` | `haiku` |
| wiki compaction | `wiki_compilation_model` | `HYDRAFLOW_WIKI_COMPILATION_MODEL` | `haiku` |
| transcript summarizer | `transcript_summary_model` | `HYDRAFLOW_TRANSCRIPT_SUMMARY_MODEL` | `haiku` |

`HYDRAFLOW_BACKGROUND_MODEL` is a cascade: when non-empty it applies to every field above that still equals its own default (`triage_model`, `transcript_summary_model`, `report_issue_model`, `sentry_model`, `code_grooming_model`). Per-worker overrides always win over the cascade.

When adding a new loop that makes LLM calls, add its own `HYDRAFLOW_<NAME>_MODEL` field to `src/config.py` and `_ENV_STR_OVERRIDES` — don't reuse an existing loop's field.

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBQ","title":"Per-worker model overrides","content":"Each background worker that dispatches an LLM call has its own `HYDRAFLOW_*_MODEL` env var so it can be tuned independently for cost. Most loops are logic-only (no LLM call) and don't appear here.\n\n| Loop | Config field | Env var | Default |\n|------|--------------|---------|---------|\n| `report_issue_loop` | `report_issue_model` | `HYDRAFLOW_REPORT_ISSUE_MODEL` | `opus` |\n| `sentry_loop` | `sentry_model` | `HYDRAFLOW_SENTRY_MODEL` | `opus` |\n| `code_grooming_loop` | `code_grooming_model` | `HYDRAFLOW_CODE_GROOMING_MODEL` | `sonnet` |\n| `adr_reviewer_loop` (council) | `adr_review_model` | `HYDRAFLOW_ADR_REVIEW_MODEL` | `sonnet` |\n| tribal-memory judge | `memory_judge_model` | `HYDRAFLOW_MEMORY_JUDGE_MODEL` | `haiku` |\n| memory_sync compaction | `memory_compaction_model` | `HYDRAFLOW_MEMORY_COMPACTION_MODEL` | `haiku` |\n| wiki compaction | `wiki_compilation_model` | `HYDRAFLOW_WIKI_COMPILATION_MODEL` | `haiku` |\n| transcript summarizer | `transcript_summary_model` | `HYDRAFLOW_TRANSCRIPT_SUMMARY_MODEL` | `haiku` |\n\n`HYDRAFLOW_BACKGROUND_MODEL` is a cascade: when non-empty it applies to every field above that still equals its own default (`triage_model`, `transcript_summary_model`, `report_issue_model`, `sentry_model`, `code_grooming_model`). Per-worker overrides always win over the cascade.\n\nWhen adding a new loop that makes LLM calls, add its own `HYDRAFLOW_<NAME>_MODEL` field to `src/config.py` and `_ENV_STR_OVERRIDES` — don't reuse an existing loop's field.","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793363+00:00","updated_at":"2026-04-25T00:47:19.793364+00:00","valid_from":"2026-04-25T00:47:19.793363+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Hindsight recall — disable / re-enable


Phase 3 PR 9 ships with `hindsight_recall_enabled=True` by default. To
flip off during the 2-week observation window while validating that the
wiki-based system catches everything Hindsight was catching:

```bash
export HYDRAFLOW_HINDSIGHT_RECALL_ENABLED=false
```

To re-enable (rollback):

```bash
unset HYDRAFLOW_HINDSIGHT_RECALL_ENABLED
```

Retains (writes to Hindsight) remain active — only reads are gated. The
archive keeps accumulating so nothing is lost during the observation
window.

Metrics to watch on the dashboard (`/api/wiki/metrics`):

- `wiki_entries_ingested` should climb at approximately the rate of
  plan/implement/review cycles.
- `wiki_supersedes` should be non-zero within a few days (proves the
  contradiction detector is active).
- `tribal_promotions` will be zero until ≥2 active target repos share
  a principle (may stay zero indefinitely with only one managed repo).
- `reflections_bridged` should increment once per target-repo issue
  merge.
- `adr_drafts_judged` / `adr_drafts_opened` are non-zero only when
  agents have emitted `ADR_DRAFT_SUGGESTION` blocks.

Also watch `/api/wiki/health` — `store: populated` and (with ≥2 repos)
`tribal: populated` indicate the stores are being used.

Issue auto-merge rate should be stable within ±10% of the pre-change
baseline. Error rate should not change.

If divergence or regressions appear, unset the env var and file an
issue; do not proceed to the Hindsight deletion (Phase 3 PR 10) until
the gap is understood.

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PBZ","title":"Hindsight recall — disable / re-enable","content":"Phase 3 PR 9 ships with `hindsight_recall_enabled=True` by default. To\nflip off during the 2-week observation window while validating that the\nwiki-based system catches everything Hindsight was catching:\n\n```bash\nexport HYDRAFLOW_HINDSIGHT_RECALL_ENABLED=false\n```\n\nTo re-enable (rollback):\n\n```bash\nunset HYDRAFLOW_HINDSIGHT_RECALL_ENABLED\n```\n\nRetains (writes to Hindsight) remain active — only reads are gated. The\narchive keeps accumulating so nothing is lost during the observation\nwindow.\n\nMetrics to watch on the dashboard (`/api/wiki/metrics`):\n\n- `wiki_entries_ingested` should climb at approximately the rate of\n  plan/implement/review cycles.\n- `wiki_supersedes` should be non-zero within a few days (proves the\n  contradiction detector is active).\n- `tribal_promotions` will be zero until ≥2 active target repos share\n  a principle (may stay zero indefinitely with only one managed repo).\n- `reflections_bridged` should increment once per target-repo issue\n  merge.\n- `adr_drafts_judged` / `adr_drafts_opened` are non-zero only when\n  agents have emitted `ADR_DRAFT_SUGGESTION` blocks.\n\nAlso watch `/api/wiki/health` — `store: populated` and (with ≥2 repos)\n`tribal: populated` indicate the stores are being used.\n\nIssue auto-merge rate should be stable within ±10% of the pre-change\nbaseline. Error rate should not change.\n\nIf divergence or regressions appear, unset the env var and file an\nissue; do not proceed to the Hindsight deletion (Phase 3 PR 10) until\nthe gap is understood.","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793474+00:00","updated_at":"2026-04-25T00:47:19.793475+00:00","valid_from":"2026-04-25T00:47:19.793474+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Code review before merge


**After creating a PR, always self-review it for gaps, bugs, and test coverage before declaring it done.** Use `/superpowers:requesting-code-review` to run a structured review that checks:

- **Gaps** — Missing edge cases, unhandled error paths, callers not updated for API changes
- **Bugs** — Logic errors, off-by-one, race conditions, injection risks
- **Test coverage** — Missing boundary tests, untested code paths, missing negative cases

Do not present a PR as ready until the review passes and any findings are addressed.

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PC3","title":"Code review before merge","content":"**After creating a PR, always self-review it for gaps, bugs, and test coverage before declaring it done.** Use `/superpowers:requesting-code-review` to run a structured review that checks:\n\n- **Gaps** — Missing edge cases, unhandled error paths, callers not updated for API changes\n- **Bugs** — Logic errors, off-by-one, race conditions, injection risks\n- **Test coverage** — Missing boundary tests, untested code paths, missing negative cases\n\nDo not present a PR as ready until the review passes and any findings are addressed.","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793553+00:00","updated_at":"2026-04-25T00:47:19.793554+00:00","valid_from":"2026-04-25T00:47:19.793553+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Reasoning triggers


For analysis-heavy tasks (architecture decisions, debugging, code review), use explicit reasoning prompts to trigger deeper analysis:

- "Think through the tradeoffs of this approach before implementing"
- "Consider what could go wrong and what edge cases exist"
- "Explain your reasoning before making changes"

Simple mechanical tasks (rename, format, move) don't need these — just do them.

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PC4","title":"Reasoning triggers","content":"For analysis-heavy tasks (architecture decisions, debugging, code review), use explicit reasoning prompts to trigger deeper analysis:\n\n- \"Think through the tradeoffs of this approach before implementing\"\n- \"Consider what could go wrong and what edge cases exist\"\n- \"Explain your reasoning before making changes\"\n\nSimple mechanical tasks (rename, format, move) don't need these — just do them.","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793559+00:00","updated_at":"2026-04-25T00:47:19.793559+00:00","valid_from":"2026-04-25T00:47:19.793559+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Sentry Error Tracking


HydraFlow uses **Sentry** (`sentry_sdk`) for error monitoring. Follow these rules to keep Sentry signal-to-noise high.

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PC6","title":"Sentry Error Tracking","content":"HydraFlow uses **Sentry** (`sentry_sdk`) for error monitoring. Follow these rules to keep Sentry signal-to-noise high.","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793626+00:00","updated_at":"2026-04-25T00:47:19.793627+00:00","valid_from":"2026-04-25T00:47:19.793626+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## What goes to Sentry


- **Real code bugs only.** `TypeError`, `KeyError`, `AttributeError`, `ValueError`, `IndexError`, `NotImplementedError`.
- The `before_send` filter in `src/server.py` drops all exceptions that are NOT in the bug-types tuple.
- `LoggingIntegration` captures `logger.error()` calls — these also go through the `before_send` filter.

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PC7","title":"What goes to Sentry","content":"- **Real code bugs only.** `TypeError`, `KeyError`, `AttributeError`, `ValueError`, `IndexError`, `NotImplementedError`.\n- The `before_send` filter in `src/server.py` drops all exceptions that are NOT in the bug-types tuple.\n- `LoggingIntegration` captures `logger.error()` calls — these also go through the `before_send` filter.","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793632+00:00","updated_at":"2026-04-25T00:47:19.793633+00:00","valid_from":"2026-04-25T00:47:19.793632+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## What does NOT go to Sentry


- **Transient errors** — network timeouts, auth failures, rate limits, subprocess crashes. These are operational, not bugs.
- **Handled exceptions** — if you catch an error and handle it, use `logger.warning()`, not `logger.error()` or `logger.exception()`.
- **Test mock exceptions** — never let test mocks raise through code paths that log at `error` level when `SENTRY_DSN` is set.

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PC8","title":"What does NOT go to Sentry","content":"- **Transient errors** — network timeouts, auth failures, rate limits, subprocess crashes. These are operational, not bugs.\n- **Handled exceptions** — if you catch an error and handle it, use `logger.warning()`, not `logger.error()` or `logger.exception()`.\n- **Test mock exceptions** — never let test mocks raise through code paths that log at `error` level when `SENTRY_DSN` is set.","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793638+00:00","updated_at":"2026-04-25T00:47:19.793639+00:00","valid_from":"2026-04-25T00:47:19.793638+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Rules for new code


1. Use `logger.warning()` for expected or transient failures (network, auth, rate limit).
2. Use `logger.error()` or `logger.exception()` ONLY for unexpected code bugs you want Sentry to capture.
3. Never use bare `except: pass` — always log at `warning` level minimum.
4. When adding a new background loop, catch operational errors and log at `warning`; let real bugs propagate to the base class error handler which logs at `error`.
5. The `_before_send` callback in `src/server.py` is the gatekeeper — if you add new exception types that indicate real bugs, add them to `_BUG_TYPES`.
6. The `SentryIngestLoop` in `src/sentry_loop.py` polls Sentry for unresolved issues and files them as GitHub issues — avoid creating noise that feeds back into this loop.

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PC9","title":"Rules for new code","content":"1. Use `logger.warning()` for expected or transient failures (network, auth, rate limit).\n2. Use `logger.error()` or `logger.exception()` ONLY for unexpected code bugs you want Sentry to capture.\n3. Never use bare `except: pass` — always log at `warning` level minimum.\n4. When adding a new background loop, catch operational errors and log at `warning`; let real bugs propagate to the base class error handler which logs at `error`.\n5. The `_before_send` callback in `src/server.py` is the gatekeeper — if you add new exception types that indicate real bugs, add them to `_BUG_TYPES`.\n6. The `SentryIngestLoop` in `src/sentry_loop.py` polls Sentry for unresolved issues and files them as GitHub issues — avoid creating noise that feeds back into this loop.","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793644+00:00","updated_at":"2026-04-25T00:47:19.793646+00:00","valid_from":"2026-04-25T00:47:19.793644+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Never skip commit hooks


**NEVER** use `git commit --no-verify` or `--no-hooks` flags. If a hook fails, investigate and fix the underlying issue — do not bypass it.

```json:entry
{"id":"01KQ11NX7HJCH34WSSAFMB0PCP","title":"Never skip commit hooks","content":"**NEVER** use `git commit --no-verify` or `--no-hooks` flags. If a hook fails, investigate and fix the underlying issue — do not bypass it.","topic":"gotchas","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.793878+00:00","updated_at":"2026-04-25T00:47:19.793879+00:00","valid_from":"2026-04-25T00:47:19.793878+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Scenario Matrix


### Happy Paths (`test_happy.py`)

| # | Scenario | Asserts |
|---|----------|---------|
| H1 | Single issue end-to-end | find -> triage -> plan -> implement -> review -> done, PR merged |
| H2 | Multi-issue concurrent batch (3 issues) | All complete independently, no cross-contamination |
| H3 | HITL round-trip | Issue escalates to HITL, correction submitted, resumes |
| H4 | Review approve + merge | APPROVE verdict, CI passes, PR merged, cleanup runs |
| H5 | Plan produces sub-issues | Planner returns `new_issues`, sub-issues created |

### Sad Paths (`test_sad.py`)

| # | Scenario | Asserts |
|---|----------|---------|
| S1 | Plan fails then succeeds on retry | First plan `success=False`, retry succeeds |
| S2 | Implement exhausts attempts | Docker fails N times, issue does not complete |
| S3 | Review rejects -> route-back | REQUEST_CHANGES, routes back, re-review approves |
| S4 | GitHub API 5xx during PR creation | `fail_service("github")` mid-implement, recovery on heal |
| S5 | Hindsight down -> pipeline continues | Memory calls fail, pipeline completes without writes |
| S6 | CI fails -> auto-fix -> CI passes | `wait_for_ci` returns failure first, then passes |

### Edge Cases (`test_edge.py`)

| # | Scenario | Asserts |
|---|----------|---------|
| E1 | Duplicate issues (same title/body) | Both tracked by number, no crash |
| E2 | Issue relabeled mid-flight | `on_phase` hook fires, pipeline continues |
| E3 | Stale worktree during active processing | GC skips actively-processing issues |
| E4 | Epic with child ordering | Parent waits for children, dependency order |
| E5 | Zero-diff implement (already satisfied) | Agent produces 0 commits, `success=True` |

### Background Loop Scenarios (`test_loops.py`)

| # | Loop | Scenario | Asserts |
|---|------|----------|---------|
| L1 | HealthMonitor | Low first_pass_rate triggers config bump | `max_quality_fix_attempts` increased, decision audit written |
| L2 | WorkspaceGC | Cleans stale worktrees | Closed-issue worktrees destroyed, active preserved |
| L3 | StaleIssueGC | Closes inactive HITL issues | Old HITL issues auto-closed with comment, fresh untouched |
| L4 | PRUnsticker | Processes HITL items with open PRs | Unstick attempted on qualifying items |
| L5 | CIMonitor | CI failure creates issue | GitHub issue created with `hydraflow-ci-failure` label |
| L6 | CIMonitor | CI recovery closes issue | Failure issue auto-closed on green CI |
| L7 | DependabotMerge | Auto-merges bot PR on CI pass | PR approved, merged, processed set updated |
| L8 | DependabotMerge | Skips bot PR on CI failure | PR not merged, skip recorded |

```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ2494","title":"Scenario Matrix","content":"### Happy Paths (`test_happy.py`)\n\n| # | Scenario | Asserts |\n|---|----------|---------|\n| H1 | Single issue end-to-end | find -> triage -> plan -> implement -> review -> done, PR merged |\n| H2 | Multi-issue concurrent batch (3 issues) | All complete independently, no cross-contamination |\n| H3 | HITL round-trip | Issue escalates to HITL, correction submitted, resumes |\n| H4 | Review approve + merge | APPROVE verdict, CI passes, PR merged, cleanup runs |\n| H5 | Plan produces sub-issues | Planner returns `new_issues`, sub-issues created |\n\n### Sad Paths (`test_sad.py`)\n\n| # | Scenario | Asserts |\n|---|----------|---------|\n| S1 | Plan fails then succeeds on retry | First plan `success=False`, retry succeeds |\n| S2 | Implement exhausts attempts | Docker fails N times, issue does not complete |\n| S3 | Review rejects -> route-back | REQUEST_CHANGES, routes back, re-review approves |\n| S4 | GitHub API 5xx during PR creation | `fail_service(\"github\")` mid-implement, recovery on heal |\n| S5 | Hindsight down -> pipeline continues | Memory calls fail, pipeline completes without writes |\n| S6 | CI fails -> auto-fix -> CI passes | `wait_for_ci` returns failure first, then passes |\n\n### Edge Cases (`test_edge.py`)\n\n| # | Scenario | Asserts |\n|---|----------|---------|\n| E1 | Duplicate issues (same title/body) | Both tracked by number, no crash |\n| E2 | Issue relabeled mid-flight | `on_phase` hook fires, pipeline continues |\n| E3 | Stale worktree during active processing | GC skips actively-processing issues |\n| E4 | Epic with child ordering | Parent waits for children, dependency order |\n| E5 | Zero-diff implement (already satisfied) | Agent produces 0 commits, `success=True` |\n\n### Background Loop Scenarios (`test_loops.py`)\n\n| # | Loop | Scenario | Asserts |\n|---|------|----------|---------|\n| L1 | HealthMonitor | Low first_pass_rate triggers config bump | `max_quality_fix_attempts` increased, decision audit written |\n| L2 | WorkspaceGC | Cleans stale worktrees | Closed-issue worktrees destroyed, active preserved |\n| L3 | StaleIssueGC | Closes inactive HITL issues | Old HITL issues auto-closed with comment, fresh untouched |\n| L4 | PRUnsticker | Processes HITL items with open PRs | Unstick attempted on qualifying items |\n| L5 | CIMonitor | CI failure creates issue | GitHub issue created with `hydraflow-ci-failure` label |\n| L6 | CIMonitor | CI recovery closes issue | Failure issue auto-closed on green CI |\n| L7 | DependabotMerge | Auto-merges bot PR on CI pass | PR approved, merged, processed set updated |\n| L8 | DependabotMerge | Skips bot PR on CI failure | PR not merged, skip recorded |","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794046+00:00","updated_at":"2026-04-25T00:47:19.794047+00:00","valid_from":"2026-04-25T00:47:19.794046+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Scenario Catalog (Extended)


### Realistic-Agent Scenarios (`test_agent_realistic.py`)

| ID | Test | What it covers |
|----|------|----------------|
| A0 | `test_A0_happy_path_realistic_agent` | Base happy path: one issue, real AgentRunner, FakeDocker commits, merges. |
| A1 | `test_A1_docker_timeout_fails_issue_no_retry` | Docker timeout — production does NOT retry; issue fails with `worker_result.success=False`. |
| A2 | `test_A2_oom_fails_issue` | OOM (exit_code=137) causes agent failure; zero commits → `_verify_result` fails. |
| A3 | `test_A3_malformed_stream_recovers_to_failure` | Garbage stream events plus exit_code=1 — StreamParser skips unknowns, result is failure. |
| A4 | `test_A4_unknown_event_type_ignored_stream_continues` | `auth_retry_required` event silently skipped; trailing `result:success` still merges issue. |
| A5 | `test_A5_token_budget_exceeded_halts_implement` | Stream-level `budget_exceeded` event plus failure result → issue fails without merge. |
| A6 | `test_A6_github_rate_limit_at_triage_halts_pipeline` | Rate-limit armed before triage (remaining=0) — first GitHub call raises, pool absorbs, no PR created. |
| A7 | `test_A7_github_secondary_rate_limit_surfaces` | Secondary (abuse-detection) rate-limit is also absorbed; issue never progresses. |
| A8 | `test_A8_find_stage_to_done_realistic_agent` | Full pipeline from `hydraflow-find` through triage→plan→implement→review; issue merges. |
| A9 | `test_A9_hindsight_failure_realistic_agent_still_succeeds` | `fail_service('hindsight')` during realistic-agent run does not halt pipeline; issue merges. |
| A10 | `test_A10_quality_fix_loop_retries_then_passes` | `make quality` fails on first attempt; quality-fix agent commits fix; second quality run passes; merges. |
| A11 | `test_A11_review_fix_ci_loop_resolves` | CI fails after PR creation; `fix_ci` loop resolves it; CI passes; merge proceeds. |
| A12 | `test_A12_multi_commit_implement` | Real agent produces 3 commits; `git rev-list --count` confirms all three on branch. |
| A13 | `test_A13_zero_diff_fails_without_merge` | Agent claims success but writes no commits; `_verify_result` fails on commit count; no merge. |
| A14 | `test_A14_three_issues_concurrent_realistic` | Three issues processed concurrently via real AgentRunner; all merge; worktree isolation verified. |
| A15 | `test_A15_epic_decomposition_creates_children` | High-complexity issue decomposed via EpicManager stub; two child issues created in FakeGitHub. |
| A16 | `test_A16_credit_exhausted_halts_pipeline` | `CreditExhaustedError` from `_execute` propagates out of `run_pipeline` (re-raise allowlist). |
| A17 | `test_A17_authentication_error_halts_pipeline` | `AuthenticationError` from `_execute` propagates out of `run_pipeline` (re-raise allowlist). |
| A18 | `test_A18_rate_limit_heals_mid_pipeline` | Rate-limit armed with remaining=5; `on_phase("implement")` heals before it matters; merges. |
| A19 | `test_A19_code_scanning_alerts_reach_reviewer` | `add_alerts(branch=...)` seeds alerts; ReviewPhase fetches by branch; reviewer receives them unchanged. |
| A20 | `test_A20_workspace_create_permission_failure` | `PermissionError` from workspace creation is swallowed; issue does not merge; run_pipeline returns normally. |
| A20b | `test_A20b_workspace_create_disk_full` | `OSError(ENOSPC)` from FakeWorkspace is swallowed gracefully; issue does not merge. |
| A20c | `test_A20c_workspace_create_branch_conflict` | `RuntimeError` ("worktree already exists") from FakeWorkspace is swallowed; issue does not merge. |
| A21 | `test_A21_state_json_corruption_graceful_fallback` | Corrupt state.json before run; `StateTracker.load` falls back to empty `StateData()`; pipeline continues. |
| A22 | `test_A22_wiki_populated_plan_consults_it` | Pre-populated `RepoWikiStore` wired to `PlanPhase`; wiki accessible; pipeline completes without crash. |

**Boot smoke** (`test_realistic_agent_boot_smoke.py`): `test_real_agent_runner_single_event_smoke` — single invocation with tool_use + message + result events; proves the AgentRunner wiring stack boots.

### Bead Workflow Scenarios (`test_bead_workflow.py`)

| ID | Test | What it covers |
|----|------|----------------|
| B1 | `test_B1_bead_workflow_end_to_end` | Plan with Task Graph headers creates 2 beads; implement calls `init`; tasks stay open (claim/close are agent-subprocess concerns). |
| B1b | `test_B1_no_beads_without_task_graph_headers` | Plan text without `### P{N}` headers → `extract_phases` returns []; no beads created; `_initialized` stays False. |

### Background Loop Scenarios (`test_loops.py` + `test_caretaker_loops.py` + `test_caretaker_loops_part2.py`)

#### L1–L8 (`test_loops.py`)

| # | Loop | Scenario | Asserts |
|---|------|----------|---------|
| L1 | HealthMonitor | Low first_pass_rate triggers config bump | `max_quality_fix_attempts` increased, decision audit written |
| L2 | WorkspaceGC | Cleans stale worktrees | Closed-issue worktrees destroyed, active preserved |
| L3 | StaleIssueGC | Closes inactive HITL issues | Old HITL issues auto-closed with comment, fresh untouched |
| L4 | PRUnsticker | Processes HITL items with open PRs | Unstick attempted on qualifying items |
| L5 | CIMonitor | CI failure creates issue | GitHub issue created with `hydraflow-ci-failure` label |
| L6 | CIMonitor | CI recovery closes issue | Failure issue auto-closed on green CI |
| L7 | DependabotMerge | Auto-merges bot PR on CI pass | PR approved, merged, processed set updated |
| L8 | DependabotMerge | Skips bot PR on CI failure | PR not merged, skip recorded |

#### L9–L13 (`test_caretaker_loops.py`)

| ID | Class | What it covers |
|----|-------|----------------|
| L9 | `TestL9ADRReviewerLoop` | `ADRReviewerLoop._do_work` delegates to `adr_reviewer.review_proposed_adrs`; stats pass through; None passthrough preserved. |
| L10 | `TestL10MemorySyncLoop` | `MemorySyncLoop._do_work` calls `sync()` then `publish_sync_event(result)`; returned stats are a fresh copy. |
| L11 | `TestL11RetrospectiveLoop` | `RetrospectiveLoop` drains queue; empty queue → zero stats; `RETRO_PATTERNS` item → processed=1, acknowledged. |
| L12 | `TestL12EpicSweeperLoop` | `EpicSweeperLoop` sweeps open epics; no epics → zero counts; epic with all closed sub-issues auto-closed. |
| L13 | `TestL13SecurityPatchLoop` | `SecurityPatchLoop` files issues from Dependabot alerts; no alerts → filed=0; high-severity fixable → filed=1; dry_run → None. |

#### L14–L23 (`test_caretaker_loops_part2.py`)

| ID | Class | What it covers |
|----|-------|----------------|
| L14 | `TestL14CodeGrooming` | `CodeGroomingLoop`: disabled → `{"skipped": "disabled"}`; dry_run → None; enabled with no findings → stats shape with `"filed"` key. |
| L15 | `TestL15DiagnosticLoop` | `DiagnosticLoop` polls `hydraflow-diagnose` issues; no issues → zero counts; issue without escalation context → escalated=1. |
| L16 | `TestL16EpicMonitorLoop` | `EpicMonitorLoop` delegates to `EpicManager`; no stale epics → stale_count=0; 3 stale + 5 tracked → stats match. |
| L17 | `TestL17GitHubCacheLoop` | `GitHubCacheLoop` calls `cache.poll()` and forwards its stats; empty dict result → None (falsy guard). |
| L18 | `TestL18RepoWikiLoop` | `RepoWikiLoop` lints per-repo wikis; no repos → zero stats; one repo → `active_lint` called, stale_entries reflected. |
| L19 | `TestL19ReportIssueLoop` | `ReportIssueLoop` processes queued bug reports; dry_run → None; empty queue → None. |
| L20 | `TestL20RunsGCLoop` | `RunsGCLoop` purges expired/oversized runs; no artifacts → zero purge; 3 expired + 1 oversized → stats match. |
| L21 | `TestL21SentryLoop` | `SentryLoop` skips gracefully without credentials; empty org or empty token → `skipped=True` with reason. |
| L22 | `TestL22StagingPromotionLoop` | `StagingPromotionLoop`: disabled → `status=staging_disabled`; cadence not elapsed → `status=cadence_not_elapsed`; elapsed → RC branch cut, promotion PR opened. |
| L23 | `TestL23StaleIssueLoop` | `StaleIssueLoop` auto-closes stale issues; no issues → zero; fresh issue → scanned but not closed; stale + dry_run → closed=1, no API call; fetch failure → zero stats. |

---

```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ2499","title":"Scenario Catalog (Extended)","content":"### Realistic-Agent Scenarios (`test_agent_realistic.py`)\n\n| ID | Test | What it covers |\n|----|------|----------------|\n| A0 | `test_A0_happy_path_realistic_agent` | Base happy path: one issue, real AgentRunner, FakeDocker commits, merges. |\n| A1 | `test_A1_docker_timeout_fails_issue_no_retry` | Docker timeout — production does NOT retry; issue fails with `worker_result.success=False`. |\n| A2 | `test_A2_oom_fails_issue` | OOM (exit_code=137) causes agent failure; zero commits → `_verify_result` fails. |\n| A3 | `test_A3_malformed_stream_recovers_to_failure` | Garbage stream events plus exit_code=1 — StreamParser skips unknowns, result is failure. |\n| A4 | `test_A4_unknown_event_type_ignored_stream_continues` | `auth_retry_required` event silently skipped; trailing `result:success` still merges issue. |\n| A5 | `test_A5_token_budget_exceeded_halts_implement` | Stream-level `budget_exceeded` event plus failure result → issue fails without merge. |\n| A6 | `test_A6_github_rate_limit_at_triage_halts_pipeline` | Rate-limit armed before triage (remaining=0) — first GitHub call raises, pool absorbs, no PR created. |\n| A7 | `test_A7_github_secondary_rate_limit_surfaces` | Secondary (abuse-detection) rate-limit is also absorbed; issue never progresses. |\n| A8 | `test_A8_find_stage_to_done_realistic_agent` | Full pipeline from `hydraflow-find` through triage→plan→implement→review; issue merges. |\n| A9 | `test_A9_hindsight_failure_realistic_agent_still_succeeds` | `fail_service('hindsight')` during realistic-agent run does not halt pipeline; issue merges. |\n| A10 | `test_A10_quality_fix_loop_retries_then_passes` | `make quality` fails on first attempt; quality-fix agent commits fix; second quality run passes; merges. |\n| A11 | `test_A11_review_fix_ci_loop_resolves` | CI fails after PR creation; `fix_ci` loop resolves it; CI passes; merge proceeds. |\n| A12 | `test_A12_multi_commit_implement` | Real agent produces 3 commits; `git rev-list --count` confirms all three on branch. |\n| A13 | `test_A13_zero_diff_fails_without_merge` | Agent claims success but writes no commits; `_verify_result` fails on commit count; no merge. |\n| A14 | `test_A14_three_issues_concurrent_realistic` | Three issues processed concurrently via real AgentRunner; all merge; worktree isolation verified. |\n| A15 | `test_A15_epic_decomposition_creates_children` | High-complexity issue decomposed via EpicManager stub; two child issues created in FakeGitHub. |\n| A16 | `test_A16_credit_exhausted_halts_pipeline` | `CreditExhaustedError` from `_execute` propagates out of `run_pipeline` (re-raise allowlist). |\n| A17 | `test_A17_authentication_error_halts_pipeline` | `AuthenticationError` from `_execute` propagates out of `run_pipeline` (re-raise allowlist). |\n| A18 | `test_A18_rate_limit_heals_mid_pipeline` | Rate-limit armed with remaining=5; `on_phase(\"implement\")` heals before it matters; merges. |\n| A19 | `test_A19_code_scanning_alerts_reach_reviewer` | `add_alerts(branch=...)` seeds alerts; ReviewPhase fetches by branch; reviewer receives them unchanged. |\n| A20 | `test_A20_workspace_create_permission_failure` | `PermissionError` from workspace creation is swallowed; issue does not merge; run_pipeline returns normally. |\n| A20b | `test_A20b_workspace_create_disk_full` | `OSError(ENOSPC)` from FakeWorkspace is swallowed gracefully; issue does not merge. |\n| A20c | `test_A20c_workspace_create_branch_conflict` | `RuntimeError` (\"worktree already exists\") from FakeWorkspace is swallowed; issue does not merge. |\n| A21 | `test_A21_state_json_corruption_graceful_fallback` | Corrupt state.json before run; `StateTracker.load` falls back to empty `StateData()`; pipeline continues. |\n| A22 | `test_A22_wiki_populated_plan_consults_it` | Pre-populated `RepoWikiStore` wired to `PlanPhase`; wiki accessible; pipeline completes without crash. |\n\n**Boot smoke** (`test_realistic_agent_boot_smoke.py`): `test_real_agent_runner_single_event_smoke` — single invocation with tool_use + message + result events; proves the AgentRunner wiring stack boots.\n\n### Bead Workflow Scenarios (`test_bead_workflow.py`)\n\n| ID | Test | What it covers |\n|----|------|----------------|\n| B1 | `test_B1_bead_workflow_end_to_end` | Plan with Task Graph headers creates 2 beads; implement calls `init`; tasks stay open (claim/close are agent-subprocess concerns). |\n| B1b | `test_B1_no_beads_without_task_graph_headers` | Plan text without `### P{N}` headers → `extract_phases` returns []; no beads created; `_initialized` stays False. |\n\n### Background Loop Scenarios (`test_loops.py` + `test_caretaker_loops.py` + `test_caretaker_loops_part2.py`)\n\n#### L1–L8 (`test_loops.py`)\n\n| # | Loop | Scenario | Asserts |\n|---|------|----------|---------|\n| L1 | HealthMonitor | Low first_pass_rate triggers config bump | `max_quality_fix_attempts` increased, decision audit written |\n| L2 | WorkspaceGC | Cleans stale worktrees | Closed-issue worktrees destroyed, active preserved |\n| L3 | StaleIssueGC | Closes inactive HITL issues | Old HITL issues auto-closed with comment, fresh untouched |\n| L4 | PRUnsticker | Processes HITL items with open PRs | Unstick attempted on qualifying items |\n| L5 | CIMonitor | CI failure creates issue | GitHub issue created with `hydraflow-ci-failure` label |\n| L6 | CIMonitor | CI recovery closes issue | Failure issue auto-closed on green CI |\n| L7 | DependabotMerge | Auto-merges bot PR on CI pass | PR approved, merged, processed set updated |\n| L8 | DependabotMerge | Skips bot PR on CI failure | PR not merged, skip recorded |\n\n#### L9–L13 (`test_caretaker_loops.py`)\n\n| ID | Class | What it covers |\n|----|-------|----------------|\n| L9 | `TestL9ADRReviewerLoop` | `ADRReviewerLoop._do_work` delegates to `adr_reviewer.review_proposed_adrs`; stats pass through; None passthrough preserved. |\n| L10 | `TestL10MemorySyncLoop` | `MemorySyncLoop._do_work` calls `sync()` then `publish_sync_event(result)`; returned stats are a fresh copy. |\n| L11 | `TestL11RetrospectiveLoop` | `RetrospectiveLoop` drains queue; empty queue → zero stats; `RETRO_PATTERNS` item → processed=1, acknowledged. |\n| L12 | `TestL12EpicSweeperLoop` | `EpicSweeperLoop` sweeps open epics; no epics → zero counts; epic with all closed sub-issues auto-closed. |\n| L13 | `TestL13SecurityPatchLoop` | `SecurityPatchLoop` files issues from Dependabot alerts; no alerts → filed=0; high-severity fixable → filed=1; dry_run → None. |\n\n#### L14–L23 (`test_caretaker_loops_part2.py`)\n\n| ID | Class | What it covers |\n|----|-------|----------------|\n| L14 | `TestL14CodeGrooming` | `CodeGroomingLoop`: disabled → `{\"skipped\": \"disabled\"}`; dry_run → None; enabled with no findings → stats shape with `\"filed\"` key. |\n| L15 | `TestL15DiagnosticLoop` | `DiagnosticLoop` polls `hydraflow-diagnose` issues; no issues → zero counts; issue without escalation context → escalated=1. |\n| L16 | `TestL16EpicMonitorLoop` | `EpicMonitorLoop` delegates to `EpicManager`; no stale epics → stale_count=0; 3 stale + 5 tracked → stats match. |\n| L17 | `TestL17GitHubCacheLoop` | `GitHubCacheLoop` calls `cache.poll()` and forwards its stats; empty dict result → None (falsy guard). |\n| L18 | `TestL18RepoWikiLoop` | `RepoWikiLoop` lints per-repo wikis; no repos → zero stats; one repo → `active_lint` called, stale_entries reflected. |\n| L19 | `TestL19ReportIssueLoop` | `ReportIssueLoop` processes queued bug reports; dry_run → None; empty queue → None. |\n| L20 | `TestL20RunsGCLoop` | `RunsGCLoop` purges expired/oversized runs; no artifacts → zero purge; 3 expired + 1 oversized → stats match. |\n| L21 | `TestL21SentryLoop` | `SentryLoop` skips gracefully without credentials; empty org or empty token → `skipped=True` with reason. |\n| L22 | `TestL22StagingPromotionLoop` | `StagingPromotionLoop`: disabled → `status=staging_disabled`; cadence not elapsed → `status=cadence_not_elapsed`; elapsed → RC branch cut, promotion PR opened. |\n| L23 | `TestL23StaleIssueLoop` | `StaleIssueLoop` auto-closes stale issues; no issues → zero; fresh issue → scanned but not closed; stale + dry_run → closed=1, no API call; fetch failure → zero stats. |\n\n---","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794072+00:00","updated_at":"2026-04-25T00:47:19.794073+00:00","valid_from":"2026-04-25T00:47:19.794072+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Notes


- `make audit` exits non-zero today (Error 1) due to a real WARN finding: P5.5 reports `main` branch on `T-rav/hydraflow` lacks branch protection (HTTP 404 from `gh`). This is a legitimate audit signal, not a prerequisite gap. The CI job will need to tolerate WARN exit codes or the underlying protection must be enabled — to be resolved in Task 17a wiring.
- Wall-clock was captured via `/usr/bin/time -p make audit > /dev/null 2>bench-$i.txt` per plan Task 0 Step 1.
- Runtime variance across 5 runs is ~0.28s (7%), well within a single CI-budget bucket; no additional warmup runs needed.

```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249M","title":"Notes","content":"- `make audit` exits non-zero today (Error 1) due to a real WARN finding: P5.5 reports `main` branch on `T-rav/hydraflow` lacks branch protection (HTTP 404 from `gh`). This is a legitimate audit signal, not a prerequisite gap. The CI job will need to tolerate WARN exit codes or the underlying protection must be enabled — to be resolved in Task 17a wiring.\n- Wall-clock was captured via `/usr/bin/time -p make audit > /dev/null 2>bench-$i.txt` per plan Task 0 Step 1.\n- Runtime variance across 5 runs is ~0.28s (7%), well within a single CI-budget bucket; no additional warmup runs needed.","topic":"testing","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794278+00:00","updated_at":"2026-04-25T00:47:19.794279+00:00","valid_from":"2026-04-25T00:47:19.794278+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```

## Recommended Alerts


### Error Alerts
| Alert | Query | Threshold | Action |
|-------|-------|-----------|--------|
| Pipeline error spike | `event.type:error` | >5 in 10 min | Slack #hydraflow-alerts |
| Credit exhaustion | `CreditExhaustedError` | Any occurrence | Immediate Slack + email |
| New error type | First seen | Any | Slack |

### Performance Alerts
| Alert | Metric | Threshold | Action |
|-------|--------|-----------|--------|
| Slow agent | `memory.first_pass_rate` | <0.2 for 1 hour | Slack |
| Score drift | `memory.avg_score` | Drops >15% in 24h | Slack |
| Learning stall | `memory.stale_items` | >20 for 48h | Slack |
| Adjustment storm | Auto-adjustment count | >5 in 24h | Slack + HITL |
| Factory divergence | Per-project first_pass_rate | Diverges >30% from avg | Investigate |

### Setup Instructions
1. Go to Sentry → Alerts → Create Alert
2. Select "Custom Metric" for performance alerts
3. Configure threshold and action channels
4. Set environment filter to match HYDRAFLOW_ENV

```json:entry
{"id":"01KQ11NX7JR1QGCQ279PEQ249P","title":"Recommended Alerts","content":"### Error Alerts\n| Alert | Query | Threshold | Action |\n|-------|-------|-----------|--------|\n| Pipeline error spike | `event.type:error` | >5 in 10 min | Slack #hydraflow-alerts |\n| Credit exhaustion | `CreditExhaustedError` | Any occurrence | Immediate Slack + email |\n| New error type | First seen | Any | Slack |\n\n### Performance Alerts\n| Alert | Metric | Threshold | Action |\n|-------|--------|-----------|--------|\n| Slow agent | `memory.first_pass_rate` | <0.2 for 1 hour | Slack |\n| Score drift | `memory.avg_score` | Drops >15% in 24h | Slack |\n| Learning stall | `memory.stale_items` | >20 for 48h | Slack |\n| Adjustment storm | Auto-adjustment count | >5 in 24h | Slack + HITL |\n| Factory divergence | Per-project first_pass_rate | Diverges >30% from avg | Investigate |\n\n### Setup Instructions\n1. Go to Sentry → Alerts → Create Alert\n2. Select \"Custom Metric\" for performance alerts\n3. Configure threshold and action channels\n4. Set environment filter to match HYDRAFLOW_ENV","topic":"patterns","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-25T00:47:19.794333+00:00","updated_at":"2026-04-25T00:47:19.794334+00:00","valid_from":"2026-04-25T00:47:19.794333+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"medium","stale":false,"corroborations":1}
```
