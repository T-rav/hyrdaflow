---
id: 0061
topic: architecture
source_issue: 6296
source_phase: review
created_at: 2026-04-10T05:36:08.671709+00:00
status: active
---

# Hindsight client cleanup ownership must be explicit

HindsightClient instances used in server modules need clear ownership semantics and cleanup paths. Resource leaks in clients compound across request lifecycles. Scope clients tightly and ensure they're explicitly closed, don't rely on GC.
