---
source: feedback_no_env_hidden_settings.md
name: User-facing config belongs in the System tab, not .env
description: Runtime-tunable config must be exposed as a settings card in the System tab; .env is for secrets and boot-time wiring only
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-04-18'
---

Any feature-level knob a user might actually want to flip (enable/disable toggles, branch names, cadences, thresholds) must be exposed as a settings card in the System tab UI. `.env` is reserved for secrets and boot-time wiring that nobody tunes at runtime.

**Why:** The user has an explicit aversion to configuration hidden in `.env` — "I hate things like this hidden in the .env". Surfacing it in the UI is how operators actually discover and use a feature; burying it in an env file means nobody ever turns it on.

**How to apply:** When adding a config field that gates user-visible behavior (e.g., `staging_enabled`, `staging_branch`, `rc_cadence_hours`), ship a System-tab settings card alongside the backend change in the same PR. Don't split "add the field" from "surface the field" across PRs — the field without a UI is dead weight. Env-var override still works underneath (for CI/tests), but the UI is the primary interface.

Related: user explicitly accepts that cross-repo factory-wide settings are a future concern. For now, single-repo per-process config surfaced on the System tab is the right scope.
