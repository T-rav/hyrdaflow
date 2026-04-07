# Claude Code Hooks

Project hooks invoked by the Claude Code CLI. Configured in `.claude/settings.json`.

## hf.* hooks

Shell scripts that gate specific tool calls:

- **PreToolUse** — `block-destructive-git`, `scan-secrets-before-commit`, `validate-tests-before-commit`, `enforce-plan-and-explore`, `check-test-counterpart`, `enforce-migrations`, `check-cross-service-impact`
- **PostToolUse** — `track-exploration`, `track-planning`, `track-code-changes`, `auto-lint-after-edit`, `warn-new-file-creation`
- **Stop** — `cleanup-code-change-marker`

## Observability

HydraFlow now collects trace data **in-process** inside `stream_claude_process()` (see `src/trace_collector.py`). There is no Stop-hook-based tracing — the collector writes `subprocess-N.json` files directly to `<data_root>/traces/<issue>/<phase>/run-N/` as each agent subprocess completes. The `trace_mining_loop` then aggregates runs into `TraceSummary` and syncs insights to Hindsight.

No environment variables or external dependencies are required for tracing.
