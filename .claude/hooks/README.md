# Claude Code Hooks

Project hooks invoked by the Claude Code CLI. Configured in `.claude/settings.json`.

## hf.* hooks

Shell scripts that gate specific tool calls:

- **PreToolUse** — `block-destructive-git`, `scan-secrets-before-commit`, `validate-tests-before-commit`, `enforce-plan-and-explore`, `check-test-counterpart`, `enforce-migrations`, `check-cross-service-impact`
- **PostToolUse** — `track-exploration`, `track-planning`, `track-code-changes`, `auto-lint-after-edit`, `warn-new-file-creation`
- **Stop** — `cleanup-code-change-marker`

## monocle_hook.py

Stop-event hook that parses the session transcript and emits OpenTelemetry spans
to [Okahu](https://okahu.ai) via the `monocle-apptrace` SDK. Runs after every
Claude Code turn for observability into agent behavior.

### Setup

1. Install the SDK in your Python environment:
   ```bash
   pip install monocle-apptrace
   ```

2. Set the required environment variables in `.env` (see `.env.sample` for the
   full list):
   ```bash
   MONOCLE_SERVICE_NAME=hydraflow-claude-ci   # per-repo identifier in Okahu
   MONOCLE_EXPORTER=okahu,file                # exporters to use
   OKAHU_API_KEY=okh_...                       # from app.okahu.ai
   ```

3. Optional debug logging:
   ```bash
   MONOCLE_CLAUDE_DEBUG=true
   # → ~/.claude/state/monocle_hook.log
   ```

4. Disable the hook entirely:
   ```bash
   MONOCLE_CLAUDE_ENABLED=false
   ```

The hook is **fail-open** — any error (missing dependency, network failure, bad
config) is logged but never blocks the Claude Code session.

### How it works

- After each turn, Claude Code invokes `monocle_hook.py` with the session id and
  transcript path on stdin.
- The hook tracks per-session offsets in `~/.claude/state/monocle_state.json`
  so it only processes new transcript lines on each invocation.
- Parsed turns are converted to OTel spans following Monocle's metamodel and
  exported via the configured exporters (Okahu and/or local JSONL files).
