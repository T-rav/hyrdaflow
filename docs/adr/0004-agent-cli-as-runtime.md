# ADR-0004: CLI-based Agent Runtime (Claude / Codex / Pi.dev)

**Status:** Accepted
**Date:** 2026-02-26

## Context

HydraFlow agents (planner, implementer, reviewer, HITL) need to:
- Explore and read the codebase (read-only for planner).
- Write, edit, and commit code (implementer, reviewer, HITL).
- Have access to the full suite of shell tools available in the worktree.
- Produce structured text output that HydraFlow parses for markers
  (`PLAN_START`, `VERDICT:`, etc.).

Options:
1. **Direct API calls** (Anthropic / OpenAI API): full control, but requires
   implementing file reading, shell execution, and tool use from scratch.
2. **SDK with tool use**: similar to direct API but with structured tool dispatch.
3. **CLI-based agents** (Claude Code `claude -p`, OpenAI Codex `codex`, Pi.dev
   `pi`): the agent handles filesystem access, shell execution, and tool dispatch
   natively. HydraFlow only needs to build the prompt and parse the output.

## Decision

Invoke agents as CLI subprocesses using `claude -p`, `codex`, or `pi` depending
on the configured `planner_tool` / `implement_tool` / `review_tool`. HydraFlow
constructs the prompt, passes it to the subprocess, streams stdout, and parses
structured markers from the transcript.

`src/agent_cli.py:build_agent_command()` constructs the correct invocation for
the configured tool. The same `BaseRunner._execute()` method handles streaming
for all tools.

### Tool routing (default)

| Stage | Default tool | Model config key |
|-------|-------------|-----------------|
| Plan | `claude` | `planner_tool` / `planner_model` |
| Implement | `claude` | `implement_tool` / `implement_model` |
| Review | `claude` | `review_tool` / `review_model` |
| HITL | `claude` | `hitl_tool` / `hitl_model` |
| Sub-skills | `claude` | `subskill_tool` / `subskill_model` |

Any tool can be switched to `codex` or `pi` per-stage via environment variables.

## Consequences

**Positive:**
- Agents have native filesystem, shell, and tool access without HydraFlow
  implementing any of that infrastructure.
- Switching between Claude, Codex, and Pi.dev requires only a config change;
  no code changes needed.
- Prompt contracts (PLAN_START, VERDICT:, SUMMARY:) are tool-agnostic: any
  agent that follows the output format works.
- Local execution: agents run in the worktree, with the repo on disk, enabling
  `make quality` and test execution as part of the agent loop.

**Negative / Trade-offs:**
- HydraFlow is dependent on the CLI being installed and authenticated on the host.
  (`claude auth`, `gh auth login`, etc.)
- CLI tool behaviour may change between versions; pinning tool versions is
  recommended.
- Streaming transcript parsing is best-effort: if the agent produces output in an
  unexpected format, markers may not be detected.
- The `PLAN_END` / `ALREADY_SATISFIED_END` early-termination signals rely on
  `on_output` callbacks in the streaming loop; this is an optimisation, not a
  correctness requirement.

## Related

- `src/agent_cli.py` — command builder
- `src/base_runner.py:BaseRunner._execute` — streaming subprocess executor
- `AGENTS.md` — canonical prompt contracts for each agent role
- ADR-0002 for the output marker protocol that makes tool-agnosticism possible
