---
source: feedback_subagent_batch_size.md
name: Cap subagent-driven-development batches at 2–4 coherent tasks
description: Batches of 10+ mechanical tasks packed into a single subagent dispatch
  time out mid-execution; small batches (2–4 tasks) complete reliably
status: issue-open
issue: 42
promoted_in: null
wontfix_reason: null
created: '2026-04-21'
---

When dispatching Agent tool calls for subagent-driven plan execution, cap each batch at **2–4 coherent tasks** (typically ≤4 commits, ≤5 minutes of work). Larger batches time out.

**Why:** During the 2026-04-20 prompt audit (PR #8376), a 10-task batch (Tasks 2–11, rubric rules + severity + combined score) dispatched to a single subagent timed out at 166s partway through Task 4. All subsequent 2–3 task batches (A/C/D/E/F/G/H) completed cleanly in 100–350s each.

**How to apply:**

1. **Ideal batch shape**: 2–4 tasks that share setup context (same files, same pattern). Each task = one commit.
2. **When tempted to batch 5+ mechanical tasks "because they're identical"**: split. The tasks being identical doesn't change timeout risk.
3. **Timebox in the prompt**: include "hard stop at N minutes; if you're not done, report BLOCKED with progress so controller can dispatch a follow-up." Makes partial-completion a clean handoff rather than a stall.
4. **Spec the commit messages up front**: avoids subagent reinterpretation and makes follow-up dispatches easy.
5. **For inspection-heavy single tasks** (reading many source files to build a registry, verifying signatures): those count as "heavier than they look" — dispatch solo even if the task description is short.

This complements the batching heuristic in writing-plans: bite-sized tasks (2–5 min each) are the plan's unit; batches are the dispatch's unit; keep both units small.
