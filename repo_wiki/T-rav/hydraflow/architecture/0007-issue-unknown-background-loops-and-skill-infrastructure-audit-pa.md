---
id: 0007
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849543+00:00
status: active
---

# Background Loops and Skill Infrastructure: Audit Patterns and Wiring

Background loops (BaseBackgroundLoop subclasses) follow a standard pattern established by CodeGroomingLoop: (1) _run_audit() invokes a slash command; (2) parse severity-headed output into findings; (3) deduplicate via DedupStore per loop type (e.g., architecture_audit_dedup.json, test_audit_dedup.json); (4) file GitHub issues for Critical/High findings. Discovery via class definition pattern (BaseBackgroundLoop subclass with worker_name kwarg). Wiring requires 5 synchronized locations: config (interval + env override), service_registry (instantiation), orchestrator (bg_loop_registry dict), dashboard UI (_INTERVAL_BOUNDS and BACKGROUND_WORKERS), and constants.js. Omitting any location causes incomplete registration. Test discovery via test_loop_wiring_completeness.py. Skip sets track intentional deviations. Distinguish from per-PR skills: per-PR skills (architecture_compliance.py, test_quality.py) are lightweight single-prompt diff reviews focused on clear violations. Background loops invoke full multi-agent slash commands. Phase-filtered skill injection separates via registry (TOOL_PHASE_MAP data), injection (base runner coordination), execution unchanged. Tool presentation to LLM is filtered by phase but execution remains unchanged. Skills in multiple backends handled via marker-based checks (substring matching for '## Output') rather than exact structure enforcement. Two-file consolidation: Pydantic model definition for structure validation and dynamic JSONL writing for persistence must stay synchronized. Operator review gates dynamic skills due to prompt injection risk. See also: Layer Architecture for placement, Dynamic Discovery for command discovery.
