# Auto-Agent — skill-prompt-stuck Playbook

{{> _envelope.md}}

## Sub-label: skill-prompt-stuck

A skill prompt evaluation is failing. Read the eval, the prompt, recent changes
— usually a regression in prompt structure or output format.

## Specific guidance

The skill-prompt-eval loop ran the eval suite for one or more skills and
detected a regression.

Order of operations:

1. Read the eval failure (in escalation context if present, otherwise re-run
   the eval against the current prompt).
2. `git log` the prompt file to see what changed recently.
3. The fix is usually one of: a missing structural element (e.g., the prompt
   stopped saying "in second person"), a format drift (output now starts with
   ```` ```json ```` instead of bare JSON), or a parameter rename.
4. Apply the smallest possible patch to the prompt file. Run the eval again to
   confirm green.

Don't restructure the whole prompt. Find the regression delta and fix it.
