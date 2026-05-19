---
source: feedback_skip_hooks_on_push.md
name: Skip lint on push when told PR is good
description: When user says the PR is good / code quality is fine, don't re-run lint/typecheck on push — just push with --no-verify
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-04-07'
---

When the user says a PR is good or explicitly says not to lint/typecheck, just push directly with `--no-verify`. Don't force quality gates the user has already cleared or dismissed.

**Why:** User found the pre-push hook (make quality-lite) unnecessarily slow when they've already validated the code.

**How to apply:** If the user indicates code quality is fine or tells you to skip checks, use `git push --no-verify` instead of waiting for hooks.
