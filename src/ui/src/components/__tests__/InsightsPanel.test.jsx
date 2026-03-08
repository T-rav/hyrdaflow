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
    digest_chars: 5000,
    curated: {
      overview: 'A multi-agent orchestration system',
      architecture: ['Async loops', 'Event-driven'],
      key_services: ['Triage', 'Planner', 'Reviewer'],
      standards: ['Always write tests'],
    },
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
    memories: null,
    ...overrides,
  }
}

describe('InsightsPanel — LearningsSection sub-sections', () => {
  beforeEach(() => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      memories: memoriesPayload(),
      troubleshooting: troubleshootingPayload(),
    }))
  })

  it('renders the Learnings top-level section', () => {
    render(<InsightsPanel />)
    expect(screen.getByText('Learnings')).toBeInTheDocument()
  })

  it('shows Curated Knowledge sub-section with overview and architecture', async () => {
    render(<InsightsPanel />)
    // Expand Learnings section
    fireEvent.click(screen.getByText('Learnings'))

    await waitFor(() => {
      expect(screen.getByText('Curated Knowledge')).toBeInTheDocument()
      expect(screen.getByText('A multi-agent orchestration system')).toBeInTheDocument()
    })
  })

  it('shows Memory Items sub-section with search filtering', async () => {
    render(<InsightsPanel />)
    fireEvent.click(screen.getByText('Learnings'))

    await waitFor(() => {
      expect(screen.getByText('Memory Items')).toBeInTheDocument()
    })

    // Expand Memory Items sub-section
    fireEvent.click(screen.getByText('Memory Items'))

    await waitFor(() => {
      expect(screen.getByPlaceholderText('Filter by issue # or text...')).toBeInTheDocument()
    })

    // Filter by issue number
    const input = screen.getByPlaceholderText('Filter by issue # or text...')
    fireEvent.change(input, { target: { value: '42' } })

    await waitFor(() => {
      expect(screen.getByText('Always validate inputs')).toBeInTheDocument()
      expect(screen.queryByText('Use async for I/O')).not.toBeInTheDocument()
    })
  })

  it('shows Troubleshooting Patterns sub-section', async () => {
    render(<InsightsPanel />)
    fireEvent.click(screen.getByText('Learnings'))

    await waitFor(() => {
      expect(screen.getByText('Troubleshooting Patterns')).toBeInTheDocument()
    })

    // Expand Troubleshooting Patterns sub-section
    fireEvent.click(screen.getByText('Troubleshooting Patterns'))

    await waitFor(() => {
      expect(screen.getByText('truthy_asyncmock')).toBeInTheDocument()
      expect(screen.getByText('3x')).toBeInTheDocument()
      expect(screen.getByText('python')).toBeInTheDocument()
    })
  })

  it('expands troubleshooting pattern to show fix strategy', async () => {
    render(<InsightsPanel />)
    fireEvent.click(screen.getByText('Learnings'))

    await waitFor(() => {
      expect(screen.getByText('Troubleshooting Patterns')).toBeInTheDocument()
    })

    // Expand Troubleshooting Patterns sub-section
    fireEvent.click(screen.getByText('Troubleshooting Patterns'))

    await waitFor(() => {
      expect(screen.getByText('truthy_asyncmock')).toBeInTheDocument()
    })

    // Click the pattern to expand it
    fireEvent.click(screen.getByText('truthy_asyncmock'))

    await waitFor(() => {
      expect(screen.getByText('AsyncMock is always truthy')).toBeInTheDocument()
      expect(screen.getByText('Use .called or .call_count instead')).toBeInTheDocument()
    })
  })

  it('shows empty state when no troubleshooting patterns exist', async () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      memories: memoriesPayload(),
      troubleshooting: { total_patterns: 0, patterns: [] },
    }))

    render(<InsightsPanel />)
    fireEvent.click(screen.getByText('Learnings'))

    await waitFor(() => {
      expect(screen.getByText('Troubleshooting Patterns')).toBeInTheDocument()
    })

    // Expand Troubleshooting Patterns sub-section
    fireEvent.click(screen.getByText('Troubleshooting Patterns'))

    await waitFor(() => {
      expect(screen.getByText('No troubleshooting patterns recorded yet.')).toBeInTheDocument()
    })
  })
})
