# Shared Prompt Prefix for Fork-Join Cache Reuse — Design Spec

**Issue:** [#5938](https://github.com/T-rav/hydraflow/issues/5938)
**Date:** 2026-04-03
**Status:** Draft

## Problem

When HydraFlow dispatches 3-5 concurrent agents (implementation or planning), each constructs its prompt independently — recalling memory per-issue, loading manifest and CLAUDE.md separately. The project context is roughly the same across agents but not byte-identical, so the Claude API's KV cache can't reuse the prefix across parallel requests. This means the shared context (often 10K+ tokens) is recomputed for every agent.

## Goal

Structure subagent prompts so parallel agents share an identical context prefix, maximizing KV cache reuse. Only the task-specific suffix differs per agent. Use a hybrid memory strategy: generic recall in the shared prefix, small issue-specific top-up in each suffix.

## Scope

**In scope:**
- Enhance existing `SharedPromptPrefix` (add manifest, all 5 memory banks, dedup, `ContextSectionCache`)
- Add `shared_prefix` parameter to `BaseRunner._inject_manifest_and_memory()`
- Wire into `implement_phase.py` and `plan_phase.py` for batch dispatch
- Telemetry: `shared_prefix_chars`, `unique_suffix_chars`, `prefix_cache_reuse_ratio`

**Out of scope:**
- Review phase (typically max_reviewers=1, no batch benefit)
- HITL/triage phases (same reason)
- Claude API `cache_control` breakpoints (requires API migration, not CLI)
- Cross-batch prefix caching (each batch builds fresh)

## Architecture

### SharedPromptPrefix Enhancements

Retrofit the existing `src/shared_prompt_prefix.py` class:

1. **Add manifest loading** — load `.hydraflow/manifest/manifest.md` via `ContextSectionCache` (already exists in `src/context_cache.py`). Currently only CLAUDE.md is loaded.

2. **Recall all 5 memory banks** — currently recalls 3 (learnings, troubleshooting, retrospectives). Add `Bank.REVIEW_INSIGHTS` and `Bank.HARNESS_INSIGHTS` to match `base_runner._inject_manifest_and_memory()`.

3. **Deduplicate across banks** — use existing `PromptDeduplicator` from `src/prompt_dedup.py` to remove duplicates before assembly, matching the base_runner pattern.

4. **Use `ContextSectionCache`** — cache CLAUDE.md and manifest file reads to avoid repeated I/O.

5. **Generic query context** — use a broad query like `"project conventions, common patterns, known issues"` for the shared recall. This pulls broadly relevant memories without being issue-specific.

The `build()` method signature gains a `context_cache` parameter:

```python
async def build(
    self,
    *,
    hindsight: HindsightClient | None = None,
    context_cache: ContextSectionCache | None = None,
) -> str:
```

The `query_context` parameter is removed — the shared prefix always uses the generic query. The `with_task()` method stays unchanged.

### BaseRunner Integration

Modify `_inject_manifest_and_memory()` to accept a `shared_prefix`:

```python
async def _inject_manifest_and_memory(
    self, *, query_context: str = "", shared_prefix: str | None = None
) -> tuple[str, str]:
```

**When `shared_prefix` is provided:**
- Skip manifest loading (already in prefix)
- Skip the full 5-bank memory recall (already in prefix)
- Do a small issue-specific memory top-up: recall only `Bank.LEARNINGS` with the issue-specific `query_context`, capped at `max_memory_prompt_chars // 4` (~1000 chars)
- Return `(shared_prefix, topup_section)`

**When `shared_prefix` is None:**
- Existing behavior, unchanged. Single agents and non-batched paths work exactly as today.

### Runner Threading

`AgentRunner` and `PlannerRunner` gain an optional `shared_prefix` parameter on their `run()` methods, threaded through to `_build_prompt_with_stats()` and then to `_inject_manifest_and_memory()`.

The prompt assembly becomes:
```
shared_prefix + topup_memory + task_specific_parts
```

Instead of:
```
manifest + full_memory + task_specific_parts
```

### Phase-Level Dispatch

**`implement_phase.py`** — before `run_refilling_pool()`:
- If `max_workers > 1`: build shared prefix once, pass to each worker
- If `max_workers == 1`: skip prefix building, existing behavior

```python
shared_prefix: str | None = None
if self._config.max_workers > 1:
    builder = SharedPromptPrefix(self._config)
    shared_prefix = await builder.build(
        hindsight=self._hindsight,
        context_cache=self._context_cache,
    )
```

The phase already receives `hindsight` and `config` via its constructor (from `service_registry`). If `context_cache` isn't available at the phase level, add it as a constructor parameter — it's a lightweight object.

The worker function receives `shared_prefix` and passes it to `AgentRunner.run()`.

**`plan_phase.py`** — same pattern when `max_planners > 1`.

**Prefix lifecycle:** One `SharedPromptPrefix` per batch dispatch. Built once, used N times, garbage collected when batch completes. No cross-batch caching — next batch builds fresh since memory may have changed.

### Telemetry

Three new fields in the stats dict returned by `_build_prompt_with_stats()`:

| Field | Type | Description |
|-------|------|-------------|
| `shared_prefix_chars` | int | Length of shared prefix (0 if single-agent mode) |
| `unique_suffix_chars` | int | Length of task-specific portion |
| `prefix_cache_reuse_ratio` | float | `shared / (shared + unique)`, 0.0 to 1.0 |

Recorded in `prompt_telemetry.py` as additional keys in the existing stats dict. No schema changes to `inferences.jsonl`.

Expected values for a 3-5 agent batch: `prefix_cache_reuse_ratio` around 0.7-0.9.

## Data Flow

```
Phase (implement/plan)
  -> max_workers > 1? Build SharedPromptPrefix once
  -> run_refilling_pool(worker_fn receives shared_prefix)
    -> Runner.run(shared_prefix=...)
      -> _build_prompt_with_stats(shared_prefix=...)
        -> _inject_manifest_and_memory(shared_prefix=...)
          -> Skip manifest + full recall
          -> Do small LEARNINGS top-up for this issue
          -> Return (shared_prefix, topup_section)
        -> Assemble: shared_prefix + topup + task parts
      -> _execute(prompt) -> subprocess
      -> _prompt_telemetry.record(stats with prefix metrics)
```

## Testing Strategy

- **Unit tests for SharedPromptPrefix:** Verify build() caches on second call, verify all 5 banks recalled, verify dedup, verify `with_task()` assembly
- **Unit tests for _inject_manifest_and_memory shared_prefix mode:** Verify manifest/full recall skipped, verify LEARNINGS top-up happens, verify return shape
- **Integration test:** Mock parallel dispatch with 2 agents, verify both get identical prefix and different suffixes
- **Telemetry test:** Verify `shared_prefix_chars`, `unique_suffix_chars`, `prefix_cache_reuse_ratio` are recorded

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/shared_prompt_prefix.py` | Modify | Add manifest, 5 banks, dedup, ContextSectionCache, generic query |
| `src/base_runner.py` | Modify | Add `shared_prefix` param to `_inject_manifest_and_memory()` |
| `src/agent.py` | Modify | Thread `shared_prefix` through `run()` and `_build_prompt_with_stats()` |
| `src/planner.py` | Modify | Thread `shared_prefix` through `run()` and `_build_prompt_with_stats()` |
| `src/implement_phase.py` | Modify | Build prefix before `run_refilling_pool()` when `max_workers > 1` |
| `src/plan_phase.py` | Modify | Build prefix before `run_refilling_pool()` when `max_planners > 1` |
| `src/prompt_telemetry.py` | Modify | Extract and record prefix cache metrics |
| `tests/test_shared_prompt_prefix.py` | Create | Unit tests for enhanced builder |
| `tests/test_base_runner_shared_prefix.py` | Create | Tests for shared_prefix mode in _inject_manifest_and_memory |
| `tests/test_implement_phase_prefix.py` | Create | Integration test for parallel dispatch with shared prefix |
