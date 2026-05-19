# ADR-0073 — RunsGCLoop: Artifact Retention Enforcement

**Status:** Proposed
**Date:** 2026-05-19

## Context

HydraFlow's `RunRecorder` persists per-run artifacts (transcripts, diffs, outputs) under `<data_root>/runs/`. As the factory operates continuously, the runs directory grows unbounded unless something enforces the configured retention policy. Without a caretaker, operators discover oversized run directories during incident response — not before.

Two config knobs govern retention:

- `artifact_retention_days` — time-to-live for run directories (default: 7 days).
- `artifact_max_size_mb` — total size cap for the runs directory (default: 500 MB).

These are already enforced by `RunRecorder.purge_expired` and `RunRecorder.purge_oversized`; the gap is autonomous scheduling.

## Decision

`RunsGCLoop` (`src/runs_gc_loop.py`) subclasses `BaseBackgroundLoop` (ADR-0001, ADR-0029) and runs on the interval set by `config.runs_gc_interval`. Each tick:

1. Calls `RunRecorder.purge_expired(config.artifact_retention_days)`.
2. Calls `RunRecorder.purge_oversized(config.artifact_max_size_mb)`.
3. Calls `RunRecorder.get_storage_stats()` and logs the result.

The loop follows the kill-switch convention (ADR-0049): `enabled_cb("runs_gc")` is checked first, then `config.runs_gc_loop_enabled`. No external I/O beyond the local filesystem; no GitHub or LLM calls.

## Consequences

- The runs directory never grows beyond the configured caps during normal operation.
- Purge events are logged with counts (expired, oversized) for observability.
- Operators can still manually purge by deleting directories directly; the loop does not conflict with manual cleanup.
- If `artifact_retention_days` or `artifact_max_size_mb` are misconfigured to zero or negative, the loop delegates error handling to `RunRecorder`.

## Alternatives considered

- **Cron job.** Rejected: adds external scheduling infrastructure the dark-factory pattern avoids.
- **Purge on startup only.** Rejected: long-running deployments need continuous enforcement, not just at boot.

## Related

- [ADR-0001](0001-five-concurrent-async-loops.md) — loop runtime
- [ADR-0029](0029-caretaker-loop-pattern.md) — caretaker loop pattern
- [ADR-0049](0049-trust-loop-kill-switch-convention.md) — kill-switch convention
- `src/runs_gc_loop.py:RunsGCLoop`
- `src/run_recorder.py:RunRecorder`
