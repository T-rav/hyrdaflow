---
id: 0003
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849524+00:00
status: active
---

# Layer Architecture: Four-Layer Model with Structural Typing

HydraFlow uses a 4-layer architecture with strict downward-only import direction: L1 (Utilities: subprocess_util, file_util, state) → L2 (Application: phases, runners, background loops) → L3 (Agents: specialized LLM runners) → L4 (Infrastructure: HTTP routes, FastAPI, CLI). TYPE_CHECKING imports and protocol abstractions enable type safety without runtime layer violations. Use @runtime_checkable Protocol abstractions (AgentPort, PRPort, IssueStorePort, OrchestratorPort) to decouple layers via structural typing—concrete implementations automatically satisfy protocols via duck typing. Service registry (service_registry.py) is the single architecturally-exempt composition root: instantiate dependencies in correct order, annotate fields with port types for abstraction but instantiate with concrete classes, thread shared dependencies through all consumers. Background loops require 5-point wiring synchronization: config fields, service_registry imports, instantiation, orchestrator bg_loop_registry dict, and dashboard constants. Layer assignments tracked in arch_compliance.py MODULE_LAYERS and validated via static checkers (check_layer_imports.py) and LLM-based compliance skills. Pattern-based inference: *_loop.py→L2, *_runner.py→L3, *_scaffold.py→L4. Bidirectional cross-cutting modules (state, events, ports) can be imported by any layer but must only import from L1. See also: Architecture Compliance for validation, Orchestrator/Sequencer Design for L2 patterns.
