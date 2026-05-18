# Factory-Phase Drift Mitigation — 2026-05-12

**Slice #4 of the documentation audit roadmap.** Companion to [ADR-0063](../adr/0063-factory-phase-drift-mitigation.md).

**Input:** [`docs/arch/coverage_matrix.md`](coverage_matrix.md) §3 (factory phases).
**Baseline matrix SHA:** `06781b1b3ffd068169ea5fd991d88c67510356b7`
**Audit commit SHA:** `038f21466abea05a83d6dd1b1d09bc94fb6e0fe6` (staging tip at audit time)

---

## Summary

The matrix recorded eight pipeline phases with current HITL triggers. This report
analyses each trigger's root cause, classifies it against the dark-factory contract
("humans only paged for raging fires"), and proposes a concrete remediation with a
success metric. Three of the eight phases preserve HITL by design; five have
actionable autonomous-recovery remediations. One phase (`triage`) has a structural
gap with no autonomous re-entry at all and needs a new caretaker loop.

| Phase | Verdict | Category | Workstream |
|---|---|---|---|
| `triage` | Drift — no autonomous re-entry | RECOVERY | W2 — `TriageRetryLoop` |
| `discover` | Drift — context-bound failure escalated | CTX | W3 — discover-expander subagent |
| `shape` | Partial drift — council pattern works but caps at 2 rounds | COUNCIL | W4 — third diversified-persona round |
| `plan` | Drift — touchpoint context missing on retry | CTX + PROMPT | W3 — touchpoint-expander subagent |
| `implement` | Drift — zero-diff branches lack spec-compliance feedback | PROMPT | W5 — two-stage review in ImplementPhase |
| `review` | Partial drift — SandboxFailureFixer under-contextualised | CTX (partial) | W3 (failure-fixer context) |
| `HITL` | Drift — generic playbook for diverse failure modes | CTX | W1 — specialist-aware preflight |
| `merge` | HITL-by-design — no autonomous attribution possible | HITL-BY-DESIGN | None (file `hydraflow-find` instead) |

Five `factory-phase-drift` beads filed; one per workstream.

---

## Per-phase analysis

### `triage`

**Matrix HITL trigger:** Issue parked when triage runner returns `needs_info`; HITL not directly triggered — parked issues await human clarification comment. **No autonomous recovery path.**

**Root cause.** The current park path (`src/triage_phase.py:312-333`) is intentional: per ADR-0033, triage failures should not pollute the HITL queue with issues that need *user* clarification, not engineering judgment. But the design predates `AutoAgentPreflightLoop` and assumes the human-author will return to provide context. In practice, parked issues sit indefinitely; the user moved on. There is no caretaker watching parked issues.

**Failure shape.** Parking reasons are typically "ambiguous repro steps," "no acceptance criteria," "label-only issue with no body." For ~30% of parked issues, sufficient context is recoverable from linked PRs, prior comments, or the project wiki — the original triage runner just didn't look there.

**Proposed remediation.** New caretaker loop `TriageRetryLoop` (W2), 24h tick. Reads issues with `hydraflow-parked` label. For each, re-runs the triage runner with `parking_reason` injected and an explicit "look for context in: linked issues, prior comments by repository maintainers, wiki entries matching keywords in the title" instruction. Tracks attempts via `state.bump_auto_triage_attempts(issue_id)`. After 3 attempts the loop labels `human-required` with a structured diagnosis comment.

**Success metric.** Median age of `hydraflow-parked` issues drops from "indefinite" to ≤72h. Track via a `triage_park_age_hours` Honeycomb metric (new).

**Work-items.**
- New file: `src/triage_retry_loop.py` (5-checkpoint wired per `dark-factory.md` §2.1).
- New config field: `triage_retry_interval` (default 86400s = 24h), `triage_retry_max_attempts` (default 3).
- New state column: `auto_triage_attempts` keyed by issue id.
- Unit + MockWorld scenario + sandbox e2e per `docs/standards/testing/README.md`.

---

### `discover`

**Matrix HITL trigger:** Research brief fails coherence evaluation after retry → `hitl-escalation` label applied, then `AutoAgentPreflightLoop` attempts autonomous recovery before issuing `human-required`.

