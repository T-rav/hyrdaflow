---
id: "01KQV37D10M06PGF32CF77W6K3"
name: "EventBus"
kind: "service"
bounded_context: "shared-kernel"
code_anchor: "src/events.py:EventBus"
aliases: ["event bus", "pub/sub bus", "hydraflow event bus"]
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-05-05T03:35:36.668765+00:00"
updated_at: "2026-05-05T03:35:36.668766+00:00"
---

## Definition

Async pub/sub bus that fans HydraFlowEvent objects out to subscriber asyncio.Queues, retains a bounded in-memory history for replay, and optionally persists every event through an EventLog. Auto-injects the active session_id and repo slug onto outbound events so downstream consumers always see a fully tagged event stream.

## Invariants

- History length is capped at max_history (default 5000); oldest entries are evicted when full.
- Slow subscribers do not block the publisher: a full subscriber queue drops its oldest entry before the new event is enqueued.
- History mutation is serialized through an asyncio.Lock.
