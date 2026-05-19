# ADR-0064: Earlier-Adversarial Pipeline — Surface Dissent Before Plan-Reviewer

- **Status:** Accepted (proposed by this PR)
- **Date:** 2026-05-17
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0001](0001-five-concurrent-async-loops.md) (five async loops), [ADR-0002](0002-labels-as-state-machine.md) (labels as state machine), [ADR-0029](0029-caretaker-loop-pattern.md) (caretaker loop pattern), [ADR-0051](0051-iterative-production-readiness-review.md) (iterative production-readiness review), [ADR-0053](0053-ubiquitous-language-as-living-artifact.md) (ubiquitous language as living artifact). See also `docs/wiki/dark-factory.md` §3 (convergence loop).
- **Enforced by:** `src/adversarial_retry_loop.py` (shared retry primitive), `src/complexity_gate.py` (routing), `src/plan_phase.py` / `src/shape_phase.py` / `src/discovery_council.py` (call sites), `src/wiki_carryover.py` (carryover→knowledge), `tests/scenarios/test_adversarial_pipeline.py` + `tests/regressions/test_adversarial_pipeline_regressions.py` (behaviour pinning).

## Context

Today the first adversarial gate in the issue lifecycle is the **Plan Reviewer** — a 7-dimension critique that runs *after* the planner has finished writing. Every step upstream (Discovery, Shape, research, planner) operates with a single perspective and no structured dissent. Mistakes made early carry downstream: misframed problems become misfit specs become misfit code, and the gap only surfaces at PR-time fresh-eyes review (per [ADR-0051](0051-iterative-production-readiness-review.md)) — by which point the cost of correction is high.

In a human-staffed factory this is recoverable: an engineer notices and re-spec's. In the **dark factory** (lights-off operating contract, see `docs/wiki/dark-factory.md`) there are no humans to escalate to, so dissent has to be manufactured inside the pipeline itself, structurally, at the points where it is cheapest to act on.

The two empirical anchors that motivated this work:

- Across the trust-fleet (#8390) and auto-agent (#8431, #8439) builds, every Critical fresh-eyes finding was a missed load-bearing convention that *could* have been surfaced by a structured contrarian voter looking at the plan instead of the diff (ADR-0051 §Context).
- Substantial features routinely take 3–5 fresh-eyes review iterations to converge. Each iteration costs LLM calls and wall-clock; moving even one class of finding earlier — *before* the planner commits — is a cost win.

## Decision

Insert three new adversarial stages into the pre-implementation pipeline, plus retrofit one existing stage to the same contract:

| Stage | Phase | Component | New / retrofit |
|---|---|---|---|
| AssumptionSurfacer | Discover + Plan | `src/assumption_surfacer.py` | New |
| DiscoveryCouncil (Problem-Sharpener, Existing-Solution-Hunter, Cheapest-Test-Advocate) | Discover | `src/discovery_council.py` + `src/discovery_council_prompts.py` | New |
| PlanCouncil (Builder, Tester, Risk-Skeptic) | Plan | `src/plan_council.py` + `src/plan_council_prompts.py` | New |
| Pre-impl SpecJudge | Plan (post-planner, pre-implementer) | `src/spec_ac_generator.py` + `src/spec_judge.py` | New |
| Challenger + ExpertCouncil | Shape | `src/shape_challenger.py` + `src/shape_expert_council.py` | Retrofit — already existed; now conforms to the shared contract |

All five stages are wrapped in a single shared primitive — `src/adversarial_retry_loop.py:AdversarialRetryLoop` — with a uniform contract:

1. **Three-retry budget per stage.** The voter produces concerns; the surfaced agent (planner / surfacer / Shape-runner) re-runs with the concerns attached as input. If the next round of voting still produces blocking concerns, retry until budget exhausted.
2. **Oscillation detection.** If round N+1's concerns are structurally the same as round N's (`Concern.fingerprint()` equality), the loop short-circuits as `OscillationDetected` rather than burning the full retry budget on a fixed-point disagreement.
3. **Wide-loop forwarding fallback on exhaustion.** When the retry budget is spent or oscillation is detected, the unresolved `Concern`s are carried forward via the `pending_concerns` channel on `AdversarialState`. The wider issue lifecycle (Plan Reviewer at minimum, but downstream stages too) sees them as `must_address_by` constraints — the tight loop's job is to surface, not to gate forever.

The `Concern` schema (`src/pending_concerns.py:Concern`) is the lingua franca: every adversarial voter speaks it; every consumer downstream knows how to read it.

### Routing — `ComplexityGate`

Not every issue is worth ~30 LLM calls of adversarial machinery. `src/complexity_gate.py:ComplexityGate` classifies each issue as `trivial` or `load_bearing` before the adversarial stages fire. Trivial issues bypass all five stages and route directly to the planner; load-bearing issues run the full pipeline.

The gate is a separate component (not buried in `plan_phase`) so its decision is auditable, testable in isolation, and overridable by label.

### Three transient labels

Per [ADR-0002](0002-labels-as-state-machine.md), all in-flight state lives in GitHub labels:

- `hydraflow-adv-discover-running`
- `hydraflow-adv-plan-running`
- `hydraflow-adv-shape-running`

Each is set on entry and cleared on exit by the dispatcher; they make the active adversarial stage visible to operators and to other loops that need to skip an issue mid-flight.

### Carryover — `ShippedWithKnownGap`

Concerns that survive both the tight loop *and* the wider loop *and* still merge become wiki entries (per [ADR-0032](0032-per-repo-wiki-knowledge-base.md)) via the new `ShippedWithKnownGap` EventBus event. `src/wiki_carryover.py` is the consumer: it converts each unresolved `Concern` into a wiki entry with `confidence: low` and `stale: false`, tagged with the merging PR. This closes the feedback loop — what the factory ships *despite* dissent becomes future input to `AssumptionSurfacer`.

### Six new EventBus events

- `AdversarialStageStarted`
- `AdversarialStageCompleted`
- `AdversarialRetryExhausted`
- `OscillationDetected`
- `ComplexityGateRouted`
- `ShippedWithKnownGap`

Wired in `src/events.py` and reduced into `src/models.py:AdversarialState`. The events are how the dashboard, observability, and downstream loops observe the adversarial pipeline without coupling to its internals.

## Consequences

**Positive:**

- Earlier dissent → cheaper to fix. A misframed problem caught by DiscoveryCouncil costs a re-spec; the same problem caught by fresh-eyes after implementation costs a re-implementation.
- Cost ceiling: load-bearing issues now burn up to ~30 LLM calls across the five adversarial stages (3 retries × ~2 calls/stage × 5 stages, minus the bypassed trivial path). The `ComplexityGate` keeps trivial issues cheap.
- Uniform contract — once you understand `AdversarialRetryLoop` + `Concern`, you understand every adversarial stage. Adding a new voter is a localised change.
- Shape phase's existing Challenger + ExpertCouncil now share the same plumbing — one less ad-hoc retry mechanism to maintain.
- Carryover converts factory-internal dissent into factory-wide knowledge via the repo wiki.

**Negative:**

- 13 new files. State model evolves (`AdversarialState`, `pending_concerns`).
- Pre-impl `SpecJudge` is a **new sibling** to the post-merge `acceptance_criteria.py` / `verification_judge.py` pipeline — it is *not* a refactor of either. They serve different purposes: pre-impl SpecJudge checks "is the spec internally consistent before we implement?"; post-merge verification checks "does the code match the AC?". Both remain the source of truth in their own lane.
- Operators must learn the three new transient labels.

**Risks:**

- Voters could converge on consensus without surfacing dissent. Mitigation: prompts explicitly reward contrary positions; oscillation is a *symptom of working voters*, not a bug, and the wide-loop fallback handles it gracefully.
- Cost regression if `ComplexityGate` mis-classifies load-bearing issues as trivial. Mitigation: gate decisions are logged via `ComplexityGateRouted` events; a follow-up `caretaker_loop` can audit gate decisions against downstream outcomes (forward work).
- Carryover concerns could pollute the wiki with noise. Mitigation: `confidence: low` tagging; `RepoWikiLoop` (ADR-0032) already prunes stale entries.

## Forward work

Flagged during Task 14 reflections — these are *not* in scope for the initial landing but should be filed as `hydraflow-find` follow-ups:

- **Factory wiring** — the new adversarial stages currently fire when their host phases (`plan_phase`, `shape_phase`, `implement_phase`) are invoked directly. Wiring them into the live `loops/` runners is forward work (separate PR, after the contract has soaked).
- **Sandbox seed adversarial slots** — sandbox MockWorld scenarios cover the new stages, but the sandbox *seed corpus* doesn't yet include issues specifically designed to exercise oscillation or gate-misclassification. Forward.
- **`ComplexityGate` audit caretaker** — see "Risks" above. Track classification quality over time.

## Alternatives Considered

- **Skip ComplexityGate, run adversarial stages on every issue.** Rejected — cost ceiling becomes operationally prohibitive; ~30 calls × every trivial doc fix is wasteful and slows the factory.
- **Refactor post-merge `acceptance_criteria.py` to also do pre-impl checking.** Rejected — the two operate on different inputs (spec text vs. code+AC pairs) and have different correctness criteria. Conflating them would couple two pipelines that are happily independent.
- **Single shared council, parameterised by phase.** Rejected — voter personas are phase-specific (a Problem-Sharpener is meaningful in Discover but nonsense in Plan). The shared part is the *retry contract* (`AdversarialRetryLoop`), not the voter set.
- **Block-on-exhaustion instead of wide-loop fallback.** Rejected — in a dark factory there is no operator to unblock; an unresolvable concern would freeze the issue forever. The carryover model trades "perfect resolution" for "always make progress, with the concern visible downstream."

## When to supersede this ADR

- If `AdversarialRetryLoop` is generalised into a primitive that other (non-adversarial) phases adopt, this ADR's "specifically the adversarial pipeline" framing becomes too narrow. Supersede with a broader contract ADR.
- If empirical data shows `ComplexityGate` mis-classifies routinely, supersede with a multi-tier classifier ADR.

## Source-file citations

- `src/adversarial_retry_loop.py` — shared retry primitive (`AdversarialRetryLoop`, `run_with_metrics`).
- `src/pending_concerns.py` — `Concern`, `ConcernResolution`, `AdversarialState` Pydantic models.
- `src/complexity_gate.py` — `ComplexityGate` routing.
- `src/assumption_surfacer.py` — Discover + Plan surfacer.
- `src/plan_council.py` + `src/plan_council_prompts.py` — Builder / Tester / Risk-Skeptic voters.
- `src/discovery_council.py` + `src/discovery_council_prompts.py` — Problem-Sharpener / Existing-Solution-Hunter / Cheapest-Test-Advocate voters.
- `src/spec_ac_generator.py` + `src/spec_judge.py` — pre-impl spec consistency judge (sibling to post-merge AC pipeline).
- `src/shape_challenger.py` + `src/shape_expert_council.py` + `src/shape_phase.py` — Shape phase retrofit.
- `src/adversarial_labels.py` — three transient labels.
- `src/wiki_carryover.py` + `src/post_merge_handler.py` — `ShippedWithKnownGap` consumer.
- `src/events.py` + `src/models.py` — six new EventBus events + state model evolution.
- `tests/scenarios/test_adversarial_pipeline.py` — MockWorld behaviour scenarios.
- `tests/regressions/test_adversarial_pipeline_regressions.py` — regression pins.
- `docs/superpowers/specs/2026-05-16-earlier-adversarial-pipeline-design.md` — design spec **(local-only artifact; not committed to the repo, kept in the worktree as the brainstorming output)**.
- `docs/superpowers/plans/2026-05-16-earlier-adversarial-pipeline.md` — implementation plan (15 tasks).