**Root cause.** `DiscoverRunner._escalate_stuck` (`src/discover_runner.py:212-265`) fires when the `discover-completeness` evaluator scores the brief below threshold twice. Looking at coherence-failure transcripts, the failure is overwhelmingly a missing-context problem: the brief covered the explicit ask but missed a touched module's prior incident, an ADR that constrains the design space, or a related sub-issue. The current retry uses the same prompt against the same context — the model can't manufacture facts it wasn't given.

**Failure shape.** Two sub-modes: "narrow brief, broad ask" (model didn't expand the question) and "missing prior art" (relevant ADRs / wiki entries not in context). Both are addressable by explicit query expansion before retry.

**Proposed remediation.** On first coherence-evaluator failure, dispatch a `discover-expander` subagent: prompt asks "what specifically would lift coherence by 30%? Propose 3 new research queries." The runner takes the proposed queries, fetches the corresponding wiki entries / ADR cross-references, attaches them to the context, and retries once. Only if the post-expansion retry still fails does it escalate.

**Success metric.** Discover-coherence retry-success rate (currently ~0% by construction). Target: ≥40% post-W3.

**Work-items.**
- New skill / prompt: `docs/superpowers/skills/discover-expander.md`.
- Hook in `src/discover_runner.py` before `_escalate_stuck`.
- Audit entry type extension: `discover_expansion_attempted` in the discover audit JSONL.

---

### `shape`

**Matrix HITL trigger:** `shape_timeout_minutes` exceeded with no human direction selection, or expert council remains split after 2 rounds → `hitl-escalation` + `AutoAgentPreflightLoop` pre-flight before `human-required`.

**Root cause.** The expert-council pattern (`src/shape_phase.py:239-320`) is good — diverse personas debate direction selection and a mediator synthesises a split vote. The cap at 2 rounds is the issue: round 2 sees prior votes + mediation, but the personas don't change. If round 1 split was a genuine principled disagreement (security vs. velocity, for example), round 2 just re-states the same positions.

**Failure shape.** Round-2 splits cluster around "the council can see the trade-off but no member has standing to break the tie." The mediator currently synthesises but doesn't introduce new lenses.

**Proposed remediation.** Round 3 with a **diversified-persona prompt**: replace the standard council with three new personas — an explicit dissenter ("argue the rejected position with full force"), an explicit consensus-seeker ("find the smallest commitment both sides can accept"), and a "what would we regret in 6 months" persona that prioritises reversibility. The vote at the end of round 3 uses majority instead of consensus. Only a 3-3 round-3 split escalates.

**Success metric.** Council-split escalation rate drops by ≥50%.

**Work-items.**
- Extend `expert_council.py::ExpertCouncil.mediate` to accept a `round` parameter and switch personas at `round == 3`.
- New persona definitions in `docs/superpowers/skills/shape-council-personas.md`.
- Unit tests + MockWorld scenario covering 3-round flow.

---

### `plan`

**Matrix HITL trigger:** Plan validation fails twice consecutively, or epic-child evidence validation fails → `hitl-escalation` applied, `AutoAgentPreflightLoop` attempts recovery, escalates to `human-required` if 3 attempts exhausted.

**Root cause.** `PlanReviewer` validation failures (visible in `src/plan_phase.py:649-674`) typically cite: missing ADR touchpoints, incomplete decomposition (`<3` sub-issues for a non-trivial change), or evidence-of-already-satisfied conflicting with the issue body. The retry sees the validation errors but not the corpus that would resolve them — the planner has to guess which ADRs are relevant, or which prior PRs touched the same files.

**Failure shape.** Two flavours: "missing context" (planner didn't know about an ADR or a prior conflict) and "ambiguous spec" (the issue itself is under-specified). The first is automatable; the second is a discover-phase failure showing up late and should ideally route back to discover rather than escalate.

**Proposed remediation.** New `plan-touchpoint-expander` subagent dispatched on first `PlanReviewer` failure: takes the validation errors + the touched-files list, walks ADR cross-references, fetches recent PR conflict history (last 30 days) for those files, and emits a structured context block. Planner retry uses this block + `superpowers:writing-plans`-shaped success criteria ("a valid plan has: explicit acceptance criteria, ≥1 ADR touchpoint citation, ≥3 sub-issues for non-trivial changes, evidence-of-already-satisfied check"). Issues where the validation error is "ambiguous spec" route back to `hydraflow-discover` instead of escalating.

**Success metric.** Plan-validation retry-success rate. Target: ≥50% post-W3.

**Work-items.**
- New subagent: `src/planner_touchpoint_expander.py` or skill `docs/superpowers/skills/plan-touchpoint-expander.md`.
- Hook in `src/plan_phase.py` before `_escalate_to_hitl`.
- Add "route-back-to-discover" branch for ambiguous-spec validation errors.

---

### `implement`

**Matrix HITL trigger:** Attempt cap reached or zero-diff branch detected → `hitl-escalation` label; `SandboxFailureFixerLoop` gets up to 3 auto-fix attempts before escalating to sandbox HITL queue.

**Root cause.** Zero-diff branches (`src/implement_phase.py:128-160`) are the canonical "prompt was too narrow" signal — the agent ran, produced nothing, and the system has no idea why. Attempt-cap reaches (`_check_attempt_cap` at line 418) usually mean the agent kept failing the same quality check on each attempt.

**Failure shape.** Both modes share a root cause: no spec-compliance feedback between attempts. `superpowers:subagent-driven-development` solves this for substantial features — every task gets a spec-compliance review then a code-quality review. ImplementPhase doesn't currently use this pattern; it dispatches the agent, reads the result, and either accepts or escalates.

**Proposed remediation.** Promote the two-stage review into ImplementPhase. On zero-diff or attempt-cap, dispatch a spec-compliance reviewer subagent first. Its findings become the prompt anchor for the next attempt: "the prior attempt produced no diff because *spec-compliance reviewer's finding*; address this specifically." This adds one subagent dispatch per escalation, not per attempt, so the cost increase is bounded.

**Success metric.** Zero-diff escalation rate. Target: ≥40% reduction post-W5.

**Work-items.**
- Wire `superpowers:subagent-driven-development` two-stage pattern into `ImplementPhase._escalate_no_changes_to_hitl` and `_escalate_capped_issue`.
- New audit entry: `spec_compliance_review_attempted` in implement audit JSONL.
- Unit tests covering the two-stage path; MockWorld scenario for zero-diff recovery.

---

### `review`

**Matrix HITL trigger:** Persistent CI red, merge conflict with main, visual validation failure, or baseline-approval required → `hitl-escalation` applied, `AutoAgentPreflightLoop` pre-flights before `human-required`.

**Root cause (CI red).** `SandboxFailureFixerLoop` is invoked but currently receives only the sandbox failure log as context. It doesn't see the original implementation's test transcript or the diffs of the last 3 commits — so on red CI it's debugging blind.

**Root cause (merge conflict with main).** Real conflicts require human judgment about which side "wins." No autonomous attempt has standing here.

**Root cause (visual validation failure).** Visual diffs are inherently judgment calls — "is this the same component or different?" — and humans are the ground truth.

**Failure shape.** CI-red is addressable (CTX). Merge-conflict and visual-validation are HITL-by-design.

**Proposed remediation.** For CI-red specifically: extend the `SandboxFailureFixerLoop` prompt to attach the original implementation's test transcript (from the implement-phase audit JSONL) and the last 3 commits' diffs. Merge-conflict and visual-validation escalations stay HITL.

**Success metric.** CI-red escalation rate (specifically). Target: ≥30% reduction post-W3 extension.

**Work-items.**
- Modify `src/sandbox_failure_fixer_loop.py` context-gather to read implement-phase audit.
- Capture-and-attach diffs for last 3 commits in the failure-fixer prompt.

---

### `HITL`

**Matrix HITL trigger:** After 3 autonomous pre-flight attempts fail, `human-required` label applied; humans exclusively monitor `human-required` — not `hitl-escalation` directly.

**Root cause.** `AutoAgentPreflightLoop` currently spawns the same generic "lead engineer" persona regardless of which phase escalated. A `discover-stuck` sub-label issue and an `implement-stuck` sub-label issue both go to the same playbook bundle and the same prompt. The sub-label is used for label-removal logic and the deny-list, but not for specialist routing.

**Failure shape.** The audit JSONL shows preflight resolution rate varies wildly by sub-label (high for review-stuck where the fix is mechanical, low for discover-stuck where a specialist research persona would help). The structure exists; the routing is missing.

**Proposed remediation.** Specialist-aware preflight (W1). Sub-label routes to a playbook bundle: `discover-stuck` → discover-expander, `shape-stuck` → council-mediator, `plan-stuck` → touchpoint-expander, `implement-stuck` → spec-compliance-reviewer, `review-stuck` → ci-debugger. Existing sub-labels with no specialist match fall back to the current generic persona. Each playbook bundle is a separate prompt template + tool restriction profile.

**Success metric.** Per-sub-label preflight resolution rate. Target: every sub-label's rate moves above its current generic-persona rate post-W1.

**Work-items.**
- Refactor `src/preflight/agent.py` to accept a playbook bundle keyed by sub-label.
- New playbook directory: `src/preflight/playbooks/`.
- Audit JSONL extension: `playbook_id` field on every entry.
- Per-playbook tests + an integration test asserting routing.

---

### `merge`

**Matrix HITL trigger:** RC red that `StagingBisectLoop` cannot attribute after bisect → `hitl-escalation` filed; otherwise merge is fully automated with no human gate.

**Root cause.** Bisect ambiguity arises when multiple commits in the same RC interact (e.g., a config change in commit A only fails when paired with a code path enabled in commit B). The bisector correctly reports "cannot attribute to single commit" — that is the honest signal. No autonomous attempt has standing to commit to a culprit without bisect-level evidence.

**Verdict.** **HITL-by-design.** Preserve.

**Proposed mitigation (optional).** When `StagingBisectLoop` returns "cannot attribute," file a `hydraflow-find` issue capturing the bisect transcript and the failed-test signal. This adds the case to the corpus that `CorpusLearningLoop` ingests, so future bisects with similar shapes have prior-art context. This is not a HITL-removal proposal; it is a "the human's eventual fix becomes signal for the next cycle" proposal.

**Success metric.** None for HITL rate (preserved). Track: count of `hydraflow-find` issues filed from bisect-ambiguity events, monthly.

**Work-items.**
- Minor: `src/staging_bisect_loop.py` on cannot-attribute path, append `hydraflow-find` filing.

---

## Workstream summary

| ID | Title | Phases addressed | Bead |
|---|---|---|---|
| W1 | Specialist-aware preflight playbook bundles | HITL (all phases benefit transitively) | `advisor-5nxu` |
| W2 | `TriageRetryLoop` for parked-issue re-entry | triage | `advisor-vz1l` |
| W3a | Discover-expander subagent | discover | `advisor-98eh` |
| W3b | Plan touchpoint-expander subagent | plan | `advisor-mba6` |
| W3c | SandboxFailureFixer context extension | review (CI-red only) | `advisor-tuu6` |
| W4 | Shape council round 3 with diversified personas | shape | `advisor-lya4` |
| W5 | Two-stage spec-compliance review in ImplementPhase | implement | `advisor-5uuc` |

## Open questions

1. **W3 splits into one bead per phase or one bead total?** The remediation pattern is the same (context-expander subagent before retry) but the prompts differ substantially. Split into three beads (discover, plan, review-CI) for traceability.
2. **Order of workstream landing.** Recommend: W1 first (lowest blast radius, highest leverage — every other workstream benefits from specialist routing), then W2 (independent), then W3/W4/W5 in any order.
3. **Specialist preflight + context-expander overlap.** Once W1 routes by sub-label, W3's discover-expander and plan-touchpoint-expander become playbook-bundle implementations of W1. They are not redundant — they ARE the playbooks.

## Drift exemptions

None claimed. Every phase's mitigation is implementable; the HITL-by-design entries (`merge`, partial-`review`) are justified inline and don't constitute exemptions from the contract — they are the contract's "raging fires" boundary.
