---
id: "01KR9A3F20M01PGF32CF88W9A1"
name: "SkillPromptEvalLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/skill_prompt_eval_loop.py:SkillPromptEvalLoop"
aliases: ["skill prompt eval loop", "skill prompt drift detector", "corpus health auditor"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-05-19T20:00:00.000000+00:00"
---

## Definition

Weekly background loop with two responsibilities. First, it runs the full adversarial skill-prompt corpus on a fixed schedule, catching regressions the RC-gate subset sampling misses (ADR-0045 §4.6). Second, it samples 10% of `provenance: learning-loop` corpus cases, flagging any that the `expected_catcher` skill passes — a weak-case signal the §4.1 learner uses for corpus quality improvement. Files `skill-prompt-drift` issues on PASS→FAIL transitions and `corpus-case-weak` issues for human triage.

## Invariants

- Both subsystems share a single loop tick; neither runs independently.
- Issues are deduplicated before filing; the same regression does not produce duplicate bead spam.
- Subclasses `BaseBackgroundLoop`; kill-switch is via `enabled_cb("skill_prompt_eval")` (ADR-0049).
