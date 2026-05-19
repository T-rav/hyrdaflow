---
source: feedback_xml_tags_in_subagent_prompts.md
name: XML tags in subagent/Claude prompts
description: When building prompts for the Claude API or Agent tool dispatches, wrap content regions in named XML tags — same rubric I apply in prompt audits
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-04-21'
---

Wrap content regions in named XML tags when constructing prompts — for Agent tool dispatches, Claude API calls, or anything else that ships text to a model. The standard tag vocabulary codified for HydraFlow:

- `<issue>` — issue title/body/labels
- `<plan>` — implementation plan
- `<diff>` — patch or PR diff
- `<history>` — prior comments, review feedback, attempt logs
- `<constraints>` — invariants the model must respect
- `<manifest>` — file list / repo layout
- `<prior_review>` — last reviewer's feedback
- `<output_format>` — the output contract
- `<example>` — few-shot examples
- `<thinking>` — CoT scaffold (output-side)

**Why:** During the 2026-04-20 prompt audit (PR #8376), 25 of 26 HydraFlow factory prompts scored High severity, with criterion #3 (XML tags) failing across all 26. My own subagent dispatches during that audit also failed #3 — I used markdown headings throughout. The audit itself proved this is the single highest-leverage structural fix for prompts.

**How to apply:**
- For subagent Agent tool dispatches: wrap task, files, context, constraints, output_format sections in tags.
- For `anthropic.Anthropic().messages.create(messages=...)` calls: do the same inside the user message.
- Never rely on markdown `## Heading` alone to delineate machine-critical regions.
- Keep `<thinking>` tags for decision-heavy tasks (classify/verdict/rank/choose).
