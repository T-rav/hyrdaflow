# ADR-0024: Config-Driven CLI Tool Names in Subprocess Commands

**Status:** Proposed
**Date:** 2026-03-14

## Context

HydraFlow invokes CLI tools (claude, codex, etc.) as subprocesses across several
background workers — memory compaction (`memory.py`), ADR review
(`adr_reviewer.py`), and PR unsticking (`pr_unsticker.py`). Each worker builds a
shell command using a tool name sourced from configuration fields such as
`background_tool`, `memory_compaction_tool`, and similar.

The configuration system already supports multiple CLI backends (`claude`,
`codex`, `pi`) and a global `background_tool` override that propagates to
per-worker tool fields at startup via `_apply_global_defaults()` in `config.py`.

However, several code paths hardcode the string `"claude"` as a fallback instead
of reading from the resolved config variable:

1. **`memory.py` `_summarise_with_model()`** — The `codex` branch correctly uses
   the literal `"codex"` (since it matches on that value), but the `else` branch
   hardcodes `cmd = ["claude", ...]` instead of using the config-resolved `tool`
   variable.

2. **`adr_reviewer.py` `_execute_orchestrator()`** and **`pr_unsticker.py`
   `_reflect_on_fix()`** — Both resolve `background_tool == "inherit"` to
   `"claude"` at the call site, duplicating default-resolution logic that
   `_apply_global_defaults()` in `config.py` already handles at startup. The
   `else` branch in these files correctly uses the `tool` variable for the
   command, but the `"inherit"` → `"claude"` mapping is a second, redundant
   default that can diverge from the config system.

This creates two risks:

- **Silent misconfiguration:** An operator sets `background_tool = "pi"` but
  `memory.py` still invokes `claude` in its else branch, ignoring the config.
- **Divergent defaults:** The call-site `"inherit" → "claude"` mapping in
  `adr_reviewer.py` and `pr_unsticker.py` can fall out of sync with the default
  in `config.py` if the project ever changes its default CLI backend.

## Decision

**All subprocess command construction MUST use the config-resolved tool variable,
never a hardcoded tool name string.**

Specifically:

1. **No hardcoded tool names in `else` branches.** When building subprocess
   commands, the `else` (non-codex) branch must use the config variable (e.g.,
   `tool`) rather than the literal `"claude"`. The `codex` branch is a match
   condition and correctly uses the literal — that is not affected.

2. **No call-site `"inherit"` resolution.** Workers should not resolve
   `"inherit"` → `"claude"` locally. The `_apply_global_defaults()` function in
   `config.py` resolves `"inherit"` at startup. If a worker receives `"inherit"`
   at runtime, it indicates a bug in config resolution, not a value that should
   be silently defaulted.

3. **Centralized default ownership.** The default CLI backend is defined exactly
   once: in the `Field(default=...)` declaration on each config field. All
   downstream code trusts the resolved config value.

### Affected files

| File | Function | Fix |
|------|----------|-----|
| `src/memory.py` | `_summarise_with_model()` | Replace `"claude"` with `tool` variable |
| `src/adr_reviewer.py` | `_execute_orchestrator()` | Remove `if tool == "inherit": tool = "claude"` fallback |
| `src/pr_unsticker.py` | `_reflect_on_fix()` | Remove `if tool == "inherit": tool = "claude"` fallback |

## Consequences

**Positive:**

- Operators can switch CLI backends globally via `HYDRAFLOW_BACKGROUND_TOOL` or
  per-worker via `HYDRAFLOW_MEMORY_COMPACTION_TOOL` and have confidence that all
  subprocess invocations respect the setting.
- Default tool names are defined in exactly one place (`config.py` field
  defaults), eliminating drift between config declarations and runtime behavior.
- Codex/pi/future-backend support works uniformly across all workers without
  per-file fixes.

**Negative / Trade-offs:**

- If `_apply_global_defaults()` has a bug and fails to resolve `"inherit"`,
  workers will attempt to invoke a binary literally named `"inherit"`, which will
  fail loudly. This is preferable to silently using the wrong tool, but requires
  confidence in the config resolution path.
- Reviewers must check new subprocess call sites for the same pattern — this is a
  recurring review concern, not a one-time fix.

## Alternatives considered

- **Keep call-site defaults as a safety net.** This provides defense-in-depth if
  config resolution fails, but introduces a second source of truth for the
  default tool name. The silent-wrong-tool risk outweighs the crash-on-bad-config
  risk, since the latter is caught immediately in testing.
- **Add a `resolved_tool()` helper method on config.** This would centralize
  `"inherit"` resolution into a method rather than relying on startup-time
  mutation. Viable but over-engineered given that `_apply_global_defaults()`
  already runs at config construction time and `"inherit"` is only valid for
  `background_tool`, not per-worker fields.

## Related

- Source memory: Issue #2635
- ADR task: Issue #2638
- `src/config.py` — `HydraFlowConfig`, `_apply_global_defaults()`
- `src/memory.py` — `_summarise_with_model()`
- `src/adr_reviewer.py` — `_execute_orchestrator()`
- `src/pr_unsticker.py` — `_reflect_on_fix()`
- ADR-0004 — CLI-based Agent Runtime (covers agent invocation architecture)
