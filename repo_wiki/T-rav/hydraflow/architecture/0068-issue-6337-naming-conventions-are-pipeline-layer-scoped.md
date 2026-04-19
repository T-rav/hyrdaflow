---
id: 0068
topic: architecture
source_issue: 6337
source_phase: plan
created_at: 2026-04-10T05:49:11.253569+00:00
status: active
---

# Naming conventions are pipeline-layer scoped

The GitHub-issue pipeline layer uses `issue_number` naming convention, but other domains (caching, memory scoring, review) intentionally keep `issue_id`. Don't over-generalize renames across modules—respect domain boundaries and only align naming where architectural layers actually overlap.
