# ADR-0043: Prompt structure standard (XML tags, 8-criterion rubric, mechanical scoring)

- **Status:** Proposed
- **Date:** 2026-04-21
- **Supersedes:** none (codifies an implicit convention that was never documented)
- **Superseded by:** none

## Context

HydraFlow ships ~26 distinct prompts to Claude across the triage / plan /
implement / review / HITL loops and adjacent helpers (ADR review, diff sanity,
test adequacy, PR unsticker, conflict resolver, expert council, diagnostic
runner, spec match, arch compliance). Every one is hand-assembled with f-string
interpolation and markdown headings (`## Issue`, `## Plan`, `## Review
Feedback`), and every one has grown organically as each loop evolved.

The prompt audit landed in PR #8376 scored all 26 against an 8-criterion
rubric derived from Anthropic's own published prompt-engineering guidance. The
headline finding: **25 of 26 prompts score High severity**, with the worst
offenders being

- **Criterion #3 (XML tag structure)** — zero content regions use named tags
  across the entire factory. Fail rate: 100% (26/26).
- **Criterion #8 (edge cases named)** — prompts rarely tell the model what to
  do on empty / truncated / unclear input. Fail rate: 85% (22/26).
- **Criterion #1 (leads with the request)** — the imperative ("return a JSON
  object…", "produce an implementation patch…") lands mid-prompt, after
  criteria / classification / context. Fail rate: 69% (18/26).

**Worst offenders** by fail count: `diagnostic_runner` and `expert_council_vote`
each fail 6 of the 8 criteria, followed by `reviewer_ci_fix` and
`triage_decomposition` at 5 each.

**Known methodology limitation — #6 is under-reported.** Criterion #6
(long-context placement) scored 0% fails against the audit fixtures, but
that reflects fixture size, not production behavior. The fixtures hold
hand-written ≤1KB issue bodies and truncated diffs so the PR diff stays
reviewable. Under production inputs (real issue bodies, full diffs, multi-comment
discussion threads, prior-failure traces), the implement prompt
(`agent.AgentRunner._build_prompt_with_stats`) will routinely exceed the 10K
threshold and, lacking any tagged content regions, is expected to fail #6.
Sub-project 2's eval gate — which renders against realistic inputs captured
from a canary repo — will be the authoritative measurement of #6 in
production. The rubric itself is correct; the audit's fixtures are just too
small to exercise it.

No architectural decision has ever codified what a prompt in this codebase
should look like. The audit's findings are not anyone's fault — they're the
expected outcome of 18 months of organic growth without a standard.

## Decision

Adopt a three-part standard for every Claude-bound prompt in HydraFlow:

### 1. Standard XML tag vocabulary for content regions

| Tag | Purpose |
|---|---|
| `<issue>` | GitHub issue title / body / labels / comments |
| `<plan>` | Planner-produced implementation plan |
| `<diff>` | Patch, PR diff, conflict markers |
| `<history>` | Prior comments, review feedback, attempt logs |
| `<constraints>` | Invariants the model must respect |
| `<manifest>` | File list / repo layout |
| `<prior_review>` | Last reviewer's feedback (distinct from `<history>`) |
| `<output_format>` | The output contract (what to produce, what to avoid) |
| `<example>` | Few-shot examples |
| `<thinking>` | CoT scaffold (output-side, not input) |

Markdown headings remain acceptable for human-readable sub-structure *inside*
a tagged region, but tags own the machine-critical boundaries.

### 2. Eight-criterion rubric for mechanical scoring

| # | Criterion | Rule |
|---|---|---|
| 1 | Leads with the request | First non-whitespace sentence (pre-tag) contains an imperative from `{produce, return, generate, classify, review, decide, output, propose, write, summarize}`. |
| 2 | Specific | Rendered prompt contains 3/3 of: output-artifact noun; named fields or schema; success criteria phrasing. |
| 3 | XML tags | ≥3 distinct `<content>...</content>` pairs (excluding `<thinking>` / `<scratchpad>`). |
| 4 | Examples where applicable | If structured output cues present, `<example>` or `Example:` required. |
| 5 | Output contract | ≥1 of: `respond with`, `do not`, `no prose`, `return only`, `output format`, `the output must`. |
| 6 | Placement of long context | For rendered prompts ≥10K chars, largest tagged block must end before the last imperative. |
| 7 | CoT scaffolded | Decision verbs present → require `<thinking>` / `<scratchpad>` / `think step by step`. |
| 8 | Edge cases named | ≥1 of: `if empty/missing/truncated/unclear/no …`, `when the … is not/cannot/fails`, `otherwise,`, `in case of`, `fallback`, `do not assume`. |

