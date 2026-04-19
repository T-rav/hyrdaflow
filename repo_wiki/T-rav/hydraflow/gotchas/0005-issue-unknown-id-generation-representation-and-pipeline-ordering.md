---
id: 0005
topic: gotchas
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T15:40:17.674486+00:00
status: active
---

# ID Generation, Representation, and Pipeline Ordering

Use consistent ID generation logic everywhere files are keyed (e.g., plans_dir / f'issue-{issue.id}.md') to avoid silent lookup failures. Define prefix lengths as constants (discover=9, shape=6) and centralize extraction to prevent off-by-one slice errors that silently produce NaN. Join factory metrics and reviews by issue_number (not pr_number). Issue number propagation before memory injection enables outcome correlation across phases; reset to 0 after injection.

Avoid implicit heuristics like `if fname not in content` for self-exclusion. Pass explicit parameters (self_fname) to filter functions instead—this makes logic clearer and prevents silent edge cases. Collision detection must explicitly exclude self before reporting to avoid misleading messages.

Representation gaps indicate multiple object models in codebase. Example: ReviewRunner uses Task.id while phase_utils.publish_review_status uses pr.issue_number for same concept. Document which representation a helper uses and scope it appropriately. Mixed usage should be consolidated to single representation or explicitly mapped.

Stage progression logic relying on array indices (currentStage from PIPELINE_STAGES position) is fragile. New stages inserted at incorrect positions silently break progression if only status values are verified in tests. When adding pipeline stages, verify both stage ordering and progression logic—order matters even if status values are correct.

For skip detection, only trigger when stage at index ≥3 (plan or later) has non-pending status. If issue is in triage (triage=active, discover/shape=pending), discover/shape must remain pending, not marked skipped.

Phase progression occurs via predictable label mutations (discover→shape, shape→plan). Clarity scoring gates entry: high-clarity issues (≥7) go directly to planning; vague issues route to discovery first. This deterministic approach makes phase progression observable in issue history, eliminating hidden state and making system auditable.

See also: Testing — ID generation must have test coverage verifying consistency across lookups.
