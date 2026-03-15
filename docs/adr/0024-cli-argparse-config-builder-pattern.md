# ADR-0024: CLI Architecture — argparse with Config Builder Pattern

**Status:** Deferred
**Date:** 2026-03-08

> **Note:** The primary implementation files described in this ADR (`src/cli.py`
> and `src/hf_cli/__main__.py`) currently reside on a feature branch and have
> not yet been merged to `main`. This ADR is recorded as Deferred and will move
> to Accepted once the feature branch lands.

## Context

HydraFlow needs a CLI that supports 50+ configuration options with values sourced
from multiple layers: config files, environment variables, and command-line
arguments. The two main Python CLI framework choices are:

1. **Click** — Decorator-based, widely used, adds an external dependency.
2. **argparse** — Standard library, no external dependency, imperative style.

Beyond framework choice, the CLI must merge configuration from three sources with
clear precedence rules. Two patterns are common:

- **Flat parsing:** Each source is handled independently; merging happens ad-hoc
  at the call site.
- **Builder pattern:** A dedicated function (`build_config()`) owns the merge
  logic, producing a single validated config object.

The `hf` console script (`hf_cli/__main__.py`) acts as a two-layer dispatcher:
workspace management commands (run, stop, view, init) are handled directly, while
orchestrator commands and flags are delegated to `cli.main()`. The dashboard
exposes `/api/control/*` endpoints for start/stop/config but does not yet cover
all CLI operations (clean, prep, scaffold, labels, audit).

## Decision

Use **argparse** (Python standard library) as the CLI framework, paired with a
**config builder pattern** implemented in `build_config()` (`src/cli.py`).

### Framework: argparse over Click

- argparse is a stdlib module — no additional dependency to install, pin, or
  audit. The project has zero Click usage in source or `pyproject.toml`.
- HydraFlow's CLI is an operational tool, not a user-facing product with rich
  help formatting needs. argparse's built-in help is sufficient.
- The CLI surface is flag-heavy (50+ flags) rather than subcommand-heavy. Click's
  decorator model adds boilerplate for flag-dominated interfaces without
  meaningful readability gains.

### Config merge: builder pattern

`build_config(args: argparse.Namespace) -> HydraFlowConfig` merges config with
explicit precedence (lowest to highest):

1. **Defaults** — Pydantic model field defaults in `HydraFlowConfig`.
2. **Config file** — YAML/JSON loaded via `load_config_file()`, filtered against
   `HydraFlowConfig.model_fields.keys()` to reject unknown keys.
3. **Environment variables** — Resolved by Pydantic's `model_validate()`.
4. **CLI arguments** — Highest priority; only explicitly-provided args override.
5. **Repo-scoped overlay** — Applied post-validation for fields not set by CLI.

The builder tracks which CLI args were explicitly provided via the
`cli_explicit_fields` frozenset on `HydraFlowConfig` (and the corresponding
`cli_explicit` parameter in `runtime_config.py`'s repo-overlay function) so that
repo-scoped overlays only fill in gaps rather than clobbering intentional CLI
overrides.

### Two-layer dispatch

`hf_cli/__main__.py` handles supervisor/workspace commands directly and delegates
orchestrator flags to `cli.main()` via a `_FLAG_COMMANDS` mapping. This keeps the
two concern domains (workspace management vs. orchestrator operation) separated
without requiring a shared CLI framework.

## Consequences

**Positive:**

- Zero external CLI dependency — reduces supply chain surface and simplifies
  Docker images.
- Single, testable merge function (`build_config()`) owns all config precedence
  logic. Adding a new config source (e.g., remote config) requires changes in one
  place.
- Pydantic validation in `HydraFlowConfig` catches invalid combinations at
  startup, before any orchestrator loop runs.
- The `cli_explicit_fields` tracking enables repo-scoped overlays to coexist with
  CLI overrides without ambiguity.

**Negative / Trade-offs:**

- argparse lacks Click's composable command groups. If the CLI grows many
  subcommands (beyond current flag-based dispatch), this decision should be
  revisited.
- The two-layer dispatch (`hf_cli` + `cli.py`) means CLI help is split across
  two parsers. Users running `hf --help` see workspace commands; orchestrator
  flags require `hf start --help`.
- Dashboard `/api/control/*` endpoints do not yet cover all CLI operations
  (clean, prep, scaffold, labels, audit). Parity will require either extending
  the API or invoking `cli.main()` programmatically from the dashboard.

## Alternatives considered

- **Click:** Would provide richer help formatting and subcommand composition, but
  adds an external dependency for marginal benefit given the current flag-heavy
  interface.
- **Typer:** Built on Click with type-hint-driven signatures. Attractive for new
  projects, but migrating 50+ argparse flags provides no functional improvement
  and adds two new dependencies (Typer + Click).
- **Flat config merge:** Spreading merge logic across call sites would make
  precedence rules implicit and harder to test. The builder pattern keeps them
  explicit and centralized.

## Related

- Source memory: Issue #2268
- `src/cli.py` — `build_config()`, `parse_args()`, `main()` *(feature branch —
  not yet on `main`)*
- `src/hf_cli/__main__.py` — Two-layer CLI dispatcher *(feature branch — not yet
  on `main`)*
- `src/config.py` — `HydraFlowConfig` Pydantic model, `cli_explicit_fields` field
- `src/runtime_config.py` — `resolve_runtime_config()`, `cli_explicit` parameter
- ADR-0004 — CLI-based Agent Runtime (related but distinct: ADR-0004 covers
  agent invocation via CLI subprocesses, this ADR covers HydraFlow's own CLI)
