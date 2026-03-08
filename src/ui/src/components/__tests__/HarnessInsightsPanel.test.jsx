import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

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

describe('HarnessInsightsPanel', () => {
  beforeEach(() => {
    mockUseHydraFlow.mockReturnValue({
      harnessInsights: null,
    })
  })

  it('shows loading state when harnessInsights is null', () => {
    render(<HarnessInsightsPanel />)
    expect(screen.getByText('Loading harness insights...')).toBeInTheDocument()
  })

  it('renders failure categories from context data', () => {
    mockUseHydraFlow.mockReturnValue({
      harnessInsights: insightsPayload({ total_failures: 7 }),
    })

    render(<HarnessInsightsPanel />)

    expect(screen.getByText('Failure Categories')).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
  })

  it('renders data with different total_failures from context', () => {
    mockUseHydraFlow.mockReturnValue({
      harnessInsights: insightsPayload({ total_failures: 5 }),
    })

    render(<HarnessInsightsPanel />)

    expect(screen.getByText('Failure Categories')).toBeInTheDocument()
    expect(screen.getByText('5')).toBeInTheDocument()
  })
})
