import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { FactoryCostTab } from '../FactoryCostTab'

// Sanity-check render tests for the §4.11p2 Task 14 composition tab.
// FactoryCostTab fans out Promise.allSettled([rolling-24h, top-issues, loops/cost, cost/by-model]).
// We stub fetch per URL so each sub-component receives a valid shape.

const rolling24h = {
  total: { cost_usd: 1.5, tokens_in: 10_000, tokens_out: 3_000 },
  by_loop: [{ loop: 'implementer', llm_calls: 3 }],
}
const topIssues = [
  { issue: 42, cost_usd: 0.75, wall_clock_seconds: 90 },
  { issue: 99, cost_usd: 0.5, wall_clock_seconds: 45 },
]
const loopsCost = [
  {
    loop: 'implementer',
    cost_usd: 1.1,
    llm_calls: 3,
    ticks: 4,
    tick_cost_avg_usd: 0.275,
    tick_cost_avg_usd_prev_period: 0.2,
    wall_clock_seconds: 60,
    sparkline_points: [0.1, 0.2, 0.3],
  },
]

function buildFetchStub() {
  return vi.fn((url) => {
    if (url.includes('/cost/rolling-24h')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(rolling24h) })
    }
    if (url.includes('/cost/top-issues')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(topIssues) })
    }
    if (url.includes('/loops/cost')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(loopsCost) })
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve([]) })
  })
}

describe('FactoryCostTab', () => {
  let originalFetch
  beforeEach(() => {
    originalFetch = global.fetch
  })
  afterEach(() => {
    global.fetch = originalFetch
  })

  it('fetches all three endpoints and renders the section headings', async () => {
    global.fetch = buildFetchStub()
    render(<FactoryCostTab range="7d" />)

    // Section headings (static). We scope to h3 since "waterfall" also
    // appears in the WaterfallView empty-state prose, which would make a
    // plain getByText(/Waterfall/i) match two elements.
    expect(
      screen.getByRole('heading', { level: 3, name: /Per-Loop Cost/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { level: 3, name: /Top Issues/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { level: 3, name: /Waterfall/i }),
    ).toBeInTheDocument()

    // After async settle: summary + top-issue + per-loop rows present.
    await waitFor(() => {
      // Summary: $1.50 from rolling24h.
      expect(screen.getByText(/\$1\.50/)).toBeInTheDocument()
    })
    // Top issue #42 link.
    expect(screen.getByText('#42')).toBeInTheDocument()
    // Per-loop row for implementer.
    expect(screen.getByText('implementer')).toBeInTheDocument()

    // All four endpoints were called at least once.
    const urls = global.fetch.mock.calls.map(([u]) => u)
    expect(urls.some((u) => u.includes('/cost/rolling-24h'))).toBe(true)
    expect(urls.some((u) => u.includes('/cost/top-issues'))).toBe(true)
    expect(urls.some((u) => u.includes('/loops/cost'))).toBe(true)
    expect(urls.some((u) => u.includes('/cost/by-model'))).toBe(true)
  })

  it('renders the waterfall input form', async () => {
    global.fetch = buildFetchStub()
    render(<FactoryCostTab range="7d" />)
    expect(screen.getByPlaceholderText(/Issue number/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Load/i })).toBeInTheDocument()
  })

  it('fetches /cost/by-model and passes rows to CostByModelChart', async () => {
    const byModelRows = [
      {
        model: 'claude-opus-4-7',
        cost_usd: 8.0,
        calls: 50,
        input_tokens: 400_000,
        output_tokens: 25_000,
        cache_read_tokens: 0,
        cache_write_tokens: 0,
      },
      {
        model: 'claude-sonnet-4-6',
        cost_usd: 2.0,
        calls: 30,
        input_tokens: 200_000,
        output_tokens: 15_000,
        cache_read_tokens: 0,
        cache_write_tokens: 0,
      },
    ]
    global.fetch = vi.fn((url) => {
      if (url.includes('/cost/by-model')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(byModelRows) })
      }
      return buildFetchStub()(url)
    })
    render(<FactoryCostTab range="7d" />)
    await waitFor(() => {
      expect(screen.getByTestId('seg-claude-opus-4-7')).toBeInTheDocument()
      expect(screen.getByTestId('seg-claude-sonnet-4-6')).toBeInTheDocument()
    })
  })
})
