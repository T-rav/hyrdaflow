# Auto-Agent — plan-stuck Playbook (ADR-0063 W1)

{{> _envelope.md}}

## Sub-label: plan-stuck

PlanReviewer rejected the plan. The pipeline already retried once with the
same shape. Don't re-run the planner; expand the touchpoint set and re-plan.

## Specific guidance

Order of operations:

1. Read the prior plan and the PlanReviewer's rejection (in escalation context
   and prior attempts).
2. Pull the touchpoints the original plan likely missed:
   - `grep`-walk the ADR set for any ADR cross-referenced by an ADR the plan
     already touches. Stop after one hop unless a touched ADR explicitly
     points at a third.
   - `git log --since=30.days -- <touched-file>` for each file the plan names,
     to surface recent PR conflicts on the same surface area.
   - Pull wiki entries (`docs/wiki/`) for affected modules — wiki entries
     encode the "load-bearing conventions" the planner needs to honor.
3. Re-shape the plan with `superpowers:writing-plans` discipline: explicit
   success criteria, file-by-file change list, test layer at each step.
4. Either commit a `plan.md` update on a fresh branch and open a PR
   (`resolved`), or return `needs_human` with the specific touchpoint conflict
   you found (e.g. "ADR-0029 caretaker-loop pattern conflicts with this
   plan's eager-evaluation step").

Do NOT:
- Re-run the same plan-shape the original planner produced.
- Skip the touchpoint walk — the failure mode is missing context, not missing
  attempts.
- Expand scope beyond what the touchpoints reveal. If the touchpoints suggest
  the plan needs to grow by >2x, escalate.
