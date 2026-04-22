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
make quality        # Lint + typecheck + security + test (parallel)
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
