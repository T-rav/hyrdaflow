# Deterministic Screenshot Capture

Captures reproducible screenshots of the HydraFlow dashboard for visual
validation during merge review and CI.

## Quick start

```bash
# From repo root:
make screenshot-update   # Generate/update baseline screenshots
make screenshot          # Compare against baselines (fails on diff)
```

Or from `src/ui/`:

```bash
npm run screenshot:update   # Generate/update baselines
npm run screenshot          # Compare against baselines
```

## How it works

1. **Seed state injection** — `window.__HYDRAFLOW_SEED_STATE__` is set before
   React mounts. The `HydraFlowProvider` detects this and uses the seed data as
   its initial state, skipping all WebSocket connections and API polling.

2. **API/WS stubbing** — Playwright intercepts every `/api/*` and `/ws` request
   with empty stub responses, preventing flaky network errors.

3. **Animation suppression** — A global stylesheet sets all `animation-duration`
   and `transition-duration` to `0s`, eliminating frame-timing variance.

4. **Fixed environment** — Playwright runs with:
   - Viewport: 1440 x 900
   - Scale factor: 1
   - Locale: `en-US`
   - Timezone: `UTC`
   - Color scheme: `dark`
   - Browser: Chromium (single project)

## Captured screens

| Name | State | Tab |
|------|-------|-----|
| `populated-issues` | Active pipeline | Work Stream |
| `populated-outcomes` | Active pipeline | Outcomes |
| `populated-hitl` | Active pipeline | HITL |
| `populated-worklog` | Active pipeline | Work Log |
| `populated-system` | Active pipeline | System |
| `populated-system-workers` | Active pipeline | System > Workers |
| `populated-system-pipeline` | Active pipeline | System > Pipeline |
| `populated-system-metrics` | Active pipeline | System > Metrics |
| `populated-system-insights` | Active pipeline | System > Insights |
| `populated-system-livestream` | Active pipeline | System > Livestream |
| `empty-issues` | Idle / empty | Work Stream |
| `empty-outcomes` | Idle / empty | Outcomes |
| `empty-hitl` | Idle / empty | HITL |
| `empty-worklog` | Idle / empty | Work Log |
| `empty-system` | Idle / empty | System |

## Required environment

- **Node.js 20+**
- **Chromium** — installed automatically by `npx playwright install --with-deps chromium`
- **No running backend** — all data comes from the seed fixture

## Modifying seed data

Edit `e2e/fixtures/seed-state.js`. The `seedState` object mirrors the shape of
`initialState` in `HydraFlowContext.jsx`. Keep all timestamps as fixed
ISO-8601 strings to preserve determinism.

After changing seed data, regenerate baselines:

```bash
make screenshot-update
```

## CI integration

The `visual-capture` job in `.github/workflows/ci.yml`:

1. Installs Node dependencies and Playwright Chromium.
2. Generates baseline screenshots with `npm run screenshot:update`.
3. Runs a second pass with `npm run screenshot` to compare against the
   baselines — this validates that captures are reproducible across two
   consecutive runs. The job fails if any screenshot differs.
4. Uploads captures as a `visual-captures` artifact (retained 30 days).
