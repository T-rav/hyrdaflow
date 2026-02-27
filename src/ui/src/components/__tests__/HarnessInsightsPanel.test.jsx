import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { HarnessInsightsPanel } = await import('../HarnessInsightsPanel')

function insightsPayload(overrides = {}) {
  return {
    total_failures: 3,
    category_counts: {
      quality_gate: 2,
      review_rejection: 1,
    },
    subcategory_counts: {},
    suggestions: [],
    proposed_patterns: [],
    ...overrides,
  }
}

describe('HarnessInsightsPanel cache', () => {
  beforeEach(() => {
    localStorage.clear()
    mockUseHydraFlow.mockReturnValue({
      config: { repo: 'T-rav/hyrda' },
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('loads cached data when API fetch fails', async () => {
    localStorage.setItem(
      'hydraflow:harness-insights:T-rav/hyrda',
      JSON.stringify(insightsPayload({ total_failures: 7 })),
    )
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))

    render(<HarnessInsightsPanel />)

    await waitFor(() => {
      expect(screen.getByText('Failure Categories')).toBeInTheDocument()
      expect(screen.getByText('cached')).toBeInTheDocument()
      expect(screen.getByText('7')).toBeInTheDocument()
    })
  })

  it('writes fresh API payload to localStorage', async () => {
    const payload = insightsPayload({ total_failures: 5 })
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => payload,
      }),
    )

    render(<HarnessInsightsPanel />)

    await waitFor(() => {
      expect(screen.getByText('Failure Categories')).toBeInTheDocument()
      expect(screen.getByText('5')).toBeInTheDocument()
    })

    const raw = localStorage.getItem('hydraflow:harness-insights:T-rav/hyrda')
    expect(raw).not.toBeNull()
    expect(JSON.parse(raw).total_failures).toBe(5)
  })
})
