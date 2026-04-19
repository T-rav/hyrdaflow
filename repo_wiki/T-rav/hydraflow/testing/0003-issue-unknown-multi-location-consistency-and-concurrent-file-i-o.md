---
id: 0003
topic: testing
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T14:53:08.908953+00:00
status: active
---

# Multi-Location Consistency and Concurrent File I/O Testing

Concurrent file operations: Test concurrent file operations using `concurrent.futures.ThreadPoolExecutor` with fixed thread counts and deterministic iterations (e.g., 10 threads × 20 events = 200 total). Assert exact event counts rather than timing. `append_jsonl` has no file locking, but POSIX guarantees atomicity for writes under ~4KB (pipe buffer). Each JSON line is well under 4KB, so concurrent appends should be safe—validate empirically. If concurrent appends produce corrupt lines, locking or buffering becomes necessary.

Memory deduplication and bank consistency: Memory deduplication uses a priority mapping: LEARNINGS (memory) = 5, TROUBLESHOOTING = 4, RETROSPECTIVES = 3, REVIEW_INSIGHTS = 2, HARNESS_INSIGHTS = 1. When two near-duplicate items collide, the higher-priority bank's item survives. Bank key consistency across dedup and assembly pipelines is critical—if `bank_order` uses different key names than dict keys, banks will be silently missed. Use consistent string keys throughout (memory, troubleshooting, review_insights, etc.). Different memory banks use different JSONL record formats. Fallback recall functions must try multiple field names (`learning`, `text`, `content`, `display_text`, `description`) to extract the text payload.

Skill definition multi-location replication: HydraFlow skills are replicated across 4 backend locations (.claude/commands/, .pi/skills/, .codex/skills/, src/*.py). Use a manual SKILL_MARKERS mapping (not regex introspection) to validate that all copies contain matching output markers. Consistency tests should check marker presence via substring search to tolerate minor markdown structure differences across backends. Each skill removal or addition requires updating all test fixtures and assertions across multiple test files—a single skill change can require updates across 3+ test files. Before committing skill changes, verify that all 4 backend copies have been updated with consistent marker text.

Cross-location key consistency principle: Both memory deduplication and skill definition replication depend on consistent naming across multiple locations. If location names or field names differ across copies, data will be silently missed during validation or deduplication. Always verify that bank_order keys match dict keys and skill markers are present in all 4 backend copies with identical text.
