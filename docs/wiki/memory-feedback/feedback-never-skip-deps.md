---
source: feedback_never_skip_deps.md
name: Never silently skip dependencies
description: Required dependencies must fail hard, never degrade gracefully or skip with a warning
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-03-27'
---

Never silently skip or gracefully degrade when a required dependency is unavailable. Fail hard and fast.

**Why:** User explicitly rejected a "skip with warning" approach for Hindsight/Docker Compose. Required infrastructure must be present — silent skipping hides real problems.

**How to apply:** When a make target or startup check detects a missing dependency, error out immediately. Don't add fallback logic that lets the system continue in a degraded state unless the user specifically asks for it.
