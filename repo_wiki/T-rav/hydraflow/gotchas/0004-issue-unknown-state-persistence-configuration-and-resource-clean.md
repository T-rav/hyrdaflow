---
id: 0004
topic: gotchas
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T15:40:17.674477+00:00
status: active
---

# State Persistence, Configuration, and Resource Cleanup

Config validators (e.g., labels_must_not_be_empty covering all label fields) serve as source of truth for audit fields. Mismatch between validator field set and audit field enumeration indicates a bug. When fixing label removal bugs, add regression tests explicitly verifying those fields by name. Fixing code doesn't retroactively clean existing issues—post-deployment manual cleanup may be needed.

When adding new list[str] label fields to HydraFlowConfig, always add as optional ConfigFactory.create() parameters with sensible defaults. Omitting causes TypeError. Add test that ConfigFactory.create() accepts all label fields. Validate collection fields accessed by index—downstream code accesses [0] without null-checking. Constructor parameters must require before optional: use `param: Type | None = None` with fallback logic.

For state persistence, use append-only reflection files (JSONL) to accumulate data across retries, avoiding schema migrations. Mark entries with structural boundaries (timestamps, phase separators). Implement explicit cleanup methods at logical boundaries to prevent unbounded growth. Wrap all JSONL I/O in try/except OSError; append operations must be idempotent to survive partial writes. Use file_util.atomic_write() instead of Path.write_text() to prevent JSON corruption from crashes mid-write. Hard size caps (e.g., 10MB) provide secondary guards. trim_jsonl operates on raw lines without JSON parsing; corrupt/malformed records survive trimming intentionally.

For schema evolution, new Pydantic model fields with `field: Type = default_value` allow existing state files to load without error. TypedDict(total=False) enables backward-compatible event payloads where all fields are optional. Frozen Pydantic models require object.__setattr__ for mutation—critical in overrides (numeric, bool, literal) to avoid breaking setter logic. Cross-field validation must run after numeric overrides but before bool/literal overrides.

When persisting to multiple banks (repo-specific + universal), use single Write-Ahead Log (WAL) to capture all writes together for atomic failure recovery. Type coercion across serialization boundaries: HindsightClient coerces metadata values to strings during retain while local JSONL keeps int. Wrap type conversions in try/except catching (TypeError, ValueError) with fallback to None.

Idempotency guards protect against duplicate calls and retries, not concurrent execution. Per-issue locking at orchestrator level prevents true concurrency. When removing config fields, removed env-var overrides should be silently ignored. Validate field removal by letting tests fail on missing attributes. When HydraFlow manages itself (repo_root == HydraFlow repo), use hash-based or idempotent installation to skip if identical. Critical in multi-execution-mode systems.

When extracting methods that compute intermediate state needed by failure paths, return tuples `(success, mergeable)` rather than recomputing. State transitions create atomicity windows for exceptions: when exceptions occur after successful state transition (e.g., label swap) but before cleanup, issues can get stuck in intermediate states. Mitigation: wrap transition+operation+cleanup in try/except that reverses transitions on non-fatal exceptions. Track resource creation state to enable safe cleanup—only attempt destroy if setup successfully created the resource. HITL workflows should destroy worktrees only on success, preserving them on failure to enable post-mortem debugging.

See also: Exception Classification — exception handling during state transitions; Testing — validate schema evolution with serialization tests.