**Severity:**
- **High** — 2+ Fails, or any Fail on #1 or #6.
- **Medium** — 1 Fail or 3+ Partials.
- **Low** — 0 Fails, ≤2 Partials.

### 3. Enforcement path — staged across sub-projects 2–4

The standard lands in four sub-projects tracked in
`docs/superpowers/specs/2026-04-20-prompt-audit-design.md`:

1. **Sub-project 1 (this PR, #8376)** — audit tool + committed report +
   fixture corpus. No prompt rewrites.
2. **Sub-project 2 — eval gate.** Wire the audit's fixture set +
   rendered-snapshot baseline into the staging→main promotion gate
   (ADR-0042). Every prompt change must pass rubric parity.
3. **Sub-project 3 — shared template.** A thin `src/prompt_template.py`
   utility codifies section order and the tag vocabulary. Optional for
   builders to adopt; reduces drift.
4. **Sub-project 4 — normalization PRs.** One PR per loop migrates its
   prompts to the standard. Each PR is reviewed against the eval gate
   established in sub-project 2. Priority order (ranked by fail count in
   the audit report): `diagnostic_runner` (6 fails), `expert_council_vote`
   (6), `reviewer_ci_fix` (5), `triage_decomposition` (5), then the
   `agent.*` variants (4 each). The implement-prompt variants should be
   re-prioritized once sub-project 2's canary produces production-scale
   renderings and #6 becomes measurable.

## Rationale — why mechanical scoring, not LLM-as-judge

Three alternatives were considered:

- **LLM-as-judge**: ask Claude to score each prompt. Most flexible, but
  non-deterministic (same prompt scores differently across runs), expensive
  at CI scale (hundreds of judging calls per gate-run), and hard to debug
  when a legitimate structural change trips the judge.
- **Manual review**: humans score each prompt. Catches semantic issues
  automation misses, but not reproducible and doesn't scale to an eval gate
  that runs on every staging→main promotion.
- **Mechanical (chosen)**: regex/keyword rules over the rendered prompt
  string. Reproducible (same input → same score, always), cheap (sub-second
  per prompt, runs in CI without LLM budget), and easy to debug (failing
  criterion points at a specific keyword).

Mechanical scoring has known false-positive risk: a prompt that happens to
contain the right keywords can pass while still being structurally weak.
This is accepted — the rubric's job is to catch the *worst* violations
reproducibly, not to judge semantic quality. Humans review PRs with the
rendered excerpts in the report; semantic quality lives there, not in the
gate.

## Consequences

**Positive**
- Prompt quality becomes a tracked, enforced property of the codebase, not
  an implicit convention.
- Sub-projects 2–4 have an unambiguous spec to implement against.
- Prompt-related PR reviews get a mechanical floor — reviewers can focus on
  semantic correctness instead of re-arguing "should we use tags?"
- Future prompts added to new loops automatically inherit the standard via
  the eval gate (sub-project 2).

**Negative**
- Normalization is a 5-loop migration with behavior-sensitive surface area.
  Each sub-project-4 PR carries real regression risk until it clears the
  eval gate. Mitigation: per-loop rollout with canary runs.
- The rubric's mechanical rules will produce occasional false positives —
  reviewers must be able to override with justification. The eval gate
  accepts a documented override; it does not accept silent drift.
- Every new Claude-bound builder added to the codebase must register with
  `PROMPT_REGISTRY` or CI fails. Low ongoing cost but a new contribution
  friction.

**Neutral**
- The existing `PromptBuilder` truncation infrastructure (`src/prompt_builder.py`)
  is unaffected — it operates on text content inside sections and is
  orthogonal to the section-structure standard.

## Alternatives considered

- **Full normalization in one PR.** Rejected: 26 prompts × behavior-sensitive
  rewrites = regression surface larger than one review can hold. Split into
  five per-loop PRs + one adjacent-helpers PR, each passing the gate.
- **Markdown-heading convention instead of XML tags.** Rejected: Anthropic's
  published guidance explicitly recommends XML tags for content regions,
  and the audit's fail rate on #3 is the biggest single structural lever.
- **Per-loop ad-hoc structure.** Rejected: that's the current state. The
  audit quantified the cost — 25/26 High severity.
- **Build the eval gate without the audit.** Rejected: without a baseline,
  the gate has nothing to enforce against. Sub-project 1's fixture +
  snapshot corpus is the gate's input.

## Links

- PR #8376 — sub-project 1, audit tool + report + fixture corpus.
- `docs/prompt-audit-2026-04-20.md` — the generated report.
- `docs/superpowers/specs/2026-04-20-prompt-audit-design.md` — full design spec.
- `docs/superpowers/plans/2026-04-20-prompt-audit.md` — implementation plan.
- ADR-0042 — two-tier branch / staging→main promotion (gate target).
