---
source: feedback_review_before_merge.md
name: Always review PRs for bugs before merging
description: Run audit agents on PRs to catch bugs, missing tests, and gaps before
  merge — don't just merge blindly
status: issue-open
issue: 38
promoted_in: null
wontfix_reason: null
created: '2026-03-28'
---

Before merging any PR, run a test-audit agent to check for:
- Missing test coverage (dry_run, error paths, edge cases)
- Real bugs (error swallowing, state reset issues, wrong defaults)
- Wiring gaps (loop not registered in orchestrator/service_registry)
- Cross-PR dependencies

**Why:** Sprint 1 audit caught 3 real bugs that would have shipped: silent error swallowing in list_issues_by_label, orphaned issue on close failure in CIMonitor, and wrong enabled default in CaretakerPanel.

**How to apply:** After writing code and before merging, always run a test-audit agent on the changed files.
