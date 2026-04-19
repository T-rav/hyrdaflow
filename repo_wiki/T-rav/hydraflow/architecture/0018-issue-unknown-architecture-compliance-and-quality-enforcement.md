---
id: 0018
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849585+00:00
status: active
---

# Architecture Compliance and Quality Enforcement

LLM-based architecture checks (arch_compliance.py, hf.audit-architecture skill) risk blocking every PR if prompts are too aggressive. Mitigations: (1) use conservative language ('only flag clear violations'); (2) default disable-friendly config (max_attempts=1); (3) exempt composition root (service_registry.py) explicitly; (4) focus on judgment-based checks that static tools cannot detect. Deferred imports are intentional per CLAUDE.md and should never be flagged. Async read-then-write patterns (fetch state, modify, write back) are a pre-existing limitation from original _run_gh calls and acceptable as known-constraint. Tests checking presence must assert content, not just structure (e.g., verify module names in layer assignments, not just that layer labels exist). Complement with defense-in-depth enforcement via three layers: linter rules (ruff T20/T10 for debug code), AST-based validation scripts (per-function test coverage), git hooks (commit message format). Pre-commit hook runs only make lint-check (intentional gap—agent pipeline and pre-push hook cover push path). This progressive hardening pattern prevents enforcement from blocking developers while maintaining quality standards. See also: Layer Architecture for compliance targets.
