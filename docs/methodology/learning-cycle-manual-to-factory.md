# Learning Cycle — Manual Work → Methodology → Factory Absorption

**Status:** Methodology
**Last updated:** 2026-05-17
**Cross-references:**
- [`factory_operation`](../standards/factory_operation/README.md) §"Self-modifying maintenance mode" — sibling cycle (factory learning from itself at runtime)
- [`self-documenting-architecture`](self-documenting-architecture.md) — how docs stay alive
- [`onboarding-hydraflow-format-repos`](onboarding-hydraflow-format-repos.md) — first complete worked example of this cycle

---

## What this document is

The **meta-cycle** by which HydraFlow grows new capabilities: operator + Claude do work manually a few times, extract the pattern into a methodology doc, file issues for the factory to absorb the capability, factory builds it, next time the work is automated. The doc you're reading was produced by this same cycle.

It is the **outer loop** that complements the existing **inner loop** in [`factory_operation/README.md`](../standards/factory_operation/README.md) §"Self-modifying maintenance mode":

| Loop | Source of learning | Output |
|---|---|---|
| **Inner** (already documented) | Factory runtime — recurring CI failures, recurring documentation gaps, recurring design oversights observed across N production runs | Caretaker loops, principles-audit checks, anti-patterns codified in standards |
| **Outer** (this document) | Operator + Claude doing capability work manually — bootstrapping new repos, designing new dashboards, adding new safety models | Methodology docs, interface proposals, issues for the factory to absorb the capability |

Both cycles produce the same shape of output (the factory grows new lobes), but the inputs are different. Inner observes; outer creates.

---

## When this cycle applies

Use this cycle when:

- You're doing a **new kind of work** that the factory doesn't yet support (e.g. bootstrapping a new project type, integrating a new external service, adding a new safety model)
- The work is **repeatable enough** that doing it again next time would benefit from automation
- You've done it **at least twice manually** so the pattern is real, not imagined
- The friction you hit is **mechanical, not creative** — automatable in principle

Do NOT use this cycle when:

- You've done the work once. One data point is not a pattern. Ship it; learn from the second run.
- The work is **creative throughout** with no mechanical core (e.g. inventing a new architectural pattern). Methodology docs work best on the mechanical parts.
- The friction is **operator-specific** (your preferences, your toolchain). The factory should not absorb your personal workflow quirks.

---

## The cycle

