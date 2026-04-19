---
id: 0021
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849596+00:00
status: active
---

# Prevent Scope Creep While Maintaining Correctness

Implementation plans are guidelines, not barriers. If necessary correctness fixes fall outside plan scope, document the deviation and rationale. Scope deferral with tracking issues prevents scope creep: defer separate problems to future issues rather than expanding current scope. However, never defer fixes when partial/incomplete fixes leave latent bugs. Example: fixing one missing label field requires fixing all missing label fields at once, not just the mentioned ones. Pre-mortem identification of failure modes helps design mitigations upfront and prevents rework.
