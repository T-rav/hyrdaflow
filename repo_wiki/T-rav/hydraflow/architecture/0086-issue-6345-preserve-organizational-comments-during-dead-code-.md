---
id: 0086
topic: architecture
source_issue: 6345
source_phase: plan
created_at: 2026-04-10T06:35:05.468491+00:00
status: active
---

# Preserve organizational comments during dead code removal

Section heading comments (e.g., '# --- reset ---', '# --- threshold tracking ---') and blank-line separators maintain code structure and readability. Preserve these markers even when adjacent dead methods are removed. They signal logical grouping to future readers and should survive refactoring.
