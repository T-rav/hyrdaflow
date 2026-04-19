---
id: 0008
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849547+00:00
status: active
---

# Label-Based Async Loop Routing via GitHub Labels

The system routes work through distinct concurrent async polling loops via GitHub issue labels (hydraflow-plan, hydraflow-discover, hydraflow-shape, etc.). Each loop: fetches issues with its label, processes them, swaps the label to route to the next phase. This pattern avoids persistent state management by leveraging GitHub as the queue and label transitions as the state machine. Event types (triage_routed, discover_complete, etc.) publish to EventLog and trigger state transitions. Source fields in events (discover, shape, plan) establish cross-references for worker creation and transcript routing. New event types require multi-layer synchronization: reducer event handlers (worker creation), EVENT_TO_STAGE mapping, SOURCE_TO_STAGE routing, and transcript routing logic. See also: Orchestrator/Sequencer Design for coordination patterns, Layer Architecture for event handling placement.
