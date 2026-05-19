---
source: feedback_verify_aspirational_glue_code.md
name: Verify aspirational glue code at spec-write time, not plan-execute time
description: Code in specs/plans that calls external constructors (e.g. TriageRunner,
  StateTracker) with invented kwargs survives into committed code if not cross-checked
  — gets caught by pre-push type checks
status: issue-open
issue: 43
promoted_in: null
wontfix_reason: null
created: '2026-04-21'
---

When writing a spec or plan that includes code calling external APIs (constructor signatures, method kwargs), verify those signatures against the real source at spec-write time. Do NOT assume the shape you wrote is correct — plan-time verification is cheaper than plan-execute-time debugging or pre-push hook failures.

**Why:** During PR #8376, the spec's Task 25 had `TriageRunner(config=..., event_bus=..., state=...)` and `StateTracker(path=...)` — neither of those kwargs exist. The subagent never actually executed the `main()` function (used fallback path), so the errors stayed latent until `git push` ran `make quality-lite`, which runs pyright and blocked the push. Fix required a surgical commit removing the aspirational `main()`.

**How to apply:**

1. **Before committing a plan file** that calls production constructors: `grep -n "def __init__" <module>` on each one. Verify param names, required vs. kwarg-only, defaults. Fix the plan text to match reality.
2. **Mark aspirational code explicitly** if you can't verify (e.g. "TODO: verify TriageRunner init signature at implementation time"). Don't ship plausible-looking-but-unverified signatures into a plan.
3. **If a subagent executes and skips an aspirational code path** (e.g., they pick a fallback strategy): the unexecuted code still type-checks. Make sure it compiles even if it never runs.
4. **Pre-push hooks are the backstop**, not the primary verification. They catch failures cheaply but too late — by then the subagent has moved on.
