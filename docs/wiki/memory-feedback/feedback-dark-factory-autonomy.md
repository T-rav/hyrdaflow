---
source: feedback_dark_factory_autonomy.md
name: Make dark-factory decisions without asking
description: User has explicitly delegated decision authority for tractable, reversible
  fixes that align with the dark-factory pattern; act first and report results instead
  of asking permission
status: issue-open
issue: 30
promoted_in: null
wontfix_reason: null
created: '2026-05-06'
---

For tractable, reversible fixes that align with the dark-factory pattern, **act first and report results** instead of asking permission. The user explicitly delegated this on 2026-05-07: "hydra is the factory, you help me build it, I want you to make more of these decisions without me going forward."

**Why:** The user is building HydraFlow as a self-fixing factory. Their bottleneck is themselves, not me. Pausing to ask "should I retarget this PR / run arch-regen / push the fix?" defeats the dark-factory premise. The factory IS the author. The factory IS the merger. The factory IS the fixer.

**How to apply:**
- Reversible + contained + clearly within HydraFlow's scope → act, then report
- Examples that fit: retargeting a PR's base branch when ruleset changes broke it, running `make arch-regen` + push when stale-artifacts blocks CI, applying `Skip-ADR:` when the touchpoints are import-level only, filing a `hydraflow-find` issue for a recurring pain
- Examples that still require explicit consent: high-blast-radius operations (force-push to main, deleting branches, dropping data, modifying repo permissions), anything destructive, anything that affects external services beyond the obvious scope
- When acting, still narrate: "Fixing X now, will report when done." Don't silently execute. The user wants to see what's happening, just not be a permission gate.

This memory pairs with `feedback_review_before_merge.md` — review caught real bugs in Sprint 1, so the bar for autonomous action is "tractable + reversible," not "anything goes."
