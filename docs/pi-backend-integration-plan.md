# Pi Backend Integration Plan for HydraFlow

## Goal
Integrate `pi` as a first-class agent execution backend alongside `claude` and `codex` across HydraFlow stages (triage, plan, implement, review, AC, verification, summarization, memory compaction, subskill/debug).

## Scope
- Agent backend selection and command-building
- Config/CLI/env support for selecting `pi`
- Stream parsing and telemetry support for `pi` output
- Tests for command builder, parser behavior, config literals, and CLI choices

Out of scope for first pass:
- Replacing GitHub task/PR source
- UI redesign; only minimal display compatibility fixes

## Current Architecture Findings
- Backend command construction is centralized in `src/agent_cli.py`.
- Execution path is shared via `BaseRunner._execute()` and `stream_claude_process()` in `src/runner_utils.py`.
- Transcript normalization is centralized in `src/stream_parser.py` and already handles Claude/Codex event shapes.
- Tool selection is constrained by `Literal[...]` fields in `src/config.py` and CLI `choices=[...]` in `src/cli.py`.

## Implementation Phases

## Status Snapshot
- [x] Phase A completed
- [x] Phase B completed
- [x] Phase C completed

### Phase A: Enable Pi in Configuration and Command Construction
1. [x] Extend tool literals from `"claude"|"codex"` to `"claude"|"codex"|"pi"` across all agent-facing config fields.
2. [x] Update CLI argument choices to include `pi` for all backend flags.
3. [x] Extend `AgentTool` and `build_agent_command()` to emit non-interactive pi command(s).
4. [x] Keep defaults unchanged (still Claude) to minimize behavior risk.

Implemented:
- Config literals + env literal override compatibility
- CLI choices for all tool flags
- `build_agent_command(tool="pi", ...)` path
- Focused tests for command builder/config/CLI

Deliverable: HydraFlow can be configured to call `pi` commands without parser/runtime changes yet.

### Phase B: Runtime Streaming and Parsing
1. [x] Generalize `stream_claude_process()` behavior for backend-specific prompt transport.
2. [x] Add pi-specific stdin/argument handling (`pi -p` receives prompt as positional arg).
3. [x] Extend `StreamParser` with pi event schema parsing.
4. [x] Ensure token usage extraction covers pi usage keys.

Deliverable: End-to-end transcript streaming and telemetry work under pi backend.

Implemented:
- `pi` prompt transport in runner utilities
- `message_update` (`text_delta`) parsing
- `message_end`/`agent_end` result capture
- `tool_execution_start`/`tool_execution_end` display handling
- Usage key mapping: `input/output/cacheRead/cacheWrite/totalTokens`
- Focused tests for parser and runner behavior

### Phase C: Validation and Hardening
1. [x] Add/extend tests for config literals, CLI choices, command builder, parser, telemetry.
2. [x] Run targeted suites then `make quality-lite`.
3. [x] Add operational docs for canary rollout (`planner_tool=pi` first).

Deliverable: Stable integration with test coverage and rollout guidance.

Validated:
- `uv run pytest -q tests/test_cli.py -k "TestPrepModelSelection or TestPrepToolSelection or test_tool_fields_support_pi"`
- `uv run ruff check src/cli.py tests/test_cli.py tests/test_prompt_telemetry.py src/stream_parser.py src/runner_utils.py`
- `make quality-lite` (pass, 2026-02-25)

## Risks and Mitigations
- Unknown pi stream schema: isolate parser mapping in one module and use fixtures.
- Behavior divergence across tools: keep unified runner contract and stage prompts unchanged.
- Operational regressions: canary by stage before full rollout.

## Suggested Rollout
1. Canary: `planner_tool=pi` only.
2. Expand to `triage_tool` and `transcript_summary_tool`.
3. Expand to implement/review after stability checks.

## Canary Commands
Use one stage at a time and verify logs/quality checks between steps.

```bash
# Phase 1 canary
python -m src.cli --planner-tool pi --planner-model gpt-5.3-codex

# Phase 2 canary
python -m src.cli --planner-tool pi --triage-tool pi --transcript-summary-tool pi \
  --planner-model gpt-5.3-codex --triage-model gpt-5.3-codex --transcript-summary-model gpt-5.3-codex

# Phase 3 expanded rollout
python -m src.cli \
  --implementation-tool pi --review-tool pi --planner-tool pi --triage-tool pi \
  --memory-compaction-tool pi --ac-tool pi --verification-judge-tool pi \
  --model gpt-5.3-codex --review-model gpt-5.3-codex --planner-model gpt-5.3-codex \
  --triage-model gpt-5.3-codex --memory-compaction-model gpt-5.3-codex
```

## Initial Execution Slice (Now)
Proceed with Phase A immediately:
- Update config literals
- Update CLI choices
- Add pi command builder path in `agent_cli.py`
- Add or update focused tests for these changes
