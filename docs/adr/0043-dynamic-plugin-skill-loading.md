# ADR-0043: Dynamic plugin skill loading — install at boot, discipline in the prompt, filtered per phase

- **Status:** Accepted
- **Date:** 2026-04-20
- **Supersedes:** none
- **Superseded by:** none
- **Related spec:** [`docs/superpowers/specs/2026-04-20-dynamic-skill-loading-design.md`](../superpowers/specs/2026-04-20-dynamic-skill-loading-design.md)

## Context

PR #8348 shipped a skill-discovery system: factory runners inject an `## Available Skills` section into their prompts listing every skill discovered from the Tier‑1 plugin allowlist. Preflight FAILs startup when a Tier‑1 plugin is missing, with the operator expected to run `/plugin install` interactively inside Claude Code.

In practice the system leaks value in three ways:

1. Subagents read the bland preamble and move on. The `superpowers:using-superpowers` skill loaded into main Claude sessions enforces a "1% confidence → MUST invoke" rule; subagents receive nothing of that strength.
2. Every phase sees every skill. A `reviewer` gets `frontend-design`; a `triage` gets `playwright` tool docs. The noise competes with the skills that actually fit.
3. A missing plugin stops the harness until a human runs the interactive slash command. Fresh clones, cleared caches, and CI boxes all pay this tax.

## Decision

Do three things together, in one PR:

1. **Install at boot.** `_check_plugins` in `src/preflight.py` shells out to `claude plugin install <name>@<marketplace> --scope user` for each missing Tier‑1 (and language-matched Tier‑2) plugin, then re-verifies. Still FAILs — but only if the install itself fails. Toggleable via `auto_install_plugins: bool = True`.
2. **Rewrite the preamble.** `format_plugin_skills_for_prompt` emits a condensed version of `using-superpowers`: "even at 1% confidence you MUST invoke", process-first priority, a short red-flag reminder. Descriptions still come verbatim from `SKILL.md` frontmatter.
3. **Per-phase whitelist.** A new `phase_skills: dict[str, list[str]]` config field maps each factory phase (`triage`, `discover`, `shape`, `planner`, `agent`, `reviewer`) to a curated set of qualified skill names. Each runner filters discovery through its whitelist before formatting.

Marketplace is expressed inline in `required_plugins` (`"name@marketplace"`), defaulting to `@claude-plugins-official` for bare names. No schema migration.

## Consequences

**Positive**

- First-boot experience is now "`python -m hydraflow` and walk away" — no manual slash-command dance.
- Subagents receive the same skill-picking discipline the main Claude session has, so the skills we ship are likelier to be used.
- Phase-level noise drops sharply: the heaviest phase (`agent`) sees 5 skills, the lightest (`triage`) sees 1. Advertisement becomes signal again.
- `make install-plugins` + `auto_install_plugins=False` give hermetic-CI operators a deterministic path.

**Negative**

- First boot on a fresh cache takes ≈ 30 s per plugin; with the 5 defaults that is ≈ 2–3 min of blocking install. Only paid once.
- Preflight now depends on `claude` being on `$PATH` and the user having run `claude login` at some point. Today's preflight already implicitly depends on `claude` — this makes the dependency slightly more demanding. Mitigated by a clear error path pointing to `claude login` when auth is the root cause.
- The `phase_skills` default mapping is opinionated. Users wanting every skill in every phase must explicitly override, which is a small friction cost in exchange for default-on signal-to-noise.

**Neutral**

- The `using-superpowers` meta-skill is still excluded from discovery; its discipline is now inlined into the preamble instead.
- Skill *discovery* is unchanged; we only add a filter in front of it.

## Alternatives considered

**Declarative install via `enabledPlugins` in `~/.claude/settings.json`.** Claude Code auto-reconciles this file on startup, so writing the plugin list there would give lazy install "for free." Rejected because (a) install would happen on the *next* subagent dispatch, not at preflight, so preflight couldn't verify the result; (b) we'd be co-editing a user-owned config file.

**Makefile-only install (`make install-plugins`), preflight stays validate-only.** Cleaner separation, but contradicts the user-stated goal ("install when booting") and leaves fresh machines in a broken state until someone remembers the setup step. We keep the Makefile target as the manual fallback, not the primary path.

**Full `using-superpowers` body inlined in the preamble.** Would maximize discipline transfer, but costs ≈ 1 kB per prompt across six runners. Condensing to 8 lines keeps the load-bearing phrases ("1% confidence", "process first", "do not rationalize") without the bulk.

**Per-phase allowlist as metadata in each `SKILL.md`.** Requires patching upstream plugins or shadowing their frontmatter. Our allowlist is a HydraFlow opinion, so it belongs in HydraFlow config, not in plugin metadata.

## Verification

**Host mode (2026-04-21):** probed by running `claude -p --output-format stream-json --verbose --permission-mode bypassPermissions --model claude-sonnet-4-6 --max-turns 3` with a prompt instructing the model to invoke `superpowers:systematic-debugging` via the `Skill` tool. Output stream included a `tool_use` event with `"name":"Skill","input":{"skill":"superpowers:systematic-debugging"}`, confirming the Skill tool is exposed in `-p` mode and routes to installed plugins discovered from `~/.claude/plugins/cache/`.

**Docker mode (not separately probed):** `src/docker_runner.py:430-435` mounts the host's `~/.claude/` into the container at `/home/hydraflow/.claude/` (rw) and sets `CLAUDE_CONFIG_DIR=/home/hydraflow/.claude`. Claude's plugin discovery reads the same filesystem layout via that env var, so the host probe's conclusions extend to Docker subagents. Additional `--plugin-dir /opt/plugins/*` flags are emitted dynamically by `agent_cli._plugin_dir_flags()` (see test `tests/test_agent_cli_plugin_dirs.py`) for plugins pre-cloned at image build time.

## References

- Spec: [`docs/superpowers/specs/2026-04-20-dynamic-skill-loading-design.md`](../superpowers/specs/2026-04-20-dynamic-skill-loading-design.md)
- Prior feature PR (now being extended): #8348
- Claude Code plugin CLI: <https://code.claude.com/docs/en/plugins-reference#plugin-install>
- [`ADR-0001: Five concurrent async loops`](0001-five-concurrent-async-loops.md) — the factory-phase names used by `phase_skills` originate here.
