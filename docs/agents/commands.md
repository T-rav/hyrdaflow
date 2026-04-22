# Development Commands

## Run and dev

```bash
make run            # Start backend + Vite frontend dev server
make dry-run        # Dry run (log actions without executing)
make clean          # Remove all worktrees and state
make status         # Show current HydraFlow state
make hot            # Send config update to running instance
```

## Tests

```bash
make test           # Run unit tests (fail-fast)
make test-fast      # Quick test run (-x --tb=short)
make test-cov       # Run tests with coverage report (70% threshold)
make integration    # Run integration tests
make soak           # Run soak/load tests
```

## Quality

```bash
make lint           # Auto-fix linting
make lint-check     # Check linting (no fix)
make typecheck      # Run Pyright type checks
make security       # Run Bandit security scan
make layer-check    # Static import-direction checker (layer boundaries)
make quality        # Lint + typecheck + security + test + layer-check (parallel)
make quality-lite   # Lint + typecheck + security (no tests)
```

## Setup and scaffolding

```bash
make setup          # Install hooks, assets, config, labels
make prep           # Sync agent assets + run full repo prep (labels, audit, CI/tests)
make scaffold       # Generate baseline tests and CI configuration only (no asset sync)
make ensure-labels  # Create HydraFlow lifecycle labels
make deps           # Sync dependencies via uv
```

## UI

```bash
make ui             # Build React dashboard
make ui-dev         # Start React dashboard dev server
```

## Quick validation loop

```bash
# After small changes
make lint && make test

# Before committing
make quality
```

## Hindsight recall — disable / re-enable

Phase 3 PR 9 ships with `hindsight_recall_enabled=True` by default. To
flip off during the 2-week observation window while validating that the
wiki-based system catches everything Hindsight was catching:

```bash
export HYDRAFLOW_HINDSIGHT_RECALL_ENABLED=false
```

To re-enable (rollback):

```bash
unset HYDRAFLOW_HINDSIGHT_RECALL_ENABLED
```

Retains (writes to Hindsight) remain active — only reads are gated. The
archive keeps accumulating so nothing is lost during the observation
window.

Metrics to watch on the dashboard (`/api/wiki/metrics`):

- `wiki_entries_ingested` should climb at approximately the rate of
  plan/implement/review cycles.
- `wiki_supersedes` should be non-zero within a few days (proves the
  contradiction detector is active).
- `tribal_promotions` will be zero until ≥2 active target repos share
  a principle (may stay zero indefinitely with only one managed repo).
- `reflections_bridged` should increment once per target-repo issue
  merge.
- `adr_drafts_judged` / `adr_drafts_opened` are non-zero only when
  agents have emitted `ADR_DRAFT_SUGGESTION` blocks.

Also watch `/api/wiki/health` — `store: populated` and (with ≥2 repos)
`tribal: populated` indicate the stores are being used.

Issue auto-merge rate should be stable within ±10% of the pre-change
baseline. Error rate should not change.

If divergence or regressions appear, unset the env var and file an
issue; do not proceed to the Hindsight deletion (Phase 3 PR 10) until
the gap is understood.

