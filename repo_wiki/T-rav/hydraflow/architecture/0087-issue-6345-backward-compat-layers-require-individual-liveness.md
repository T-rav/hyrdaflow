---
id: 0087
topic: architecture
source_issue: 6345
source_phase: plan
created_at: 2026-04-10T06:35:05.468495+00:00
status: active
---

# Backward-compat layers require individual liveness evaluation

Backward-compatibility property collections may contain both live and dead items that cannot be blanket-evaluated. Example: review_phase.py has active _run_post_merge_hooks alongside dead _save_conflict_transcript. Verify each property individually rather than assuming a layer is wholly live or wholly dead.
