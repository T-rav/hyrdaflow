---
id: 0037
topic: architecture
source_issue: 6321
source_phase: plan
created_at: 2026-04-10T04:19:28.375208+00:00
status: active
---

# Cross-cutting methods as callbacks, not new classes

Methods called by 4+ concerns (like `_escalate_to_hitl` and `_publish_review_status`) should stay on the origin class and be passed as bound-method callbacks to extracted coordinators. This avoids creating yet another coordinator just for common operations and matches the established PostMergeHandler/MergeApprovalContext callback pattern.
