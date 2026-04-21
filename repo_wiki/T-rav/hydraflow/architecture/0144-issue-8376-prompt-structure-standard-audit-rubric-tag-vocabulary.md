---
id: 0144
topic: architecture
source_issue: 8376
source_phase: synthesis
created_at: 2026-04-21T00:00:00+00:00
status: proposed
---

# Prompt Structure Standard — Audit Rubric and Tag Vocabulary (DRAFT — not yet enforced)

> **Status note:** This entry describes a *target* standard being staged across sub-projects 2–4. As of PR #8376, **25 of 26 factory prompts violate it**. Do not read this as "how HydraFlow prompts currently look" — read it as "how they will look after the normalization PRs land." See ADR-0043 for the authoritative decision record and the enforcement path.

## What the standard is

Every Claude-bound prompt in HydraFlow (triage / plan / implement / review / HITL runners and adjacent helpers — `arch_compliance`, `diff_sanity`, `test_adequacy`, `spec_match`, `conflict_prompt`, `expert_council`, `diagnostic_runner`, `adr_reviewer`, `pr_unsticker`) must render to a string that scores Low or Medium on the 8-criterion rubric codified in ADR-0043. The rubric is mechanically scored — regex/keyword rules over the rendered prompt text — and its result feeds the staging→main eval gate (sub-project 2, ADR-0042 integration).

## Tag vocabulary (10 standard tags)

Wrap machine-critical content regions in named XML tags. Markdown headings remain fine for human-readable sub-structure *inside* a tagged region.

- `<issue>` — GitHub issue title/body/labels/comments
- `<plan>` — implementation plan
- `<diff>` — patch, PR diff, conflict markers
- `<history>` — prior comments, review feedback, attempt logs
- `<constraints>` — invariants the model must respect
- `<manifest>` — file list / repo layout
- `<prior_review>` — last reviewer's feedback (distinct from `<history>`)
- `<output_format>` — the output contract
- `<example>` — few-shot examples
- `<thinking>` — CoT scaffold (output-side)

## Rubric summary (see ADR-0043 for the canonical table)

1. Leads with the request (imperative in first sentence)
2. Specific (output artifact + fields + success criteria)
3. XML tags (≥3 distinct content-region pairs)
4. Examples where applicable (`<example>` when output is structured)
5. Output contract explicit (`respond with`, `do not`, `return only`, …)
6. Placement of long context (≥10K-char prompts: largest block before the last imperative)
7. CoT scaffolded where decisions are made (`<thinking>`, `think step by step`)
8. Edge cases named (`if empty/missing/truncated`, `otherwise`, `fallback`)

Severity: **High** = 2+ Fails or any Fail on #1 or #6. **Medium** = 1 Fail or 3+ Partials. **Low** = 0 Fails, ≤2 Partials.

## Why this exists

Prompt quality was previously an implicit convention — markdown headings, organic growth per loop, no cross-factory consistency. The audit in PR #8376 quantified the cost: across 26 prompts, **every single one fails criterion #3 (XML tags)** (100%), most fail #8 (edge cases named) (85%), and 69% fail #1 (imperative buried after context).

Anthropic's published prompt-engineering guidance explicitly recommends XML-tagged content regions for structured inputs — the audit simply measured how far HydraFlow had drifted.

**Important caveat about #6 (long-context placement).** The audit's fixtures hold ≤1KB synthetic issue bodies and truncated diffs for reviewability. Under real production inputs, the implement prompt (`agent.AgentRunner._build_prompt_with_stats`) routinely renders at 14K+ chars and — with no tagged content regions — is expected to fail #6. The audit measures 0% fails on #6 because fixtures don't trip the 10K threshold. Sub-project 2's canary will exercise the rule against realistic inputs.

## Enforcement

- **Sub-project 2 (eval gate)** wires the audit's fixture + rendered-snapshot corpus into the staging→main promotion gate. A PR whose prompt changes violate parity is blocked.
- **Sub-project 3 (shared template)** provides `src/prompt_template.py` — a thin utility codifying tag order and section headers. Adoption is voluntary; the gate enforces *output*, not *construction*.
- **Sub-project 4 (normalization PRs)** migrates each loop one PR at a time. Priority order (ranked by fail count): `diagnostic_runner` (6 fails), `expert_council_vote` (6), `reviewer_ci_fix` (5), `triage_decomposition` (5), then the `agent.*` variants (4 each). Implement-prompt priority will rise once sub-project 2's canary makes #6 measurable against production inputs.

## Current-state truth (as of 2026-04-21)

- 26 prompts audited. 25 High severity. 1 Medium (`diff_sanity`). 0 Low.
- Top failing criteria system-wide: #3 (100%), #8 (85%), #1 (69%). #6 scored 0% fails but is under-measured by synthetic fixtures — see ADR-0043 for the production caveat.
- Audit tool: `scripts/audit_prompts.py`. Regenerate report: `make audit-prompts`.
- Report: `docs/prompt-audit-2026-04-20.md`.
- Fixture corpus: `tests/fixtures/prompts/` (26 JSON fixtures + 26 rendered snapshots).

## Links

- ADR-0043 (authoritative decision) — `docs/adr/0043-prompt-structure-standard.md`
- ADR-0042 (staging→main gate where the eval gate plugs in)
- Audit tool — `scripts/audit_prompts.py`
- Generated report — `docs/prompt-audit-2026-04-20.md`
- Spec — `docs/superpowers/specs/2026-04-20-prompt-audit-design.md` (local draft)
- Plan — `docs/superpowers/plans/2026-04-20-prompt-audit.md` (local draft)
