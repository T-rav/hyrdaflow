# ADR-0076 — GitHubCacheLoop: Centralized GitHub Data Cache

**Status:** Proposed
**Date:** 2026-05-19

## Context

In the original architecture, every dashboard endpoint and background worker that needed GitHub data (open PRs, HITL items, label counts, open issues) made its own `gh api` call. This produced:

- **Rate-limit exposure:** many concurrent read calls hit the GitHub API at the same time during busy factory periods.
- **Latency:** dashboard endpoints blocked on `gh api` round-trips before returning to the browser.
- **Redundancy:** 10+ callers each fetching the same PR list independently within the same second.

ADR-0041 declared GitHub as source of truth with a local cache as sidecar. `GitHubCacheLoop` is the implementation of that sidecar.

## Decision

`GitHubCacheLoop` (`src/github_cache_loop.py`) is a single background loop per repo runtime. It polls GitHub on a fixed interval and stores results in `GitHubDataCache`. The cache stores each dataset as a `CacheSnapshot` with a `fetched_at` timestamp.

All read consumers (dashboard routes, background loops) read from `GitHubDataCache` via its `get_*` methods. Write operations (create PR, merge, comment, label swap) remain direct `gh` calls — they need immediate confirmation and are low-frequency.

The cache is persisted to disk (JSON) so that a process restart does not immediately produce stale reads. On first boot, `age_seconds` returns infinity until the loop completes its first poll.

Kill-switch: `enabled_cb("github_cache")` (ADR-0049).

## Consequences

- Dashboard endpoint latency drops from `gh api` round-trip time (~300ms) to in-memory dict read (~0ms).
- GitHub API read rate drops proportionally to the number of consumers that were previously making independent calls.
- Cache is eventually consistent: reads may lag by up to one poll interval.
- Write operations are unaffected; they bypass the cache entirely.

## Alternatives considered

- **Per-caller caching.** Rejected: each caller would implement its own TTL logic redundantly, and calls would still race with each other.
- **Redis or external cache.** Rejected: adds an external dependency for a concern the factory can handle locally with simpler disk-backed JSON.

## Related

- [ADR-0041](0041-github-source-of-truth-cache-as-sidecar.md) — GitHub as source of truth
- [ADR-0029](0029-caretaker-loop-pattern.md) — caretaker loop pattern
- [ADR-0049](0049-trust-loop-kill-switch-convention.md) — kill-switch convention
- `src/github_cache_loop.py:GitHubCacheLoop`
- `src/github_cache_loop.py:GitHubDataCache`
