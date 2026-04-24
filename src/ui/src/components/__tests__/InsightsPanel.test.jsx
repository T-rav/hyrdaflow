import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

vi.mock('../HarnessInsightsPanel', () => ({
  HarnessInsightsPanel: () => <div>HarnessInsightsPanel</div>,
}))

// Dynamic import after mocks
const { InsightsPanel } = await import('../InsightsPanel')

function memoriesPayload(overrides = {}) {
  return {
    total_items: 2,
    items: [
      { issue_number: 42, learning: 'Always validate inputs' },
      { issue_number: 55, learning: 'Use async for I/O' },
    ],
    ...overrides,
  }
}

function troubleshootingPayload(overrides = {}) {
  return {
    total_patterns: 2,
    patterns: [
      {
        language: 'python',
        pattern_name: 'truthy_asyncmock',
        description: 'AsyncMock is always truthy',
        fix_strategy: 'Use .called or .call_count instead',
        frequency: 3,
        source_issues: [10, 20, 30],
      },
      {
        language: 'node',
        pattern_name: 'jest_open_handles',
        description: 'Jest hangs due to open handles',
        fix_strategy: 'Use --forceExit or close resources',
        frequency: 1,
        source_issues: [42],
      },
    ],
    ...overrides,
  }
}

function defaultContext(overrides = {}) {
  return {
    config: { repo: 'T-rav/hyrda' },
    harnessInsights: null,
    reviewInsights: null,
    retrospectives: null,
    troubleshooting: null,
    ...overrides,
  }
}

describe('InsightsPanel — Troubleshooting Patterns top-level section', () => {
  beforeEach(() => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      troubleshooting: troubleshootingPayload(),
    }))
  })

  it('renders the Troubleshooting Patterns top-level section', () => {
    render(<InsightsPanel />)
    expect(screen.getByText('Troubleshooting Patterns')).toBeInTheDocument()
  })

  it('shows patterns when expanded', async () => {
    render(<InsightsPanel />)
    fireEvent.click(screen.getByText('Troubleshooting Patterns'))

    await waitFor(() => {
      expect(screen.getByText('truthy_asyncmock')).toBeInTheDocument()
      expect(screen.getByText('3x')).toBeInTheDocument()
      expect(screen.getByText('python')).toBeInTheDocument()
    })
  })

  it('expands pattern to show fix strategy', async () => {
    render(<InsightsPanel />)
    fireEvent.click(screen.getByText('Troubleshooting Patterns'))

    await waitFor(() => {
      expect(screen.getByText('truthy_asyncmock')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('truthy_asyncmock'))

    await waitFor(() => {
      expect(screen.getByText('AsyncMock is always truthy')).toBeInTheDocument()
      expect(screen.getByText('Use .called or .call_count instead')).toBeInTheDocument()
    })
  })

  it('shows empty state when no patterns exist', async () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      troubleshooting: { total_patterns: 0, patterns: [] },
    }))

    render(<InsightsPanel />)
    fireEvent.click(screen.getByText('Troubleshooting Patterns'))

    await waitFor(() => {
      expect(screen.getByText('No troubleshooting patterns recorded yet.')).toBeInTheDocument()
    })
  })
})
