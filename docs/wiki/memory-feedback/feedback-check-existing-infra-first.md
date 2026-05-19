---
source: feedback_check_existing_infra_first.md
name: Check existing infrastructure before building parallel solutions
description: Before writing a new test/lint/loop, grep the codebase for existing infrastructure that already solves the problem — reinventing wastes ~30-45 min of agent dispatches per missed case
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: 2026-05-08
---

# Check existing infrastructure before building parallel solutions

When a spec calls for a new convention-enforcement (test, lint rule, fixture, loop), grep the codebase first to confirm equivalent infrastructure doesn't already exist. **Reinventing is the more common failure mode than under-building** when working from a multi-item spec.

**Why:** PR #8714 Task 4 ("EventType ↔ reducer parity test") was reinventing `tests/test_event_reducer_coverage.py` (which already implemented parity with a SKIP_LIST mechanism, predating my work). The duplicate test was caught only at `make quality` time when ruff's line-wrapping interaction broke the existing parser. Net cost: 2 agent dispatches building the redundant pieces + 1 cleanup commit reverting them. The existing test had been there for months.

**How to apply:**

- **Before dispatching an agent for a new test:** `rg -l "EventType\|reducer\|parity" tests/` (or analogous keywords for the convention). 30 seconds of grep beats 30 minutes of reinventing.
- **Before designing a new caretaker loop:** check `find src -name "*loop*.py"` for sibling loops that may already cover the surface. Check `docs/wiki/dark-factory.md` and the functional area map.
- **At spec-write time:** explicitly note "checked: no existing infrastructure for X" in the spec. Forces the check; documents the search for future readers.
- **The existing infrastructure may have flaws** (the existing parity test had a brittle regex parser). Fix-in-place beats parallel build — same effective coverage, half the surface area, no duplication tax.

**Pattern recognition signal:** if your spec says "we need a test/check that does X" and X sounds generic enough that someone else might have built it, you're probably right.
