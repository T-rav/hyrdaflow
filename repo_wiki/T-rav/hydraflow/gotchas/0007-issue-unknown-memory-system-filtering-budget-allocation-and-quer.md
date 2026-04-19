---
id: 0007
topic: gotchas
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T15:40:17.674506+00:00
status: active
---

# Memory System — Filtering, Budget Allocation, and Query Optimization

Filter evicted memories on both content prefix ('[EVICTED]') AND metadata status ('status: evicted'). Dual filtering ensures tombstones never leak into agent prompts even if one filter has bugs. Apply filters at recall time in _inject_memory() before formatting. Treat budget allocation as cap, not target. Cross-section dedup runs after truncation, so final prompt may be smaller than allocated budget. Dedup savings below budget ceiling are acceptable and expected—not failure case.

For prompt feedback sections with exemplars, place exemplars before remediation hints to ensure exemplars survive truncation. Phase-specific query customization should prepend context (`f"{prefix}, {context}"`) rather than replace it. Narrowing queries too much degrades recall quality. Additive prefixes guide semantic search while preserving original issue context needed for relevance matching. Relevance score boost uses in-place mutation (mem.relevance_score *= 1.15)—monitor this constraint during dependency upgrades.

See also: Exception Classification — classify failures in memory injection to distinguish bugs from transient errors.
