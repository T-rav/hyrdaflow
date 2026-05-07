# ADR-0056: ADR touchpoint enforcement — synchronous gate → asynchronous caretaker loop

- **Status:** Accepted
- **Date:** 2026-05-06
- **Supersedes:** none (the gate it replaces was a piece of CI tooling, not an ADR-blessed decision)
- **Superseded by:** none
- **Related:** [ADR-0029](0029-caretaker-loop-pattern.md) (caretaker-loop pattern), [ADR-0045](0045-trust-architecture-hardening.md) (trust-architecture hardening, which originally floated `Skip-ADR:` as a convention). Code: `src/adr_touchpoint_auditor_loop.py`, `src/adr_drift.py`, `src/state/_adr_audit.py`.
- **Enforced by:** `tests/test_adr_touchpoint_auditor_loop.py`, `tests/test_adr_drift.py`, `tests/test_loop_wiring_completeness.py` (auto-discovery confirms the loop is wired in all 5 checkpoints).

## Context

The "ADR touchpoint gate" — `.github/workflows/adr-touchpoints.yml` plus `scripts/check_adr_touchpoints.py` — was a synchronous CI check that failed any PR whose diff touched a `src/` file cited by an Accepted ADR unless either (a) the cited ADR file was also in the diff or (b) the PR body carried a literal `Skip-ADR: <reason>` line. Its intent was to keep ADRs in step with the code they describe — when load-bearing code drifts from documented architecture, future readers get a misleading map.

In practice, three friction modes outweighed the oversight value:

1. **Trivial bypass.** `Skip-ADR: ¯\_(ツ)_/¯` clears the gate. Any contributor short on time wrote a one-word reason and merged. The gate did not enforce thought; it enforced the *appearance* of thought.
2. **Body-edit fragility.** The workflow runs on `pull_request: edited`, but GitHub's check status for the original `opened` run is what Mergify and humans look at. Editing the body to add `Skip-ADR:` after-the-fact does not retrigger the check from the operator's perspective; only an empty commit does. This burned multiple sessions in the auto-agent fleet and showed up in the user's auto-memory ("Skip-ADR added after PR open needs retrigger").
3. **No drift surface for non-PR changes.** Squash-merged PRs are scanned at merge time; force-pushes, rebases, and direct-branch work are not. The gate's coverage was incidentally narrower than the problem it claimed to solve.

The gate was deleted in PR #8484. This ADR documents the replacement: an asynchronous caretaker loop that surfaces the same drift signal as queued work without blocking the merge train.

## Decision

**Replace the synchronous gate with `AdrTouchpointAuditorLoop` — a caretaker loop following the [ADR-0029](0029-caretaker-loop-pattern.md) pattern.**

The loop runs on a configurable interval (default: 4 hours). On each tick it:

1. Walks merged PRs since the last cursor (`state.adr_audit_cursor`, ISO-8601 of the most-recently-scanned merge).
2. For each merged PR, computes the file-diff and intersects it with the citation table from `ADRIndex` (Accepted ADRs whose `Related:` line names a `src/...` module).
3. For each ADR whose cited module changed *without* the ADR file being in the same diff, files a `hydraflow-find` issue with title `ADR drift: ADR-NNNN cited modules changed in PR #NNNN`. Labels: `find_label`, `adr_drift_label` (`hydraflow-adr-drift`).
4. Dedup key `adr_touchpoint_auditor:{pr}:{adr}` prevents re-filing the same drift across re-scans (e.g. cursor rewind during incident response).
5. After 3 unresolved attempts on the same key, escalates to `hitl_escalation_label` + `adr_drift_stuck_label` (`hydraflow-adr-drift-stuck`). Closing the escalation issue clears the dedup key and attempt counter (same reconcile pattern as `FakeCoverageAuditorLoop`).

The loop honors the [ADR-0049](0049-trust-loop-kill-switch-convention.md) in-body kill-switch:

```python
async def _do_work(self) -> dict[str, Any] | None:
    if not self._enabled_cb(self._worker_name):
        return {"status": "disabled"}
    # ... walk merged PRs since cursor ...
```

### Rules

1. **No PR-time blocking.** The loop never modifies CI status, never comments on open PRs, never blocks a merge. Drift is a finding, not a precondition.
2. **Cursor is durable.** `state.adr_audit_cursor` survives orchestrator restarts; the first run after deploy starts at "now" so we don't process pre-existing merge history (frozen).
3. **File-level intersection only (v1).** Citations are resolved at file granularity (`EXAMPLE.py`). The deleted gate also supported symbol-level (`EXAMPLE.py:Bar`) precision, but inspection of `docs/arch/generated/adr_xref.md` showed zero ADRs use this form in production. Symbol precision is YAGNI for v1; revisit if/when a citation actually uses it.
4. **`Skip-ADR:` is gone.** No PR-body marker, no escape hatch convention. If a contributor judges that an ADR doesn't need updating for a given diff, they close the loop's issue with a short explanation. That comment is the audit trail; it lives on the issue, not buried in a PR body.

## Consequences

**Positive:**
- Merges are no longer gated on a check that was bypassable by typing a single word.
- Drift surfaces as bounded, dedup'd, escalatable work — operators see a `hydraflow-find` issue queue instead of a blocked PR.
- The caretaker pattern means failures (gh API outage, ADR-index parse error) don't cascade into merge-blocking. The loop retries next tick; the merge train moves.
- Symmetry with the rest of the trust fleet — every other audit signal (`FakeCoverageAuditorLoop`, `FlakeTrackerLoop`, `WikiRotDetectorLoop`, `PrinciplesAuditLoop`) is already a caretaker loop, not a gate.

**Negative:**
- There is a window (one loop interval, default 4h) between merge and drift surfacing. A PR that introduces ADR drift can land before the loop notices. Mitigation: the loop's purpose is to make drift visible, not to prevent it; the issue queue is the surface.
- The cursor-based scan can miss PRs if the cursor is corrupted or rewound past a merge. Mitigation: the dedup store is the source of truth for "have we filed on this PR×ADR pair"; rewinding the cursor only re-scans, doesn't re-file.
- One additional loop in the fleet — modest cost-budget impact (the loop only spawns `gh` subprocesses, no LLM calls).

**Migration:**
- The gate workflow + script are deleted in PR #8484.
- The first deploy after this ADR lands seeds `adr_audit_cursor` to "now"; pre-existing merged PRs are *not* retroactively scanned. Operators who want a backfill can manually rewind the cursor in `.hydraflow/.../state.json`.

## Notes for future ADRs

- A future ADR may revisit symbol-level precision when an ADR's `Related:` line actually carries `EXAMPLE.py:Bar` style citations. Until then, file-level is sufficient and matches observed usage.
- A future ADR may add a "drift severity" axis (e.g. distinguish `ADR cites the file exists` from `ADR cites a specific symbol's behavior`). The current single-severity model is the simplest thing that surfaces signal.
