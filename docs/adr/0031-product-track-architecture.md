# ADR-0031: Product Track Architecture — Discover and Shape Phases

**Status:** Proposed
**Date:** 2026-04-04

## Context

HydraFlow's original pipeline (ADR-0001) defined five stages: triage, plan,
implement, review, and HITL. This works well for issues where the *what* is
clear and only the *how* needs solving — e.g., "add pagination to the users
endpoint" or "fix the race condition in worktree cleanup."

However, many issues arrive as vague product intent rather than engineering
tasks: "we need better onboarding," "explore notification options," or a
one-line feature request without context. Routing these directly to planning
produces poor plans — the planner lacks the product research and scope
narrowing that a human product decision-maker would normally provide.

The system needed to distinguish between two fundamentally different classes
of work:

1. **Engineering work** — the problem is defined, the solution needs building.
   Route: Triage → Plan → Implement → Review → Merge.

2. **Product work** — the problem is vague or broad, the solution needs
   discovering and shaping before engineering can begin.
   Route: Triage → Discover → Shape → Plan → Implement → Review → Merge.

### Alternatives Considered

1. **Always plan everything** — Force the planner to handle vague issues.
   Rejected: planners produce low-quality plans for vague input (observed
   <50% plan accuracy when clarity scores were low).

2. **Human-only triage** — Require a human to refine every vague issue before
   it enters the pipeline. Rejected: creates a bottleneck that defeats the
   purpose of automation; humans are slow and scarce.

3. **Single "research" phase** — One additional phase for product research
   without human conversation. Rejected: research alone doesn't narrow scope;
   someone still needs to choose a direction from the research findings.

## Decision

Add two phases — **Discover** and **Shape** — that form a *product track*
branching from triage and rejoining at plan. The pipeline becomes a fork:

```
                    ┌─ Discover ─→ Shape ─┐
Triage ─→ (route) ─┤                      ├─→ Plan → Implement → Review → Merge
                    └──── (direct) ───────┘
```

### Routing Decision

Triage evaluates each issue and produces a `clarity_score` (0–10) and a
`needs_discovery` boolean. The routing rule in `triage_phase.py:_triage_single`:

- If `needs_discovery` is true, **or** `clarity_score < clarity_threshold`
  (default 7): route to **Discover** (`hydraflow-discover` label).
- Otherwise: route directly to **Plan** (`hydraflow-plan` label).

The threshold is configurable via `config.py:clarity_threshold` (env:
`HYDRAFLOW_CLARITY_THRESHOLD`).

### Discover Phase

Read-only product research. The `DiscoverRunner` launches an agent with
web search and codebase read access (no write tools) to produce a structured
research brief:

- **Competitors analyzed** — existing solutions in the space.
- **User needs identified** — what users actually want.
- **Opportunities** — gaps and approaches worth exploring.

The brief is posted as a structured GitHub comment and the issue transitions
to `hydraflow-shape`. This phase is fully automated — no human interaction.

### Shape Phase

Multi-turn human-agent conversation to narrow scope and select a direction.
Two operating modes:

