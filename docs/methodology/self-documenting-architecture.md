# Self-Documenting Architecture — HydraFlow methodology

> **Status:** Stable (extracted 2026-04-26 from the Architecture Knowledge System v1 build)
> **Scope:** How we build, document, and maintain architectural knowledge for any
> non-trivial software system — and how HydraFlow can apply this autonomously to
> projects it builds.

This document is the **playbook** behind `docs/arch/`, `docs/adr/`, and the
DiagramLoop (L24). It generalizes the patterns we used to build the
Architecture Knowledge System v1 (PRs #8432, #8433, #8434, plus 5 follow-ups).

It is intentionally **methodology, not code**. The code lives in
`src/arch/` and `src/diagram_loop.py`. The code follows this methodology;
the methodology survives the code.

---

## 1. Industry-standard framing

The methodology is a synthesis of established patterns. Each component below
maps to a documented industry practice — the value-add of HydraFlow's variant
is the **autonomous-loop** layer (a dark factory writing its own docs).

| HydraFlow practice | Industry standard | Reference |
|---|---|---|
| Three-layer doc model (Generated / Curated / Narrative) | Diátaxis quadrants partially | Procida, *Diátaxis Documentation Framework* |
| Multi-resolution diagram set (loops, ports, modules, events) | C4 model | Brown, *The C4 Model for Visualising Software Architecture* |
| ADRs with `Enforced by:` + bidirectional cross-reference | Architecture Decision Records | Nygard, *Documenting Architecture Decisions* (2011) |
| `tests/architecture/test_*` drift guards + curated-drift CI | Architecture fitness functions | Ford / Parsons / Kua, *Building Evolutionary Architectures* (2017) |
| `docs/wiki/` Karpathy-style with `json:entry` blocks | Repo wiki / context engineering | Karpathy, *llm.c* repo (informal); Diátaxis explanation quadrant |
| MkDocs Material + Mermaid via `actions/deploy-pages@v4` | Docs as code, in-repo single-source | Gentle, *Docs Like Code* (2017) |
| `DiagramLoop` autonomous regen + CI guard | **Novel** — autonomous living docs | Beyond industry standard |
| Kill-switch convention (`HYDRAFLOW_DISABLE_*`) | Operational kill switches | SRE Workbook, *Reliable Service Limits* |

The novel piece is the autonomous loop. Industry says *"living docs are
docs that update with the code."* HydraFlow says *"living docs are docs an
agent re-derives from the code on a schedule and PR-merges back."* That
is the unlock.

---

## 2. When to apply

Decision tree before invoking the full kit:

```
Is the project > 1 module deep?
├── No → skip; README + inline comments suffice
└── Yes → continue

Is the project an autonomous / multi-loop system?
├── No → minimal (extractors only, no DiagramLoop)
└── Yes → full kit

Is the project > 50k LOC?
├── No → minimal kit + ADRs for load-bearing decisions
└── Yes → full kit + functional area map + freshness model
```

**Minimal kit** = extractors + generators + 1-shot baseline (no autonomous loop).

**Full kit** = minimal kit + DiagramLoop + CI guard + Pages site + ADR drift gate.

Most internal tooling lands in *minimal*. Anything HydraFlow itself ships,
or any operator-facing autonomous system, gets the full kit.

---

## 3. The three-layer model

Treat documentation as a layered pipeline, not a folder. Each layer has a
different decay rate and a different update mechanism. **All three are
required**; none substitutes for any other.

| Layer | Decay rate | Owner | Examples |
|---|---|---|---|
| **Generated** | code speed (hours) | autonomous loop + CI guard | `docs/arch/generated/*.md` |
| **Curated** | feature speed (days) | autonomous loop + humans | `docs/wiki/`, `docs/arch/functional_areas.yml`, `docs/arch/trust_fleet.md` |
| **Narrative** | decision speed (months) | humans + agent reviewers | `docs/adr/`, README, this file |

**Rule.** Each layer cites the next layer up via `module:symbol` or path
references. Each layer is cited by the one below it.

- Generated → cites Narrative (ADRs that justify the code).
- Narrative → declares `Enforced by:` references back to code.
- Curated → explains *why* informally and links both directions.

**Corollary.** When in doubt, classify the artifact by who maintains it,
not by what it contains. A hand-drawn topology diagram is Curated even if
its content overlaps with Generated. A `.likec4` file dumped by an agent
in a one-shot is Generated even if no auto-regen exists yet (delete or
make it auto-regen — don't preserve as Curated).

---

## 4. The 9-artifact starter set

For full-kit deployment, this is the canonical Generated artifact set.
Each is a separate `.md` with embedded Mermaid where useful.

| Artifact | What it shows | Source of truth |
|---|---|---|
| `loops.md` | Background loops (subclasses of base class), tick interval, kill-switch, ADR refs | AST: `class X(BaseLoop)` |
| `ports.md` | Hexagonal Ports + adapters + fakes | AST: `class X(Protocol)` ending in `Port` |
| `labels.md` | State machine transitions (e.g. issue label transitions) | AST: literal `TRANSITIONS = [...]` |
| `modules.md` | Package-level import graph + cycles + cross-layer violations | AST: `import` / `from import` |
| `events.md` | Event bus topology (publishers, subscribers, orphans) | AST: `*.publish(EventType.X)` / `*.subscribe(...)` |
| `adr_xref.md` | Bidirectional ADR ↔ module index | regex over `docs/adr/*.md` |
| `mockworld.md` | Test fakes + scenarios that wire each fake | AST: `tests/scenarios/fakes/Fake*` + scenario imports |
| `functional_areas.md` | Conceptual grouping (caretaking, quality_gates, etc.) | curated YAML + AST membership |
| `changelog.md` | Last 90 days of arch-touching commits | `git log` |

**Drop or add per project shape.** If the project has no Ports, drop `ports.md`.
If it has a domain-specific structure (e.g. routes, handlers), add an
extractor for it. The 9-set isn't sacred; the **principle** of one extractor
+ one generator + one renderable artifact per architectural concern is.

---

## 5. The two-writers / one-set model

Drift detection is what makes Generated artifacts honest. Two writers
must run the **same generation code**:

```
                 ┌─────────────────────────────┐
                 │    src/arch/runner.py       │
                 │    (single source of truth) │
                 └──────────┬──────────────────┘
                            │
              ┌─────────────┴────────────┐
              ▼                          ▼
     Autonomous loop              CI guard (per PR)
     (DiagramLoop, 4h)            (arch-regen.yml)
     - if drift: PR               - if drift: fail build
     - kill-switch                - dry-run only
```

**Rules:**

- **One source of truth.** Both invoke the same `runner.py`. Any drift
  between them is a bug.
- **CI fails the PR.** No "warning" mode. Drift is a build break.
- **The loop opens a PR.** Idempotent at the **branch level** (fixed
  branch name, force-push), title-prefix matched (not date-stamped — handles
  midnight UTC).
- **Both run path-filtered.** Only fire on changes that could affect
  generation (`src/**`, `docs/adr/**`, `docs/arch/**`, `tests/scenarios/fakes/**`,
  `tests/architecture/**`). Avoids burning CI on unrelated PRs.

---

## 6. The freshness model

Every Generated page footer ends with a single italic line:

> *Regenerated from commit `abc1234` on 2026-04-26 14:32 UTC. Source last
> changed at `def5678`. Status: 🟢 fresh.*

States and triggers:

| Badge | Trigger |
|---|---|
| 🟢 fresh | Regenerated within 24h **and** source unchanged since regen |
| 🟡 source-moved | Source changed within 7 days of last regen |
| 🔴 stale | More than 7 days since regen, OR contradicts an Accepted ADR (drift test fail), OR `.meta.json` missing the entry |

**The footer is not a comment.** Use rendered italic markdown so MkDocs
shows it. HTML-comment-wrapped status is invisible to readers and
defeats the purpose.

**Strip the footer for diff comparison.** Timestamp differs every run;
strip during `_strip_footer` before content equality check.

---

## 7. Drift exemptions

Some artifacts are inherently time-varying. Exempt them from drift
detection — but **only after root-causing**, not as a workaround.

| Artifact | Exempt? | Why |
|---|---|---|
| `changelog.md` | yes | Derives from `git log`; changes every commit by design |
| `modules.md` | **no** (we initially exempted, then root-caused) | "Drift" turned out to be stale baseline after merges |
| any artifact with timestamps in body | exempt OR fix | Timestamps belong in `.meta.json` sidecar, not body |
| environment-dependent output | **no** — fix the determinism bug | We mistakenly blamed Linux/macOS once; it was stale baseline |

**Anti-pattern.** "I'll exempt it because CI keeps failing." Investigate
first. Most "drift" is the artifact telling the truth and the baseline
being out of date.

---

## 8. ADR discipline

Every Accepted ADR has these load-bearing fields:

- **Status:** Accepted | Proposed | Superseded | Deprecated
- **Date:** ISO format
- **Enforced by:** comma-separated test path(s), OR `(process)`, OR
  `(historical)`, OR `(none)` (placeholder, must be replaced)
- **Context:** the problem
- **Decision:** the choice
- **Consequences:** what changes downstream
- **Related:** ADR backlinks + module:symbol citations

**The ADR-touchpoint gate.** A PR that modifies any module cited by an
Accepted ADR must either (a) update the ADR or (b) add a `Skip-ADR:
<reason>` line to the PR body. The CI workflow `adr-touchpoints.yml`
enforces this; the script is `scripts/check_adr_touchpoints.py`.

**Skip-ADR is for low-risk uniform changes.** Examples that justify
Skip-ADR:
- Applying a uniform pattern (e.g. kill-switch gate) across many cited
  modules
- Renaming a method without changing its semantics
- Test additions

Examples that **do not** justify Skip-ADR:
- Changing public API on a cited module
- Deleting a function the ADR relies on

---

## 9. Process flow

```
brainstorming  →  spec  →  plans (sequenced)  →  execution per plan  →  fresh-eyes review  →  merge
       │           │           │                     │                       │                  │
       │           │           │                     │                       │                  └─ re-emit baseline
       │           │           │                     │                       │                     before push
       │           │           │                     │                       │
       │           │           │                     │                       └─ subagent reviewer
       │           │           │                     │                          (don't trust CI alone)
       │           │           │                     │
       │           │           │                     └─ TDD per task,
       │           │           │                        commit per task
       │           │           │
       │           │           └─ each plan has its own
       │           │              brainstorm→spec→plan if non-trivial
       │           │
       │           └─ spec reviewed by subagent before plans
       │
       └─ ask 1 question at a time, propose 2-3 options,
          present design sections for user approval
```

**Each gate is a real review.** When PR #8433 (Plan B) and PR #8434 (Plan C)
landed, I trusted CI and skipped fresh-eyes review. Result: 12 wrong-org
URLs across 6 files and a Pages site that 404'd at the documented URL.
A 30-second cross-grep would have caught it. CI checks code, not text.

---

## 10. Anti-patterns we hit (this session)

These are real failures from this build. Each cost time and either had
to be fixed in a follow-up PR or surfaced as user-visible breakage.

1. **Trusting CI in lieu of review.** PRs #8433 and #8434 had wrong-org
   URLs throughout. CI passed because URLs are content, not code.
   *Lesson: fresh eyes at every merge gate, even when CI is green.*
2. **Misdiagnosing root cause.** `modules.md` drift was blamed on
   Linux/macOS environmental difference and exempted. Real cause: stale
   baseline after auto-agent merge added a new `state` import.
   *Lesson: investigate before exempting. Most drift is the artifact
   telling the truth.*
3. **Class introspection for loop discovery.** First draft used
   `BaseClass.__subclasses__()` which would have fired side effects on
   every loop module's import. Reviewer caught it; switched to AST.
   *Lesson: documentation pipelines must be side-effect-free.*
4. **Ignoring test conventions when adopting from spec drafts.** Plan A's
   ports test had a class named `NotAPort` to test "not-a-port" filtering.
   `"NotAPort".endswith("Port")` is True — the test would have always
   included it. Renamed to `HelperProtocol`.
   *Lesson: read your test fixtures with the production filter in mind.*
5. **Skipping Hindsight residual cleanup.** Tested briefly, found it was
   entangled in `tests/helpers.py` parameter signatures threading through
   19 test files. Deferred. This is OK as long as the deferral is honest
   (we documented in the PR body of #8435).
6. **Underscore-prefixed classes leaking.** Loops extractor filtered
   `_*` (intentional); ports extractor didn't. Auto-agent's internal
   `_PRPort` Protocol type-hint helpers leaked into `ports.md`.
   *Lesson: filter conventions should be uniform across extractors.*
7. **Forgetting to re-emit baseline after merge.** Drift on subsequent
   PRs was always due to the previous merge updating source without
   updating baseline. Now baked into the autonomous loop tick.
8. **Operating from wrong worktree.** Twice I created nested worktrees
   inside other worktrees. Always anchor `git worktree add` from the
   main repo root with absolute paths.
9. **Pages source mode mismatch.** Pages was set to "Deploy from a
   branch" (Jekyll mode) while `actions/deploy-pages@v4` workflow was
   uploading. Both were "succeeding"; user saw Jekyll output. Required
   manual UI flip to "GitHub Actions" source. *Document this as a
   deployment prereq.*
10. **Underestimating loop-wiring surface area.** The wiki documented a
   "five-checkpoint" loop wiring pattern. Two more gates were added
   later (functional-area assignment in `docs/arch/functional_areas.yml`
   per PR #8434, and the curated/generated drift guard that requires
   `python -m arch.runner --emit` after wiring) but the wiki entry
   wasn't updated. PricingRefreshLoop's `make quality` failed on both
   gates after the implementer thought the loop was complete. Promoted
   to "Eight-Checkpoint Loop Wiring" in the wiki. *Lesson: when a new
   gate lands in CI, the canonical "how to add an X" wiki entry is part
   of the gate's surface area — update it in the same PR or the next
   X-builder will pay the tax.*

---

## 11. The HydraFlow autonomy unlock

The piece that goes beyond industry standard:

> An autonomous loop that walks source, regenerates documentation, and
> opens a PR with the diff. On a 4-hour cadence, with a kill switch.

This is what a **dark factory** adds to living documentation. Industry
calls living docs "docs that humans update alongside code." HydraFlow's
DiagramLoop adds: **docs that an agent updates *instead of* humans, with
a CI guard catching anything humans bypassed and a runtime loop catching
anything CI bypassed.**

The two-writer model is the sweet spot:
- CI catches drift at PR time (synchronous, blocks merge)
- DiagramLoop catches drift between PRs (asynchronous, force-pushed branch + auto-merge label)

Result: docs/arch/generated/ is **never wrong for more than 4 hours**, no
matter what humans or agents do to the code.

---

## 12. Adoption plan for HydraFlow

To let HydraFlow apply this methodology to *other* software it builds:

### Phase 1 — Extract the toolkit (Q3 follow-up)

The current `src/arch/` is HydraFlow-specific. Generalize:

- Move `src/arch/extractors/` to a stand-alone Python package
  (`hydraflow-arch-toolkit` or similar) that takes a config of:
  - Base class name (`BaseBackgroundLoop` → configurable)
  - Port suffix (`Port` → configurable, optional)
  - State-machine constant names
  - ADR directory layout
  - Functional-area YAML schema
- The methodology doc (this file) becomes the README of the package.
- HydraFlow's own `src/arch/` becomes the package's first downstream user.

### Phase 2 — Skill / agent invocation (Q4)

Add a HydraFlow skill `apply-self-documenting-architecture` that, when
invoked on a target repo:
1. Surveys the repo for shape (loop classes, Protocols, ADR dir, etc.)
2. Asks 3-5 yes/no questions to confirm shape (keep it minimal)
3. Generates the starter `docs/arch/` + `docs/adr/0001-...` + the
   appropriate runner config
4. Files a PR with the initial baseline + `arch-regen.yml` workflow
5. Optionally schedules a DiagramLoop equivalent in the target repo

### Phase 3 — New-project default (long-horizon)

When HydraFlow accepts an `epic: build new project X`, the project
scaffold includes the self-doc layer **from day 1**:
- `docs/arch/` with empty `functional_areas.yml`
- `docs/adr/0001-bootstrap.md`
- `arch-regen.yml` workflow
- `make arch-regen` target

This means every HydraFlow-built project is self-documenting before the
first feature ships. The cost is ~1h of scaffolding code, paid back on
every later inspection.

---

## 13. Reference

- Brown, Simon. *The C4 Model for Visualising Software Architecture.* https://c4model.com
- Ford, Neal et al. *Building Evolutionary Architectures.* O'Reilly, 2017.
- Gentle, Anne. *Docs Like Code.* 2017.
- Martraire, Cyrille. *Living Documentation: Continuous Knowledge Sharing by Design.* Addison-Wesley, 2019.
- Nygard, Michael. *Documenting Architecture Decisions.* https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions
- Procida, Daniele. *Diátaxis Documentation Framework.* https://diataxis.fr
- Karpathy, Andrej. Various repos using the per-folder wiki + manifest pattern.
