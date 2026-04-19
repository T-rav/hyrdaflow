---
id: 0017
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849581+00:00
status: active
---

# ADR Documentation: Format, Citations, Validation, and Superseding

ADRs use markdown with structured sections: Date, Status, Title, Context, Decision, Rationale, Consequences. Validation checklist: structural checks first (missing sections, status format), then semantic checks (scope significance, contradiction audit). Source citations use module:function format without line numbers per CLAUDE.md. Set status to Accepted for documenting existing implicit patterns, not just new proposals. Reference authoritative runtime sources (e.g., src/config.py:all_pipeline_labels) instead of copying definitions to avoid drift. Skip TYPE_CHECKING imports in citations since they're compile-time-only. Ghost entries (README listing files that don't exist) indicate stale migrations—validate documentation against filesystem reality. ADR Superseding Pattern: when a planned feature documented in an ADR is removed as dead code (never implemented), update the ADR status to 'Superseded by removal' and cross-reference the removal issue. This preserves architectural decision history and clarifies for future reimplementation attempts without duplicating work.
