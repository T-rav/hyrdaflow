# ADR-0023: ADR Reviewer Proposed-Only Filter and Validator Scope

**Status:** Proposed
**Date:** 2026-03-07

## Context

The `ADRCouncilReviewer` in `src/adr_reviewer.py` enters its review pipeline through
`review_proposed_adrs()`, which calls `_find_proposed_adrs()` to discover candidates.
This finder method filters ADR files to only those with `**Status:** Proposed`,
meaning the entire downstream review flow — duplicate detection, council voting,
acceptance, escalation — only ever processes ADRs in the Proposed state.

Any status-specific logic for other states (e.g. checking `status == "superseded"`)
is unreachable through the main `review_proposed_adrs` entry point. If the class is
used as a standalone validator and called with individual methods directly, those
branches become reachable, but through the primary orchestrated flow they are dead
code.

Tests that exercise status-specific branches (such as superseded-status validation)
test the validator in isolation rather than through the review flow. This creates a
gap: the tests pass, but the code paths they cover are never triggered in production.

**Source memory:** Issue #2251 — [Memory] ADR pre-review validator only processes
Status: Proposed ADRs.

## Decision

Accept the Proposed-only filter as the intentional design for the automated review
pipeline and document the following boundaries:

1. **`review_proposed_adrs()` is the production entry point.** It deliberately
   restricts processing to Proposed ADRs. This prevents the council from
   re-reviewing Accepted, Superseded, or Rejected ADRs on every cycle, which would
   waste compute and risk unintended status transitions.

2. **Status-specific validation branches are for external/manual callers only.**
   If individual validation methods (e.g. supersession checks) are exposed for use
   outside the automated pipeline, they must be documented as such. Tests covering
   these paths should be clearly labeled as testing the standalone API, not the
   orchestrated flow.

3. **Do not add unreachable branches inside the automated flow.** New status checks
   should only be added to the pipeline if `_find_proposed_adrs` is broadened to
   return ADRs in those states. Otherwise, place them in a separate utility or guard
   that callers can invoke independently.

## Consequences

- **Clarity:** Developers know that the automated review loop intentionally skips
  non-Proposed ADRs. No one will add supersession or deprecation logic to the
  pipeline expecting it to run.

- **Test accuracy:** Tests for status-specific branches should be grouped under a
  "standalone validator" test class or clearly annotated, so reviewers understand
  these paths are not exercised in the orchestrated flow.

- **Future extension:** If the pipeline needs to handle other statuses (e.g.
  re-validating Superseded ADRs for dangling references), the filter in
  `_find_proposed_adrs` must be explicitly broadened and new integration tests
  added to cover the expanded flow.

- **Dead code risk:** Existing unreachable branches through the main flow should
  be evaluated. If they serve no standalone purpose, they should be removed to
  reduce maintenance burden.

## Alternatives Considered

- **Broaden the filter to all statuses:** Rejected because it would cause the
  council to re-process every ADR on every cycle, increasing latency and risking
  accidental status changes on already-decided ADRs.

- **Remove all non-Proposed status checks:** Rejected because the validator class
  has value as a reusable component. External callers (scripts, CI checks) may
  invoke individual methods on ADRs in any state.

- **Split into two classes (pipeline reviewer vs. standalone validator):** Considered
  viable but deferred as over-engineering for the current usage pattern. If external
  usage grows, this split would be the natural next step.

## Related

- Issue #2251 — Source memory: ADR pre-review validator only processes Status: Proposed ADRs
- Issue #2253 — This ADR task
- `src/adr_reviewer.py` — `ADRCouncilReviewer._find_proposed_adrs` (line 92)
- `src/adr_reviewer.py` — `ADRCouncilReviewer.review_proposed_adrs` (line 43)
