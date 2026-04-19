---
id: 0016
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849578+00:00
status: active
---

# Dead Code Removal Verification and Code Cleanup

Verify dead code removal via: (1) `make test` confirms no hidden dependencies, (2) `make quality-lite` for lint/type/security, (3) `make layer-check` validates layer boundaries, (4) comprehensive grep -r across src/ and tests/ for remaining references. When removing modules: update scripts/check_layer_imports.py MODULE_LAYERS dict, verify all imports are removed, delete entire files not stubs. Empty files create ambiguity—delete them entirely. Layer checker warns about nonexistent modules if entries aren't removed from MODULE_LAYERS. When deleting code from a subsection, preserve section heading comments (e.g., '# --- Structured Return Types ---') if other items in that section remain. The comment applies to all remaining members and improves navigation for future readers. ADR Superseding Pattern: when a planned feature documented in an ADR is removed as dead code (never implemented), update the ADR status to 'Superseded by removal' and cross-reference the removal issue. This preserves architectural decision history and clarifies for future reimplementation attempts.