```
┌──────────────────────────────────────────────────────────────────┐
│  1. Do the work manually (N=1)                                   │
│     · operator + Claude collaborate                              │
│     · capture friction as you go (don't try to generalize yet)   │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  2. Do the work manually a SECOND time (N=2)                     │
│     · same shape, different domain                               │
│     · apply lessons from N=1                                     │
│     · note which lessons stuck, which were one-off               │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  3. Extract the pattern into a methodology doc                   │
│     · what's invariant (the kernel)                              │
│     · what varies (customization knobs)                          │
│     · friction catalog (with cause + fix + prevention)           │
│     · mechanical vs creative split                               │
│     · be honest about confidence level (N=2 is shaping, not      │
│       validation)                                                │
│     · save to docs/methodology/<topic>.md                        │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  4. Propose an interface that absorbs the friction               │
│     · same doc, separate section                                 │
│     · operator-facing UX + backend services                      │
│     · phased implementation roadmap                              │
│     · explicit open questions                                    │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  5. Critique pass (with operator playing "rude reviewer")        │
│     · find what's overengineered                                 │
│     · find what's hand-wavy                                      │
│     · find what's missing (e.g. error story)                     │
│     · find what oversells "validation"                           │
│     · close speculative issues; soften aspirational claims       │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  6. File issues for the factory to absorb the capability         │
│     · 1 hydraflow-epic + N hydraflow-epic-child issues           │
│     · methodology doc IS the shape-phase artifact                │
│     · plan issues reference the doc instead of re-deriving       │
│     · 3rd-domain validation as the explicit acceptance gate      │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  7. Factory builds it (its own pipeline does the work)           │
│     · DiscoverLoop picks up the hydraflow-find issues            │
│     · SHAPE → PLAN → IMPLEMENT runs normally                     │
│     · the capability ships                                       │
└──────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  8. Next time the work is needed: automated (N=3+)               │
│     · operator uses the new capability                           │
│     · friction that surfaces here feeds the INNER cycle          │
│       (recurring failures → caretaker loops)                     │
│     · methodology doc updated with new confidence: "validated"   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Why this works

### Methodology docs are first-class artifacts

The doc produced in step 3 is not background reading — it's the **shape-phase output** for the issues filed in step 6. Future intent like "build feature X based on methodology Y" should be processable by the factory's SHAPE phase without re-deriving the design from scratch.

This is what makes the cycle compound. Each pass through the cycle leaves an artifact future intent can consume. The factory gets smarter without anyone explicitly teaching it.

### N=2 is the minimum honest sample

One manual pass produces interesting observations but they're indistinguishable from random noise. Two manual passes let you see what's repeating. Three would be better but the cost of a third manual pass usually exceeds the cost of automating.

The trade-off: at N=2, your methodology will be wrong in places. That's why step 5 (critique pass) exists, and why the doc should explicitly declare its confidence level rather than claiming "validated."

### The factory eats its own dog food

Filing issues against HydraFlow itself for capability absorption means HydraFlow's pipeline processes the work. If the pipeline can't handle "build a wizard for bootstrapping HydraFlow-format repos," that's evidence the pipeline isn't yet capable of meta-work — itself a useful signal.

The dog-food path also forces honesty: if SHAPE phase can't consume the methodology doc as input, the doc isn't crisp enough. If PLAN phase can't expand the proposed phases into tasks, the phases weren't decomposed well. Each handoff is a quality gate.

### Critique is non-optional

Step 5 is the difference between a methodology doc that's useful and one that's wishful. Without an adversarial pass, the doc will:

- Oversell validation (N=2 ≠ proven)
- Skip error stories (mockups show happy paths)
- Hand-wave hard problems ("the AI extracts structured fields reliably")
- File speculative issues for problems you don't have evidence for yet
- Bury real acceptance criteria

The operator-as-rude-reviewer pattern works well: ask the operator to drop the helpful tone and read the doc as an antagonist would. What they find usually maps directly to the gaps that would hurt future readers most.

---

## What the methodology doc must contain

Beyond the obvious (the pattern itself), a methodology doc from this cycle must include:

1. **Confidence level** at the top — what's high vs medium vs low confidence, with evidence type for each
2. **Friction catalog** with cause + fix + prevention for each entry — the friction is the data the cycle exists to capture
3. **Mechanical vs creative split** — the absorption target is the mechanical part; creative parts stay with operator + Claude
4. **Customization knobs** — what varies legitimately across applications of the pattern
5. **Error story** — what fails, how it's detected, how it's recovered
6. **Open questions** — what's unresolved, with reopen criteria for closed sibling issues
7. **Quick-reference manual procedure** — the pre-automation pathway, preserved for operators who need it before the factory absorbs the capability
8. **Toolchain dependencies** — what the manual procedure assumes you have installed; methodology docs should not silently assume Claude Code + plugins
9. **Acknowledgments** — links to the worked-example repos that produced the data

---

## Anti-patterns

### Premature methodology (N=1 syndrome)

You do something once, find it interesting, write a methodology doc. The doc claims patterns that one data point can't support. Future readers treat it as gospel and propagate the wrong pattern.

**Fix:** wait for N=2. If you can't get to N=2, write a wiki entry instead — it sets the confidence bar lower.

### Aspirational doc disguised as design

The doc says "backend absorbs friction silently" without specifying how. Reads like a design but is actually a wish list. Future implementers either over-build (trying to live up to the aspirational language) or under-build (because the wishes were vague).

**Fix:** every claim in the doc should be falsifiable. If you can't write a test for it, soften the claim or remove it.

### Over-generalization

You did two bootstraps for similar Python projects and wrote a doc claiming this pattern applies to bootstrapping ANY HydraFlow-format repo (including the Rust ones you haven't done). The pattern probably doesn't generalize as far as the doc implies.

**Fix:** scope the doc to the cases you've actually observed. Note where generalization is unproven.

### Issue inflation

You file an epic + 4 phase issues + 2 speculative meta-issues. The phase issues aren't really independent. The speculative issues solve problems that don't exist yet. You feel productive but the issue tracker is now noisy.

**Fix:** close speculative issues with explicit reopen criteria. Acknowledge phase interdependence in the epic. File the smallest unit of value as its own issue, not a phased fantasy.

### Skipping the critique pass

You write the doc, file the issues, ship to staging. No one reads the doc adversarially. Six months later the implementer hits all the gaps and realizes the doc was a fairy tale.

**Fix:** the critique pass is part of the cycle, not a nice-to-have. Schedule it. If the operator won't do it, find someone else who will. A doc that hasn't been critiqued is a doc that's wrong somewhere.

### Forgetting to update confidence level

The cycle produces a doc, the factory absorbs the capability, the 3rd-domain bootstrap succeeds. The doc still says "medium confidence — not validated against a 3rd bootstrap." Nobody updates it. Future readers don't know if the doc is still in proposal state or has graduated.

**Fix:** updating the confidence section is part of the absorption acceptance criteria. When the 3rd domain ships, the doc's confidence section gets a PR.

---

## The worked example

[`onboarding-hydraflow-format-repos.md`](onboarding-hydraflow-format-repos.md) is the first complete pass through this cycle in HydraFlow's history. Steps mapped:

| Step | What happened | Where to look |
|---|---|---|
| 1 (N=1) | Bootstrapped `amplifier` manually | `T-rav/amplifier` repo + the session that produced it |
| 2 (N=2) | Bootstrapped `harvestd` manually, applied lessons from amplifier | `T-rav/harvestd` repo |
| 3 (extract) | Wrote `docs/methodology/onboarding-hydraflow-format-repos.md` | PR #8866 |
| 4 (propose interface) | Wizard + dashboard integration + 3 backend services + 4-phase roadmap | Same doc |
| 5 (critique) | Operator-as-rude-reviewer pass produced 12 critiques | PR #8936 |
| 6 (file issues) | Epic [#8929] + 4 phase issues [#8930-8933] + 2 speculative (later closed) | hydraflow issues |
| 7 (factory builds) | TBD — waiting on capacity allocation | future |
| 8 (next time) | TBD — third bootstrap is the validation gate | future |

This doc you're reading was produced in step 8.5 — meta-extracting the pattern OF the cycle from the first complete pass through it.

---

## Cross-references

- [`factory_operation/README.md`](../standards/factory_operation/README.md) §"Self-modifying maintenance mode" — the inner cycle (factory learning from runtime)
- [`self-documenting-architecture.md`](self-documenting-architecture.md) — how docs stay alive once written
- [`onboarding-hydraflow-format-repos.md`](onboarding-hydraflow-format-repos.md) — the first complete worked example
- Future: as more methodology docs land via this cycle, list them here
