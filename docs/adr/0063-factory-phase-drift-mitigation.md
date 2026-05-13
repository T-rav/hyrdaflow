# ADR-0063 — Factory-Phase Drift Mitigation

**Status:** Proposed
**Date:** 2026-05-12
**Slice:** Documentation audit roadmap, slice #4 of 5
**Input:** `docs/arch/coverage_matrix.md` §3 (Factory phases), 2026-05-12 baseline
**Companion report:** `docs/arch/factory_phase_drift_2026-05-12.md`

## Context

The dark-factory contract ([`docs/wiki/dark-factory.md`](../wiki/dark-factory.md) §1) commits HydraFlow to "humans only paged for raging fires." Every `hitl-escalation` issue is supposed to flow through `AutoAgentPreflightLoop` (ADR-0050) for up to three autonomous recovery attempts before a human sees `human-required`.

Slice #1's coverage matrix surfaced the per-phase HITL triggers as of `06781b1b`. Looking across all eight pipeline phases reveals an uneven story:

- The `HITL` phase is a thin general-purpose retry. Auto-Agent re-runs the same playbook with prior-diagnosis context, no specialist agent, no context expansion.
- Five phases (`discover`, `shape`, `plan`, `implement`, `review`) escalate on what are essentially **model competence failures** — the coherence evaluator said no, the plan reviewer said no, the council was split, the implementation produced no diff. These are not raging fires; they are signals the autonomous attempt did not have enough context, the wrong specialist, or the wrong prompt structure.
- One phase (`triage`) has a structural gap: `needs_info` parks the issue and **no loop ever re-attempts triage**. Parked issues sit indefinitely awaiting a human clarification comment.
- One phase (`merge`) escalates only on `StagingBisectLoop` failing to attribute a culprit. That is a genuine investigative failure — a real fire.

Cost of the status quo: parked issues bleed cycle time, repeated escalations on the same prompt-failure mode produce audit noise, and humans are paged for issues the system has the latent skills to resolve (the superpowers skill pack already encodes the relevant patterns — `brainstorming`, `writing-plans`, `subagent-driven-development`, `systematic-debugging`).

## Decision

For each of the eight factory phases, classify the current HITL trigger as one of:

- **CTX** — Autonomous context expansion (expand brief, attach prior transcripts, pull cross-referenced ADRs) before retry.
- **COUNCIL** — Multi-agent specialist council (already used in `shape`; extend pattern).
- **PROMPT** — Sharper prompt structure with explicit success criteria (apply `superpowers:writing-plans` discipline).
- **RECOVERY** — New autonomous-recovery mini-loop (close a structural gap).
- **HITL-BY-DESIGN** — Preserve human escalation; the failure mode is a real fire.

Per-phase decision:

| Phase | Category | Mitigation summary |
|---|---|---|
| `triage` | **RECOVERY** | New `TriageRetryLoop` (caretaker, 24h tick) that re-runs parked-issue triage with the original parking reason as context. Cap at 3 retries before `human-required`. |
| `discover` | **CTX** | On coherence-evaluator failure, dispatch a "what would 30% more confidence require?" subagent that proposes added research queries; expand the brief and retry once before escalating. |
| `shape` | **COUNCIL** | Extend existing expert-council to a third round with a **diversified-persona** prompt when round 2 remains split. Keep HITL only when round 3 still splits. |
| `plan` | **CTX + PROMPT** | New `plan-touchpoint-expander` subagent dispatched on first `PlanReviewer` failure: pulls cross-referenced ADRs, recent PR conflicts on touched files, and current wiki entries for affected modules; the planner retries with that context attached and `writing-plans`-shaped success criteria. |
| `implement` | **PROMPT** | Promote `superpowers:subagent-driven-development`'s two-stage (spec-compliance then code-quality) review into ImplementPhase. Zero-diff branches re-dispatch with the spec-compliance reviewer's finding as the new prompt anchor. |
| `review` | **CTX** | When `SandboxFailureFixerLoop` is invoked, the failure-fixer prompt receives the original implementation's test transcript and the last 3 commits' diffs (currently it sees only the sandbox failure log). Visual-validation and merge-conflict failures remain HITL-by-design. |
| `HITL` | **CTX** | `AutoAgentPreflightLoop` becomes specialist-aware: route by sub-label to a phase-specific playbook (`discover-stuck` → discover-expander, `plan-stuck` → touchpoint-expander, etc.) rather than the current generic lead-engineer persona. |
| `merge` | **HITL-BY-DESIGN** | `StagingBisectLoop` failing to attribute is a real fire; auto-agent cannot reasonably propose a culprit when bisect itself produced ambiguity. Preserve. Optional: file a `hydraflow-find` issue capturing the bisect transcript so the next cycle has a corpus entry. |

### Implementation strategy — five workstreams

Each mitigation lands as a separate PR with the production-readiness loop applied (§3 of `dark-factory.md`):

1. **W1 — Specialist-aware preflight (HITL phase).** Generalize `AutoAgentPreflightLoop` so the sub-label routes to a playbook bundle. Backwards-compatible: existing playbooks become the `_default` for their sub-labels. New playbooks: `discover-stuck`, `shape-stuck`, `plan-stuck`, `implement-stuck`, `review-stuck`.
2. **W2 — TriageRetryLoop (triage gap).** New caretaker loop (5-checkpoint wire). 24h tick. Reads `hydraflow-parked` issues, re-runs the triage runner with `parking_reason` injected as context, decrements an `auto_triage_attempts` counter, and applies `human-required` after the cap.
3. **W3 — Discover and Plan context-expanders.** Two skills + matching subagent dispatch hooks. Discover: "expand-query" subagent that proposes ≥3 new research queries when coherence < threshold. Plan: "touchpoint-expander" subagent that walks ADR cross-references and recent PR conflict history for the touched files.
4. **W4 — Shape council round 3.** Extend `ExpertCouncil.mediate` to a third diversified-persona round when round 2 ties. Personas: an explicit dissenter, an explicit consensus-seeker, a "what would we regret in 6 months" persona.
5. **W5 — ImplementPhase two-stage review.** Wire `superpowers:subagent-driven-development` per-task pattern into `ImplementPhase` directly so zero-diff/attempt-cap issues re-dispatch with the spec-compliance review as the prompt anchor before escalating.

