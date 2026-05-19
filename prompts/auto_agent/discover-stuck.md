# Auto-Agent — discover-stuck Playbook (ADR-0063 W1)

{{> _envelope.md}}

## Sub-label: discover-stuck

The discover-runner's coherence evaluator rejected the research brief. The
runner already retried with the original query set; preflight is the second
chance to expand the queries before a human picks it up.

## Specific guidance

Order of operations:

1. Read the rejected brief and the evaluator's score / reason (in escalation
   context). The reason will surface as one of: "underspecified scope",
   "missing cross-reference", "contradicts an Accepted ADR", or
   "no measurable success criteria".
2. Apply the "what would 30% more confidence require?" frame. Propose at
   least three additional research queries that would close the gap — for
   example:
   - If the reason is "underspecified scope", queries that bound the scope
     (which modules, which lifecycle phase, which trust tier).
   - If the reason is "missing cross-reference", queries that pull adjacent
     ADRs or wiki entries.
   - If the reason is "contradicts an Accepted ADR", queries that either
     locate the supersession (the brief should reference the new ADR) or
     produce the supersession ADR draft (`hf.adr` slash command).
3. Re-run the brief with the expanded queries appended. Commit the updated
   brief on a fresh branch, push, return `resolved` with the new brief
   pointer.
4. If the gap is structural (missing source data, no ADR exists to reference,
   evaluator scoring rubric itself is the blocker), return `needs_human` with
   the specific blocker. Do not push a brief you know won't pass.

Do NOT:
- Re-run the original query set unchanged. The discover-runner already did.
- Lower the coherence threshold to force a pass. Threshold drift is a
  factory-phase-drift failure mode on its own.
- Skip the "what would 30% more confidence require?" check. The whole point
  of W1 routing here is that this prompt produces *different* queries than
  the runner's first attempt.