1. **Comment-based** (always active): The agent posts 2–5 product direction
   options (e.g., "Direction A: Quick & Focused" vs "Direction B:
   Comprehensive"). The human selects a direction by commenting. Selection
   is detected via regex matching on direction keywords.

2. **Runner-based** (when `ShapeRunner` configured): Full multi-turn
   conversation loop. Each turn is a fresh agent invocation with the
   accumulated conversation history, research brief, and recalled preference
   memories. Supports up to `max_shape_turns` (default 10) turns.

The Shape phase extracts **learning signals** from human responses:
- `scope_narrow` — human asked to reduce scope ("just," "only," "MVP")
- `scope_expand` — human asked to broaden ("also," "what about," "include")
- `positive` — human approved direction ("like," "love," "great")
- `negative` — human rejected direction ("no," "skip," "drop")

These signals are retained to memory for future preference learning.

Human input arrives via GitHub comments, the dashboard UI, or WhatsApp
(when `whatsapp_enabled` is configured). A configurable timeout
(`shape_timeout_minutes`, default 60) handles unresponsive conversations.

### Finalization and Handoff to Plan

When the human finalizes (selects a direction or says "ship it"), the Shape
phase posts a structured comment containing the selected direction and marks
the issue with `DECOMPOSITION REQUIRED`. This signals downstream phases:

- The **Plan phase** detects product-track issues via the decomposition marker
  and enforces that the planner produces 3–8 concrete sub-issues (not a
  single monolithic plan).
- The **Review phase** detects product-track PRs and runs a spec-match check
  to verify implementation aligns with the shaped direction.

### Track Model in UI

The dashboard explicitly models three tracks in `constants.js:PIPELINE_STAGES`:

| Track       | Stages                  | Purpose                    |
|-------------|-------------------------|----------------------------|
| `junction`  | Triage, Plan            | Entry and convergence      |
| `product`   | Discover, Shape         | Scope narrowing            |
| `engineering` | Implement, Review, Merged | Code delivery            |

`PRODUCT_TRACK_KEYS` is exported as a `Set` for UI components to branch
rendering (fork arrows, track grouping, skip detection).

### Labels

Two new lifecycle labels extend the state machine from ADR-0002:

| Label               | Stage    | Meaning                                |
|---------------------|----------|----------------------------------------|
| `hydraflow-discover`| Discover | Needs product research                 |
| `hydraflow-shape`   | Shape    | Awaiting direction selection           |

These follow the same `swap_pipeline_labels()` atomic transition pattern
as all other pipeline labels.

## Consequences

**Positive:**

- Vague issues get structured product research and human-guided scope
  narrowing before any code is written. This prevents wasted implementation
  effort on poorly-defined work.
- Human intent is captured as a first-class signal: direction selection,
  scope preferences, and approval are all recorded in the conversation
  history and retained to memory.
- Learned preferences accumulate over time — the system adapts to how a
  specific human/team makes product decisions (scope tendencies, risk
  appetite, preferred direction styles).
- The fork-and-rejoin architecture means engineering phases (Plan, Implement,
  Review) are unaware of whether an issue went through the product track.
  The decomposition marker is the only signal, keeping coupling minimal.
- Clear issues skip the product track entirely with zero overhead.

**Negative / Trade-offs:**

- Product-track issues take significantly longer (discover + shape + human
  wait time) before any code is written. This is intentional — vague work
  *should* be slower because it needs more thought.
- The clarity_score routing threshold is a tuning parameter. Too low and
  vague issues leak through to bad plans; too high and clear issues get
  unnecessary product research. Default 7 was chosen empirically.
- Shape phase depends on human responsiveness. Unresponsive conversations
  time out after `shape_timeout_minutes` and may escalate to HITL.
- The multi-turn conversation model means shape state must be persisted
  across polling cycles via `StateTracker.get/set_shape_conversation()`.
- Two new labels (`hydraflow-discover`, `hydraflow-shape`) are not listed in
  ADR-0002's original label set — this ADR extends that state machine.

## Related

- ADR-0001 (Five Concurrent Async Loops) — the original 5-stage pipeline
  that this ADR extends to 7 stages
- ADR-0002 (GitHub Labels as Pipeline State Machine) — the label-based state
  machine that this ADR extends with two new labels
- `src/triage_phase.py:_triage_single` — routing decision (clarity_score vs
  threshold)
- `src/discover_phase.py:DiscoverPhase` — product research execution
- `src/discover_runner.py:DiscoverRunner` — read-only research agent
- `src/shape_phase.py:ShapePhase` — multi-turn conversation loop
- `src/shape_runner.py:ShapeRunner` — conversation agent
- `src/config.py:clarity_threshold` — routing threshold configuration
- `src/config.py:max_shape_turns` — conversation turn limit
- `src/config.py:shape_timeout_minutes` — human response timeout
- `src/ui/src/constants.js:PIPELINE_STAGES` — track model (product, junction,
  engineering)
- `src/ui/src/constants.js:PRODUCT_TRACK_KEYS` — product track stage set
- `src/plan_phase.py:_is_product_track_issue` — decomposition enforcement
- `src/review_phase.py:_is_product_track_pr` — spec-match verification
- `src/models.py:TriageResult` — clarity_score and needs_discovery fields
- `src/models.py:DiscoverResult` — research brief output model
- `src/models.py:ShapeConversation` — conversation state model
