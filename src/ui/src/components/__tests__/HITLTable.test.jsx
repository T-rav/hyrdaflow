import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { HITLTable } from '../HITLTable'

const mockItems = [
  {
    issue: 42,
    title: 'Fix widget',
    issueUrl: 'https://github.com/org/repo/issues/42',
    pr: 99,
    prUrl: 'https://github.com/org/repo/pull/99',
    branch: 'agent/issue-42',
    cause: 'CI failure',
    status: 'from review',
    llmSummary: 'CI is failing on lint.\nBranch has stale rebase.\nRe-run after pulling main.\nUpdate snapshots for new output.\nThen request retry.',
  },
  {
    issue: 10,
    title: 'Broken thing',
    issueUrl: '',
    pr: 0,
    prUrl: '',
    branch: 'agent/issue-10',
    cause: '',
    status: 'processing',
  },
  {
    issue: 7,
    title: 'Legacy item',
    issueUrl: '',
    pr: 0,
    prUrl: '',
    branch: 'agent/issue-7',
    status: 'pending',
  },
]

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('HITLTable component', () => {
  it('renders table with items', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    expect(screen.getByText('#42')).toBeInTheDocument()
    expect(screen.getByText('Fix widget')).toBeInTheDocument()
    expect(screen.getByText('#99')).toBeInTheDocument()
    expect(screen.getByText('agent/issue-42')).toBeInTheDocument()
  })

  it('shows empty state when no items', () => {
    render(<HITLTable items={[]} onRefresh={() => {}} />)
    expect(screen.getByText('No stuck PRs')).toBeInTheDocument()
  })

  it('renders status column header', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    expect(screen.getByText('Status')).toBeInTheDocument()
  })

  it('renders status badges for each item', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    expect(screen.getByText('from review')).toBeInTheDocument()
    expect(screen.getByText('processing')).toBeInTheDocument()
  })

  it('renders from triage status badge', () => {
    const items = [{ ...mockItems[0], status: 'from triage' }]
    render(<HITLTable items={items} onRefresh={() => {}} />)
    expect(screen.getByText('from triage')).toBeInTheDocument()
  })

  it('renders from plan status badge', () => {
    const items = [{ ...mockItems[0], status: 'from plan' }]
    render(<HITLTable items={items} onRefresh={() => {}} />)
    expect(screen.getByText('from plan')).toBeInTheDocument()
  })

  it('renders from implement status badge', () => {
    const items = [{ ...mockItems[0], status: 'from implement' }]
    render(<HITLTable items={items} onRefresh={() => {}} />)
    expect(screen.getByText('from implement')).toBeInTheDocument()
  })

  it('renders unknown status with fallback styling without crashing', () => {
    const items = [{ ...mockItems[0], status: 'unknown-status' }]
    render(<HITLTable items={items} onRefresh={() => {}} />)
    expect(screen.getByText('unknown-status')).toBeInTheDocument()
  })

  it('expands row on click to show detail panel', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    expect(screen.getByTestId('hitl-detail-42')).toBeInTheDocument()
    expect(screen.getByTestId('hitl-summary-42')).toBeInTheDocument()
    expect(screen.getByTestId('hitl-textarea-42')).toBeInTheDocument()
    expect(screen.getByTestId('hitl-retry-42')).toBeInTheDocument()
    expect(screen.getByTestId('hitl-skip-42')).toBeInTheDocument()
    expect(screen.getByTestId('hitl-close-42')).toBeInTheDocument()
  })

  it('toggles summary from collapsed preview to expanded context', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    const summary = screen.getByTestId('hitl-summary-42')
    expect(summary.textContent).toContain('CI is failing on lint.')
    expect(screen.getByTestId('hitl-summary-toggle-42')).toHaveTextContent('Show more')
    fireEvent.click(screen.getByTestId('hitl-summary-toggle-42'))
    expect(screen.getByTestId('hitl-summary-toggle-42')).toHaveTextContent('Show less')
  })

  it('fetches summary on expand when not preloaded', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ summary: 'Blocking CI check.\nNeed branch rebase.' }),
    })
    global.fetch = fetchMock
    const items = [{ ...mockItems[1], llmSummary: '' }]
    render(<HITLTable items={items} onRefresh={() => {}} />)

    fireEvent.click(screen.getByTestId('hitl-row-10'))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/hitl/10/summary')
      expect(screen.getByTestId('hitl-summary-10').textContent).toContain(
        'Blocking CI check.'
      )
    })
  })

  it('shows fallback message when summary fetch fails', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 500 })
    global.fetch = fetchMock
    const items = [{ ...mockItems[1], llmSummary: '' }]
    render(<HITLTable items={items} onRefresh={() => {}} />)

    fireEvent.click(screen.getByTestId('hitl-row-10'))
    await waitFor(() => {
      expect(screen.getByTestId('hitl-summary-10').textContent).toContain(
        'Could not generate context summary yet.'
      )
    })
  })

  it('collapses row on second click', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    expect(screen.getByTestId('hitl-detail-42')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    expect(screen.queryByTestId('hitl-detail-42')).not.toBeInTheDocument()
  })

  it('shows cause badge when cause is non-empty', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    expect(screen.getByTestId('hitl-cause-42')).toBeInTheDocument()
    expect(screen.getByText('Cause: CI failure')).toBeInTheDocument()
  })

  it('hides cause badge when cause is empty', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-10'))
    expect(screen.queryByTestId('hitl-cause-10')).not.toBeInTheDocument()
  })

  it('updates correction text area state', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    const textarea = screen.getByTestId('hitl-textarea-42')
    fireEvent.change(textarea, { target: { value: 'Mock the DB' } })
    expect(textarea.value).toBe('Mock the DB')
  })

  it('retry button is disabled when textarea is empty', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    expect(screen.getByTestId('hitl-retry-42')).toBeDisabled()
  })

  it('retry button is enabled when textarea has text', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    const textarea = screen.getByTestId('hitl-textarea-42')
    fireEvent.change(textarea, { target: { value: 'Fix the tests' } })
    expect(screen.getByTestId('hitl-retry-42')).not.toBeDisabled()
  })

  it('calls correct API on retry click', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    global.fetch = fetchMock
    const onRefresh = vi.fn()

    render(<HITLTable items={mockItems} onRefresh={onRefresh} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    const textarea = screen.getByTestId('hitl-textarea-42')
    fireEvent.change(textarea, { target: { value: 'Fix the tests' } })
    fireEvent.click(screen.getByTestId('hitl-retry-42'))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/hitl/42/correct', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ correction: 'Fix the tests' }),
      })
    })
    await waitFor(() => {
      expect(onRefresh).toHaveBeenCalled()
    })
  })

  it('calls correct API on skip click', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    global.fetch = fetchMock
    const onRefresh = vi.fn()

    render(<HITLTable items={mockItems} onRefresh={onRefresh} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    fireEvent.click(screen.getByTestId('hitl-skip-42'))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/hitl/42/skip', {
        method: 'POST',
      })
    })
    await waitFor(() => {
      expect(onRefresh).toHaveBeenCalled()
    })
  })

  it('calls correct API on close click without confirmation prompt', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm')
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    global.fetch = fetchMock
    const onRefresh = vi.fn()

    render(<HITLTable items={mockItems} onRefresh={onRefresh} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    fireEvent.click(screen.getByTestId('hitl-close-42'))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/hitl/42/close', {
        method: 'POST',
      })
    })
    await waitFor(() => {
      expect(onRefresh).toHaveBeenCalled()
    })
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('removes item from UI immediately after successful close', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    global.fetch = fetchMock

    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    expect(screen.getByText('#42')).toBeInTheDocument()
    expect(screen.getByText('3 items awaiting action')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('hitl-row-42'))
    fireEvent.click(screen.getByTestId('hitl-close-42'))

    await waitFor(() => {
      expect(screen.queryByText('#42')).not.toBeInTheDocument()
      expect(screen.getByText('2 items awaiting action')).toBeInTheDocument()
    })
  })

  it('shows item count in header', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    expect(screen.getByText('3 items awaiting action')).toBeInTheDocument()
  })

  it('shows singular form for one item', () => {
    render(<HITLTable items={[mockItems[0]]} onRefresh={() => {}} />)
    expect(screen.getByText('1 item awaiting action')).toBeInTheDocument()
  })

  it('refresh button calls onRefresh prop', () => {
    const onRefresh = vi.fn()
    render(<HITLTable items={mockItems} onRefresh={onRefresh} />)
    fireEvent.click(screen.getByText('Refresh'))
    expect(onRefresh).toHaveBeenCalledOnce()
  })

  it('renders Refresh button in empty state and calls onRefresh on click', () => {
    const onRefresh = vi.fn()
    render(<HITLTable items={[]} onRefresh={onRefresh} />)
    const btn = screen.getByText('Refresh')
    expect(btn).toBeInTheDocument()
    fireEvent.click(btn)
    expect(onRefresh).toHaveBeenCalledOnce()
  })

  it('shows muted HITL header text in empty state', () => {
    render(<HITLTable items={[]} onRefresh={() => {}} />)
    expect(screen.getByText('HITL')).toBeInTheDocument()
  })

  it('does not fetch data on mount (no side effects)', () => {
    if (typeof globalThis.fetch?.mockClear === 'function') globalThis.fetch.mockClear()
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    render(<HITLTable items={[]} onRefresh={() => {}} />)
    expect(fetchSpy).not.toHaveBeenCalled()
    fetchSpy.mockRestore()
  })

  it('shows "No PR" when pr is 0', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    expect(screen.getAllByText('No PR')).toHaveLength(2)
  })

  it('renders Cause column header', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    expect(screen.getByText('Cause')).toBeInTheDocument()
  })

  it('displays cause text in table row without expanding', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    expect(screen.getByText('CI failure')).toBeInTheDocument()
    expect(screen.queryByTestId('hitl-detail-42')).not.toBeInTheDocument()
  })

  it('shows em-dash for empty cause', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    const row = screen.getByTestId('hitl-row-10')
    expect(row).toHaveTextContent('—')
  })

  it('shows em-dash when cause is undefined', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    const row = screen.getByTestId('hitl-row-7')
    expect(row).toHaveTextContent('—')
  })

  it('container has overflowX auto for horizontal scrolling', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    const table = screen.getByText('Fix widget').closest('table')
    const container = table.parentElement
    expect(container.style.overflowX).toBe('auto')
  })

  it('table has minWidth to prevent column squishing', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    const table = screen.getByText('Fix widget').closest('table')
    expect(table.style.minWidth).toBe('600px')
  })

  it('shows approve button when isMemorySuggestion is true', () => {
    const items = [{ ...mockItems[0], isMemorySuggestion: true }]
    render(<HITLTable items={items} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    expect(screen.getByTestId('hitl-approve-memory-42')).toBeInTheDocument()
    expect(screen.getByText('Approve as Memory')).toBeInTheDocument()
  })

  it('hides approve button when isMemorySuggestion is false', () => {
    const items = [{ ...mockItems[0], isMemorySuggestion: false }]
    render(<HITLTable items={items} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    expect(screen.queryByTestId('hitl-approve-memory-42')).not.toBeInTheDocument()
  })

  it('calls correct API on approve memory click', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    global.fetch = fetchMock
    const onRefresh = vi.fn()

    const items = [{ ...mockItems[0], isMemorySuggestion: true }]
    render(<HITLTable items={items} onRefresh={onRefresh} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    fireEvent.click(screen.getByTestId('hitl-approve-memory-42'))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/hitl/42/approve-memory', {
        method: 'POST',
      })
    })
    await waitFor(() => {
      expect(onRefresh).toHaveBeenCalled()
    })
  })

  it('uses purple badge for memory suggestion cause', () => {
    const items = [{
      ...mockItems[0],
      isMemorySuggestion: true,
      cause: 'Memory suggestion',
    }]
    render(<HITLTable items={items} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    const badge = screen.getByTestId('hitl-cause-42')
    expect(badge.style.background).toBe('var(--purple-subtle)')
    expect(badge.style.color).toBe('var(--purple)')
  })

  it('hides approve button when isMemorySuggestion is undefined', () => {
    const items = [{ ...mockItems[0] }]
    delete items[0].isMemorySuggestion
    render(<HITLTable items={items} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    expect(screen.queryByTestId('hitl-approve-memory-42')).not.toBeInTheDocument()
  })

  it('shows Approving... text during approve loading', async () => {
    let resolveApprove
    const fetchMock = vi.fn().mockImplementation(() =>
      new Promise(resolve => { resolveApprove = resolve })
    )
    global.fetch = fetchMock

    const items = [{ ...mockItems[0], isMemorySuggestion: true }]
    render(<HITLTable items={items} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    fireEvent.click(screen.getByTestId('hitl-approve-memory-42'))

    await waitFor(() => {
      expect(screen.getByText('Approving...')).toBeInTheDocument()
    })

    resolveApprove({ ok: true })
  })

  it('disables approve button during other action loading', async () => {
    let resolveSkip
    const fetchMock = vi.fn().mockImplementation(() =>
      new Promise(resolve => { resolveSkip = resolve })
    )
    global.fetch = fetchMock

    const items = [{ ...mockItems[0], isMemorySuggestion: true }]
    render(<HITLTable items={items} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    fireEvent.click(screen.getByTestId('hitl-skip-42'))

    await waitFor(() => {
      expect(screen.getByTestId('hitl-approve-memory-42')).toBeDisabled()
    })

    resolveSkip({ ok: true })
  })

  it('renders approval status badge with purple styling', () => {
    const items = [{ ...mockItems[0], status: 'approval' }]
    render(<HITLTable items={items} onRefresh={() => {}} />)
    const badge = screen.getByText('approval')
    expect(badge).toBeInTheDocument()
    expect(badge.style.background).toBe('var(--purple-subtle)')
    expect(badge.style.color).toBe('var(--purple)')
  })

  it('uses orange badge for non-memory cause', () => {
    const items = [{ ...mockItems[0], isMemorySuggestion: false }]
    render(<HITLTable items={items} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    const badge = screen.getByTestId('hitl-cause-42')
    expect(badge.style.background).toBe('var(--orange-subtle)')
    expect(badge.style.color).toBe('var(--orange)')
  })
})
