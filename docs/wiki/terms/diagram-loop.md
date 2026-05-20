---
id: "01KRBL0F20M01PGF32CF88W9B1"
name: "DiagramLoop"
kind: "loop"
bounded_context: "caretaker"
code_anchor: "src/diagram_loop.py:DiagramLoop"
aliases: ["diagram loop", "arch regen loop", "architecture regen loop", "L24"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-19T20:00:00.000000+00:00"
updated_at: "2026-05-19T20:00:00.000000+00:00"
---

## Definition

Caretaker loop (L24) that keeps `docs/arch/generated/` in sync with `src/` by running the arch-regen runner on each tick and opening a single idempotent bot PR (`arch-regen-auto` branch) when drift is detected (ADR-0029, ADR-0049). If no drift is found the tick exits silently. A secondary functional-area coverage check fires after regen; failures open a separate `chore(arch): unassigned functional area` issue via `PRPort.find_existing_issue` + `create_issue`, distinct from the regen PR.

## Invariants

- The regen PR always targets the fixed branch `arch-regen-auto`; a force-push updates any existing open PR rather than opening duplicates.
- The functional-area coverage issue is separate from the regen PR — one concern per artifact.
- Kill-switch is `HYDRAFLOW_DISABLE_DIAGRAM_LOOP=1` (ADR-0049 convention; no config field).
