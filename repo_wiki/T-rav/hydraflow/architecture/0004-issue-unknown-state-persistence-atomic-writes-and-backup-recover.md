---
id: 0004
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849528+00:00
status: active
---

# State Persistence: Atomic Writes and Backup Recovery

All critical file operations use atomic write patterns to prevent partial corruption on crash: write to temp file, fsync for durability, then os.replace() for atomic swap. Use centralized utilities: `file_util.atomic_write()` for entire file rewrites (e.g., JSONL rotations) and `file_util.append_jsonl()` for crash-safe appends with automatic mkdir, flush, and fsync. For JSONL rotation/trimming: read, filter, write atomically; acquire exclusive file lock (.{filename}.lock) for the entire read-filter-write cycle to prevent TOCTOU bugs. Cache JSONL parsing results with TTL patterns for HTTP handlers. StateTracker uses backup pattern: save .bak backup before overwriting; restore from backup if main file corrupts. Single-writer assumption (async orchestrator) eliminates need for write-ahead logging. Applies to WAL files, state snapshots, JSONL stores, and configuration.
