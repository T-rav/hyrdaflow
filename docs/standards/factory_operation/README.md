# HydraFlow Standard — Factory Operation (the Kernel)

HydraFlow is a factory. Designs go in. Software comes out. The point of the
factory is that this happens reliably, repeatably, and without the operator
becoming the bottleneck. This document is the kernel — the master standard
that ties the others together so a fresh repo following the HydraFlow format
inherits the entire operating model.

## The factory model

```
                ┌──────────────────────────────────────────┐
                │           DESIGNER (human)               │
                │  writes specs, sets policy, approves     │
                │  scope, evaluates the printed product    │
                └──────────────────┬───────────────────────┘
                                   │  spec / intent / labelled GitHub issue
                                   ▼
                ┌──────────────────────────────────────────┐
                │      FACTORY  (HydraFlow orchestrator)   │
                │  takes specs through the lifecycle:      │
                │    triage → discover → shape → plan →    │
                │    implement → review → HITL → merge     │
                │  governed by the four standards below    │
                └──────────────────┬───────────────────────┘
                                   │  PR → integration branch → release-candidate → main
                                   ▼
                ┌──────────────────────────────────────────┐
                │             PRODUCT (software)            │
                │  shipped via the two-tier branch model    │
                │  passing the full test pyramid            │
                └──────────────────────────────────────────┘
```

The **designer** specifies what should be built. The **factory** builds it
following standards. The **product** ships when the standards are satisfied.

The operator's job is to design, not to micromanage production. Anything
the factory can do for itself, the factory should do for itself.

## The four kernel standards

These four standards together constitute the factory's operating contract.
Every HydraFlow-format repo gets the full set; together they describe how
the factory takes a spec from intent to production.

| Standard | Doc | One-line role |
|---|---|---|
| **Factory autonomy** | [`docs/standards/factory_autonomy/`](../factory_autonomy/README.md) | When agents act vs ask. Tractable + reversible work is factory work, not a permission gate. |
| **Test pyramid** | [`docs/standards/testing/`](../testing/README.md) | Three layers (unit + MockWorld scenario + sandbox e2e) gate every load-bearing feature. |
| **Branch protection** | [`docs/standards/branch_protection/`](../branch_protection/README.md) | Two-tier branch model (integration + release reference) with versioned ruleset configs and a re-applyable apply-script. |
| **Self-modifying maintenance** | this document, §"Self-modifying maintenance mode" | Recurring patterns become caretaker loops; lessons get encoded back into the kernel. |

The factory's behavior emerges from **all four** running together. Removing
any one breaks the contract:

- Without **autonomy**: the operator becomes the bottleneck the factory
  was designed to eliminate.
- Without **the pyramid**: features pass in isolation but break in
  production, which means the operator becomes the test suite.
- Without **branch protection**: bad code reaches the release reference,
  which means the operator becomes QA.
- Without **self-modifying maintenance**: every recurring failure mode
  is solved manually, which means the operator becomes the fix-up bot.

## Self-modifying maintenance mode

The factory does not stay static. As it operates, patterns surface that the
factory itself should automate:

1. **Recurring CI failure modes** that follow a fixed recipe (stale
   auto-regenerated artifacts → run regen + push; lint formatting →
   run lint-fix + push; PR base mismatch → retarget) become caretaker
   loops.

2. **Recurring documentation gaps** (e.g. tests authored against
   non-existent state shapes; placeholders that ship under sNN file
   names but assert nothing meaningful) become principles-audit checks.

3. **Recurring design oversights** (a feature that shipped without one
   of the test-pyramid layers; a PR that bypassed the two-tier branch
   model) become explicit anti-patterns in the relevant standard, plus
   an audit rule.

The flow:

```
   recurring manual fix  ─────────→  hydraflow-find issue  ─────────→
       (3+ instances)                  (filed by the agent that
                                        recognized the pattern)

   ─────────→  caretaker loop spec  ─────────→  loop ships, follows
                  (designer review)                test pyramid

   ─────────→  loop runs in production, factory autonomy expands
```

Each iteration of this flow shrinks the operator's manual surface and
expands the factory's autonomous surface. That is what "self-modifying"
means: the kernel grows new lobes as it learns.

### The discipline

- After **three or more** instances of the same kind of manual fix, the
  agent that recognizes the pattern files a `hydraflow-find` issue. Do
  not silently keep applying the fix; that hides the signal.
- The find-issue includes: what the manual fix is, where it has been
  applied (PR / commit references), the proposed automation, and an
  estimate of cost vs benefit.
- Caretaker-loop specs go through the standard
  brainstorming → spec → plan → TDD execute flow. Self-modification
  does not bypass discipline; it follows it.

## How a fresh HydraFlow-format repo bootstraps

1. Copy `docs/standards/` into the new repo (or fork from the canonical
   HydraFlow template).
2. Copy `CLAUDE.md` Quick Rules + Knowledge Lookup index sections, replacing
   project-specific text but keeping the structure.
3. Run `python scripts/setup_branch_protection.py --apply` to encode the
   two-tier ruleset into GitHub.
4. Set `HYDRAFLOW_STAGING_ENABLED=true` in `.env` (gitignored).
5. Boot the orchestrator. The factory starts running.

The standards are the factory's tooling. Once they're in the repo, the
factory's behavior is reproducible.

## What is NOT in the kernel

The kernel is the operating contract. It does **not** specify:

- The product. Each repo's spec describes what HydraFlow should build for
  that project. The kernel doesn't care; it just runs the factory.
- The model. Which LLM, which tool, which prompt is a configuration
  concern, not a kernel concern.
- The cadence. RC promotion every 4 hours vs every hour vs once a day is
  a configuration knob (`rc_cadence_hours`).

Kernel standards are about **process**: how work moves through the
factory, who has authority over what class of decision, and how the
factory learns. Product, model, and cadence are above (designer-set) or
beside (config) the kernel.

## Discoverability

This kernel doc lives in one place by name and is referenced from:

- `CLAUDE.md` Knowledge Lookup index (the "Cross-cutting standards" row)
- Each of the four sub-standards' "Discoverability" section
- `docs/wiki/dark-factory.md` (the operating-contract wiki entry)

A future audit (extension of `principles_audit_loop`) should check that
every HydraFlow-format repo has all four sub-standards present and the
kernel references resolve.
