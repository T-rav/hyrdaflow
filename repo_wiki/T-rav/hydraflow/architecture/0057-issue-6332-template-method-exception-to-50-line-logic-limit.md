---
id: 0057
topic: architecture
source_issue: 6332
source_phase: plan
created_at: 2026-04-10T05:33:08.098270+00:00
status: active
---

# Template method exception to 50-line logic limit

Methods containing static prompt templates or configuration strings can exceed 50 lines of text while maintaining good design if the logic content is minimal (<5 lines). `_assemble_plan_prompt` will be ~110 lines but acceptable because it's an f-string template with variable interpolation only. Splitting such templates across multiple methods reduces readability of the full prompt.
