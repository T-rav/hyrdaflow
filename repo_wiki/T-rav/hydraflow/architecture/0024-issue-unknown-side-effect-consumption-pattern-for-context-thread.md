---
id: 0024
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.852318+00:00
status: active
---

# Side Effect Consumption Pattern for Context Threading

Runners capture mutable side effects (e.g., `_last_recalled_items`, `_last_context_stats`) that must be explicitly consumed via getter methods after execution and cleared at method entry. This pattern prevents item leakage when runner instances are reused concurrently across issues. Pattern: (1) initialize side-effect variable in __init__ or at method entry; (2) populate during execution; (3) expose via `_consume_*()` method returning the value; (4) clear state after consumption in caller. Phases consume runner outputs, convert to domain models, and persist. This separates data production (runners) from I/O (phases) while threading context between stages via explicit consumption. See also: Functional Design for pure data threading, State Persistence for persistence patterns.
