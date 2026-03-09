# ADR-0001: Five Concurrent Async Loops

**Status:** Accepted
**Date:** 2026-02-26

## Context

HydraFlow must process GitHub issues through five distinct stages: triage, plan,
implement, review, and human-in-the-loop (HITL) correction. Each stage has
different latency profiles:

- Triage: fast (seconds) — scoring + label assignment
- Plan: slow (minutes) — codebase exploration + plan generation
- Implement: very slow (many minutes) — full code changes + quality gate
- Review: slow (minutes) — diff analysis + optional fixes
- HITL: human-gated (indefinite) — waits for operator action

Multiple issues exist in the pipeline simultaneously, and stages are independent
of each other (issue #10 can be in triage while issue #5 is in review).

## Decision

Run five concurrent `asyncio` polling loops from `orchestrator.py`, one per stage.
Each loop independently:
1. Fetches its work queue (issues with the relevant label) from GitHub.
2. Processes items up to a configurable batch size and concurrency limit.
3. Sleeps for a configurable interval between polls.
4. Respects a shared `stop_event` for graceful shutdown.

## Consequences

**Positive:**
- Maximum pipeline throughput: all stages run in parallel without head-of-line blocking.
- Stage-level concurrency control (`max_planners`, `max_implementers`, etc.) is
  independently configurable.
- Simple mental model: one file per stage (`plan_phase.py`, `implement_phase.py`,
  etc.), one loop per stage in `orchestrator.py`.
- Graceful degradation: one stage failing does not block the others.

**Negative / Trade-offs:**
- GitHub API rate limits are shared across all loops; burst traffic can exhaust
  the limit if batch sizes are too high.
- No global scheduler means the orchestrator cannot prioritize high-severity issues
  across stages (stages are FIFO within their own queue).
- A crashed loop is not automatically restarted (the orchestrator must be restarted
  by restarting the HydraFlow server, e.g., `make run`).

## Alternatives considered

- **Single sequential loop**: Simpler but creates head-of-line blocking — one slow
  implementation would starve planning for all other issues.
- **Task queue (Celery/RQ)**: More powerful scheduling, but adds Redis/broker
  infrastructure and removes the simplicity of a pure-Python in-process design.
- **Thread-per-stage**: Would work but asyncio's cooperative multitasking is a
  better fit for I/O-bound agent subprocess management.