Each workstream gets its own bead under the `factory-phase-drift` label.

### What this is not

- **Not "retry harder."** Adding more attempts to the same failing prompt is exactly what the matrix shows already happens (3 preflight attempts, 2 plan-reviewer retries, 2 council rounds). The remediation is changing the *content* of the next attempt — more context, different specialist, sharper success criteria.
- **Not removing all HITL.** `merge` bisect-can't-attribute, `review` visual-validation failure, and `review` merge-conflict-with-main remain HITL-by-design because no autonomous attempt has the standing to commit to those resolutions.
- **Not a new orchestrator.** All mitigations land inside existing phase loops, `AutoAgentPreflightLoop`, or a single new caretaker (`TriageRetryLoop`). No new runtime topology.

## Consequences

**Positive:**

- Closes the triage-parking gap (currently the only phase with no autonomous recovery).
- Reduces `human-required` rate for prompt-failure modes that have known remediations (context expansion, specialist routing).
- The specialist-aware preflight makes audit JSONL more useful: a failed `plan-stuck` attempt records the touchpoint set the expander pulled, which is itself a corpus signal for the principles-audit loop.
- Establishes a phase-by-phase mitigation pattern other ADRs can extend.

**Negative:**

- Adds wall-clock per issue. Context expansion is a real subagent dispatch (~30-120s) that runs before the retry. Mitigated by: only running on first failure, not every attempt; tracking spend in the existing `auto_agent_daily_budget_usd` cap.
- More configuration surface. Each playbook adds a prompt template + sub-label routing entry. Mitigated by: the existing playbook bundle structure already accepts this growth pattern.
- Risk of "false recovery" — auto-agent resolves something the human would have caught. Mitigated by: every preflight resolution still produces a PR that goes through the existing review phase; the auto-agent does not bypass review.

**Measurability:**

- Track `hitl-escalation` → `human-required` transition rate per phase, monthly. Target: 30% reduction within one quarter of W1-W5 landing.
- Track `hydraflow-parked` median age. Target: drop from "indefinite" to "≤72h" once `TriageRetryLoop` is live.
- Audit JSONL inspection: count distinct sub-labels resolved by Auto-Agent per week pre/post W1.

**Risks:**

- Auto-agent confidently producing wrong fixes is the canonical risk. The ADR-0050 mitigations (tool restrictions, principles-audit deny-list, human review of resulting PR) apply unchanged.
- Context-expansion subagents can themselves drift — produce queries that don't actually help. Detection: track post-expansion coherence-evaluator score; if expansion doesn't lift score on >50% of cases, the expander itself becomes a `factory-phase-drift` follow-up.

## Alternatives Considered

1. **Just raise `auto_agent_max_attempts`.** Rejected: retries against the same prompt have diminishing returns. The matrix already shows attempts at 3 (preflight) plus phase-level retries; the failures are not retry-count-bound, they are context-bound.
2. **Single mega-skill that handles every escalation generically.** Rejected: the value of specialist routing is that each phase failure has a distinct remediation shape. A generic skill would have to re-detect the phase from the issue body, which is what sub-label routing already encodes.
3. **Replace `AutoAgentPreflightLoop` with parallel-specialist dispatch.** Rejected for now: introduces concurrency risk on the same worktree and increases LLM spend without evidence that serial specialist runs are insufficient. Kept as a future option if W1 doesn't move the rate enough.

## Source-file citations

- `src/triage_phase.py` — current parking path with no autonomous re-entry
- `src/discover_runner.py` — `_escalate_stuck` coherence-failure path
- `src/shape_phase.py` — `ExpertCouncil` two-round mediation
- `src/plan_phase.py` — `PlanReviewer` validation + `PipelineEscalator`
- `src/implement_phase.py` — `_check_attempt_cap`, `_escalate_no_changes_to_hitl`
- `src/review_phase/_phase.py` — visual-validation, merge-conflict, CI-red escalation handlers
- `src/auto_agent_preflight_loop.py` — current generic preflight loop
- `src/preflight/` — playbook bundle, decision, context-gather
- `docs/wiki/dark-factory.md` §1 — contract, §3 — production-readiness loop
- `docs/adr/0050-auto-agent-hitl-preflight.md` — preflight foundation this ADR extends

## Touchpoints

- ADR-0050 (Auto-Agent HITL Pre-Flight) — this ADR extends preflight from a single generic playbook router to a specialist-aware playbook bundle.
- ADR-0044 (HydraFlow principles) — "humans only paged for raging fires" is the principle this ADR operationalizes per-phase.
- ADR-0033 (Gate-triage as call) — Triage's "park, not escalate" pattern is preserved; W2 adds re-entry, not bypass.
- ADR-0034 (Auto-triage toggle) — `TriageRetryLoop` must respect the same toggle.
- ADR-0049 (Trust-loop kill-switch convention) — `TriageRetryLoop` ships with the standard kill-switch.
- `docs/wiki/dark-factory.md` — update §1 contract bullet "every escalation has an autonomous fix-attempt path" once W1-W5 land.
