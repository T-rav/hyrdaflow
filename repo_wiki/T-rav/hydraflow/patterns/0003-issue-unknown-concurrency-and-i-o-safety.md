---
id: 0003
topic: patterns
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T15:38:18.766127+00:00
status: active
---

# Concurrency and I/O safety

Use `threading.Lock` when code runs in a thread pool (via `asyncio.to_thread()`) or is called from both sync and async contexts—`asyncio.Lock` is not thread-safe. Use `asyncio.Lock` only for coordinating pure coroutines without thread-pool involvement. For concurrent file I/O with brief lock hold times, `threading.Lock` is appropriate. Extract `_unlocked()` helper variants to prevent re-entrant lock attempts when lock-holding methods call each other. For crash-safe I/O: use `file_util.append_jsonl()` wrapped in `file_lock()` for JSONL appends (includes `flush()` and `os.fsync()`). Use `file_util.atomic_write()` for critical state file updates (writes to temp, then `os.replace()` atomically). Use `os.replace()` for atomic JSONL rewrites when content is small. All three patterns prevent partial writes and crash-induced corruption. Lock files (zero-byte sentinels) are durable and not cleaned up—overhead is negligible. Concurrent append-while-rewrite races are accepted at low frequency (hourly) but document as a load-bearing constraint.

For state mutations in asyncio (e.g., StateTracker), synchronous methods guarantee safe interleaving—locking is needed at the file level (via `file_lock()`), not the in-memory object level. Claim-then-merge for async queue processing: atomically claim items (clear/load), release lock, perform async work, re-acquire lock, reload for new items, merge with remaining, atomically write. Prevents lost entries when `write_all` overwrites file during async gap. Preserved tracing context lifecycle: set/clear or begin/end pairs MUST execute within single try/finally block to prevent trace state leaks. If accidentally split during refactoring, trace state leaks across issues/iterations. Fast synchronous I/O safe directly in async context when latency is negligible and lock contention is low. Call state cleanup unconditionally to purge stale state even when primary work set is empty. Event publishing stays coupled with condition checks in the same method—separating event logic from condition checks creates code paths where gates block but events don't fire, breaking observability.

See also: Refactoring and testing practices — error isolation preservation; Memory management — atomic write patterns and crash-safe file operations.
