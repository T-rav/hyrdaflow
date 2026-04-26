# About this site

This site is the human-readable face of HydraFlow's architecture. It
serves three audiences:

1. **Engineers** — looking up patterns, ADRs, or the current shape of
   the system before making a change.
2. **Operators** — checking what the autonomous loops are doing.
3. **Agents** — reading the generated artifacts as input to their work.

## Three layers

| Layer | What it is | Decay rate | Maintained by |
|---|---|---|---|
| **Generated** | Auto-extracted from source — loop registry, port map, etc. | code speed (hours) | `DiagramLoop` (L24) + CI guard |
| **Curated** | Wiki entries, the Functional Area Map | feature speed (days) | `RepoWikiLoop` + humans |
| **Narrative** | ADRs, this About page, the README | decision speed (months) | humans |

Generated pages have a footer indicating their freshness state. Curated
and narrative pages are explicit human work — the contribution flow is
"open a PR against `docs/wiki/` or `docs/adr/`."

## Freshness states

Each Generated page footer reads something like:

> *Regenerated from commit `abc1234` on 2026-04-24 14:32 UTC. Source last
> changed at `def5678`. Status: 🟢 fresh.*

| State | Meaning |
|---|---|
| 🟢 **fresh** | Regenerated within 24h **and** source unchanged since regen. |
| 🟡 **source-moved** | Source changed after last regen but within 7 days. The DiagramLoop should catch up within 4h; if you see this for >24h, the loop is paused or slow. |
| 🔴 **stale** | More than 7 days since regen, **or** the page contradicts an Accepted ADR (the `test_label_state_matches_adr0002` / `test_loop_count_matches_adr0001` checks failed in CI), **or** `.meta.json` is missing the artifact entirely (bootstrap state, before the loop has run). |

## How to contribute

- **Found drift?** Open an issue. If a Generated page lies, the loop
  will likely catch it within 4 hours; if you can't wait, run
  `make arch-regen` locally and open a PR.
- **Want to amend an ADR?** Direct PR against `docs/adr/`.
- **Want to add a wiki entry?** Direct PR against `docs/wiki/`.
- **New loop or Port?** Add it to `docs/arch/functional_areas.yml`
  in the same PR — the coverage test will fail otherwise.

## Build

The site is built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/)
and deployed by `.github/workflows/pages-deploy.yml` to GitHub Pages on
every merge to `main`. To preview locally:

```
make arch-serve
```
