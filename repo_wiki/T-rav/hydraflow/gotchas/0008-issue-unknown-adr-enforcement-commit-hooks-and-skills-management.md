---
id: 0008
topic: gotchas
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T15:40:17.674515+00:00
status: active
---

# ADR Enforcement, Commit Hooks, and Skills Management

Enforcement ADRs need explicit tier-to-mechanism mapping (pre-commit hook, linter, test suite, manual review) with distinct statuses for items with tracking issues vs. those requiring new issues. Consequences sections must cross-check tracking status against decision tables—verify item-by-item that all proposed items have clear tracking. Avoid conflating 'tracked' with 'needs issue'.

Commit message validation should only block commits that *attempt* specific format incorrectly (e.g., Fix instead of Fixes). Allow plain commits without issue refs, WIP prefixes, merge commits, reverts, and auto-generated commits. This avoids blocking agents that make multiple intermediate commits during implementation.

New dynamic skills start with blocking=False to avoid breaking workflows. Skills graduate to blocking=True only after ≥20 runs with ≥95% success rate. This policy ensures new automated checks are proven before failing builds.

Extract workflow concepts (TDD, systematic debugging, review rigor) and hardcode them in PHASE_SKILL_GUIDANCE dict rather than dynamically loading from filesystem. This avoids dependency on superpowers installation path and keeps system self-contained. New phases need dict entries, not filesystem discovery. TOOL_PHASE_MAP registration is ongoing maintenance burden—add lint test warning on unknown commands in .claude/commands/ to catch unregistered tools before shipping.
