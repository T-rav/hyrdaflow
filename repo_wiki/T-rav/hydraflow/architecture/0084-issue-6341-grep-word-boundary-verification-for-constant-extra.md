---
id: 0084
topic: architecture
source_issue: 6341
source_phase: plan
created_at: 2026-04-10T06:22:03.281162+00:00
status: active
---

# Grep word-boundary verification for constant extraction refactors

After extracting magic numbers, verify completeness using grep word-boundary searches: grep -rn '\\b<literal>\\b' src/ tests/ should return exactly 1 match (the constant definition). Catches incomplete replacements and is language-agnostic, working across files and modules.
