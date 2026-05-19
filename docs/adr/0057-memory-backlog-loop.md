# ADR-0057: MemoryBacklogLoop — promote session-memory feedback to the find queue

- **Status:** Accepted
- **Date:** 2026-05-07
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0029](0029-caretaker-loop-pattern.md) (caretaker-loop pattern), [ADR-0049](0049-trust-loop-kill-switch-convention.md) (kill-switch convention), [ADR-0051](0051-iterative-production-readiness-review.md) (iterative production-readiness review), ADR-0056 (gate → loop precedent — promotes to staging separately). Code: `src/memory_backlog_loop.py`, `src/memory_backlog_mirror.py`, `docs/wiki/memory-feedback/`.
- **Enforced by:** `tests/test_memory_backlog_loop.py`, `tests/test_loop_wiring_completeness.py` (auto-discovery confirms 5-checkpoint wire), `tests/architecture/test_functional_area_coverage.py` (loop assigned in `functional_areas.yml`).

## Context

Across ~7 weeks of HydraFlow sessions, ~19 `feedback_*.md` memory files have accumulated in Claude's session-memory directory (`~/.claude/projects/<repo-encoded>/memory/`). Each captures a recurring footgun the user has corrected at least once — patterns like "cap subagent batches at 2–4 tasks", "ruff strips unused imports during TDD", "cleanup PRs need full-suite verification". The dark-factory wiki (`docs/wiki/dark-factory.md` §6) names the meta-fix: move conventions from "remembered" to "structurally enforced." But the memories themselves are private to Claude's session — the trust fleet has no way to surface them as work, so they pile up unconverted.

This ADR documents the bridge between Claude's private memory and the trust-fleet issue queue.

## Decision

Adopt a two-piece approach:

1. **In-repo redacted mirror.** When Claude saves a `feedback_*.md`, it ALSO commits a redacted copy to `docs/wiki/memory-feedback/<slug>.md`. Redaction strips `originSessionId`, replaces `$HOME`-absolute paths with `~`, and redacts emails outside an allowlist. Frontmatter has `status: pending | issue-open | promoted | wontfix` plus `issue` / `promoted_in` / `wontfix_reason` fields. The mirror is the source-of-truth for the loop.

2. **`MemoryBacklogLoop`** (caretaker, ADR-0029 pattern). Default cadence 24h. On each tick:
   - Walk `docs/wiki/memory-feedback/*.md`.
   - For each entry with `status: pending`, file a `hydraflow-find` issue (labels: `find_label` + `memory_backlog_label`).
   - Update frontmatter to `status: issue-open` + `issue: <N>` and commit the change.
   - Standard 3-strikes-then-bug escalation when an issue is closed without `promoted` / `wontfix` (re-files three times with cooldown, then escalates with `memory_backlog_stuck_label`).

The loop honors the [ADR-0049](0049-trust-loop-kill-switch-convention.md) in-body kill-switch gate.

### Rules

1. **No reading of `~/.claude/.../memory/` from the loop.** The loop is fleet-portable; it must not depend on user-HOME paths. Redaction happens at memory-write time (Claude's responsibility), not at tick time.
2. **No body edits.** The loop only writes the frontmatter `status` / `issue` / `promoted_in` / `wontfix_reason` fields.
3. **No auto-PR.** The loop files issues; promoting a memory to enforcement is human-or-Claude work, intentionally.

## Consequences

**Positive:**
- The "remembered → enforced" backlog is now a dedup'd, escalatable issue queue; the user is no longer the bottleneck.
- New feedback memories surface as work without operator intervention.
- The mirror is auditable in PR review — every entry is plain markdown with explicit frontmatter.
- Symmetry with the rest of the trust fleet — every other audit signal (`FakeCoverageAuditorLoop`, `FlakeTrackerLoop`, `WikiRotDetectorLoop`, `AdrTouchpointAuditorLoop`) is already a caretaker loop, not a gate.

**Negative:**
- Redaction is manual at memory-write time. A future iteration may automate it via a slash command or pre-commit hook.
- The mirror can drift from the source memory if Claude forgets to mirror. Mitigation: documented in the memory protocol; a follow-up could add an automated check.
- The loop only handles `feedback_*.md`. `project_*.md` (time-sensitive state) and `user_*.md` (personal) are out of scope for v1.

## Out of scope (deferred for future iterations)

- Automated mirror sync on memory write (current convention: Claude does it manually).
- `project_*.md` and `user_*.md` mirroring.
- Auto-promotion to ADR / test stub generation when a memory is converted.
- JSONL audit stream of tick decisions (derivable from issue history + `promoted_in`).
