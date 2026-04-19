---
id: 0002
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849518+00:00
status: active
---

# Optional Dependencies: Graceful Degradation and Safe Handling

Services like Hindsight, Docker, and others may be unavailable or disabled. Design via: (1) **Never-raise pattern**: wrap all calls to optional features in try/except blocks that return safe defaults rather than raising. Catch broad exception types (Exception, OSError, ConnectionError) instead of importing optional module exception types. (2) **Graceful degradation**: when unavailable, fall back to JSONL file storage or no-op behavior; use dual-write pattern during migration. (3) **Explicit None checks**: guard with `if hindsight is not None:` (never falsy checks, as MagicMock can be falsy-but-not-None). (4) **Fire-and-forget async variants**: wrap blocking I/O without blocking callers. (5) **Property-based access**: expose optional services via properties rather than constructor parameters. Core principle: failures in non-critical or optional features must never crash the pipeline. See also: Feature Gates for feature flags that gate incomplete features, Deferred Imports for import-time handling.
