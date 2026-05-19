---
source: feedback_dont_close_unfixed_issues.md
name: Never close issues that aren't actually fixed
description: Only close issues with a merged PR that fixes them — never close as "deferred" or "tracked debt"
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-04-18'
---

Only close *human-filed* GitHub issues when there is a merged PR that actually fixes them. Do NOT close them as:
- "Deferred — tracked for future"
- "Tracked technical debt"
- "Review insight, not actionable"

**Why:** User called this out — closing unfixed human-filed issues hides work and loses track of what still needs doing. Reopening 14 issues was required to fix the mistake.

**How to apply:** If a human-filed issue can't be fixed now, leave it open. Add investigation notes if useful, but don't close it.

**Exception — auto-filed noise from disabled/misfiring loops:** Bulk-closing auto-generated findings (e.g. `hydraflow-find` code-quality issues filed by the code_grooming_loop) is fine when the user explicitly authorizes it and the source loop is being disabled or retuned. On 2026-04-18 the user approved closing 788 auto-filed `Code Quality:` issues after PR #8344 defaulted code grooming off; kept the top 10 by real correctness/security hazard. Still ask for the "worst N to keep" cutoff and show the keep list before bulk-closing.
