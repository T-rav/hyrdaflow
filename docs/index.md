# HydraFlow Architecture

> **Intent in. Software out.** A multi-agent orchestration system that
> automates the full GitHub issue lifecycle.

## Where to start

- **[System Map](arch/generated/functional_areas.md)** — what this
  machine does, organized by functional area.
- **[Loop Registry](arch/generated/loops.md)** — every background loop,
  live truth from the AST.
- **[Decisions](adr/README.md)** — 49 ADRs covering every load-bearing
  architecture choice.
- **[Wiki](wiki/index.md)** — narrative entries on patterns, gotchas,
  testing, and dependencies.

## How this site stays honest

The pages under [Generated](arch/generated/loops.md) are **not
hand-written**. A `DiagramLoop` (L24) walks `src/`, `tests/`, and
`docs/adr/` every 4 hours, emits Markdown + Mermaid, and opens a PR
when the live truth has drifted. A CI guard (`arch-regen.yml`) re-runs
the same generation on every PR and fails the build if the working
tree's `docs/arch/generated/` is stale.

Every generated page footer shows its freshness state: 🟢 fresh,
🟡 source-moved (the loop will catch up within 4h), or 🔴 stale.

## See also

- [Changelog](arch/generated/changelog.md) — what's moved in the last
  90 days.
- [About this site](about.md) — how it's built, how to contribute.
- [Source on GitHub](https://github.com/T-rav-Hydra-Ops/hydraflow)
