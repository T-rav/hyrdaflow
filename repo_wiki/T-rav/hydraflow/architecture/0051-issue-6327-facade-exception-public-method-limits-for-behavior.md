---
id: 0051
topic: architecture
source_issue: 6327
source_phase: plan
created_at: 2026-04-10T05:07:55.384601+00:00
status: active
---

# Facade Exception: Public Method Limits for Behavioral Classes

The ≤7 public method / ≤200 line constraints apply to extracted behavioral classes (ActiveIssueTracker, IssueSnapshotBuilder, IssueQueueRouter). The facade necessarily retains 25 delegation stubs for backward compatibility per the documented pattern — this is not a violation of the rule, but a documented exception to preserve import paths and external consumers.
