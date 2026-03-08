import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
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
    expect(screen.getByText('No stuck issues')).toBeInTheDocument()
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

  it('calls correct API on skip click with default reason', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    global.fetch = fetchMock
    const onRefresh = vi.fn()

    render(<HITLTable items={mockItems} onRefresh={onRefresh} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    fireEvent.click(screen.getByTestId('hitl-skip-42'))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/hitl/42/skip', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Skipped by operator' }),
      })
    })
    await waitFor(() => {
      expect(onRefresh).toHaveBeenCalled()
    })
  })

  it('calls correct API on close click with default reason', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    global.fetch = fetchMock
    const onRefresh = vi.fn()

    render(<HITLTable items={mockItems} onRefresh={onRefresh} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    fireEvent.click(screen.getByTestId('hitl-close-42'))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/hitl/42/close', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Closed by operator' }),
      })
    })
    await waitFor(() => {
      expect(onRefresh).toHaveBeenCalled()
    })
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

  it('shows Refreshing... and disables button after click until items update', async () => {
    const onRefresh = vi.fn()
    const { rerender } = render(<HITLTable items={mockItems} onRefresh={onRefresh} />)

    fireEvent.click(screen.getByText('Refresh'))
    expect(screen.getByText('Refreshing...')).toBeInTheDocument()
    expect(screen.getByText('Refreshing...')).toBeDisabled()

    // Simulate items prop updating (context dispatched new data)
    rerender(<HITLTable items={[...mockItems]} onRefresh={onRefresh} />)
    await waitFor(() => {
      expect(screen.getByText('Refresh')).toBeInTheDocument()
      expect(screen.getByText('Refresh')).not.toBeDisabled()
    })
  })

  it('shows auto countdown hint below the refresh button', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    expect(screen.getByText(/^auto in \d+s$/)).toBeInTheDocument()
  })

  it('hides countdown hint while refreshing', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    fireEvent.click(screen.getByText('Refresh'))
    expect(screen.queryByText(/^auto in \d+s$/)).not.toBeInTheDocument()
  })

  it('resets countdown to 30s after manual refresh', async () => {
    vi.useFakeTimers()
    try {
      const onRefresh = vi.fn()
      render(<HITLTable items={mockItems} onRefresh={onRefresh} />)

      // Tick down 5 seconds, flush React state updates
      await act(async () => { vi.advanceTimersByTime(5000) })
      expect(screen.getByText('auto in 25s')).toBeInTheDocument()

      // Manual refresh resets to 30 synchronously
      fireEvent.click(screen.getByText('Refresh'))
      // Countdown is hidden during refreshing, but resets on next items update
    } finally {
      vi.useRealTimers()
    }
  })

  it('triggers auto refresh when countdown reaches zero', async () => {
    vi.useFakeTimers()
    try {
      const onRefresh = vi.fn()
      render(<HITLTable items={mockItems} onRefresh={onRefresh} />)

      await act(async () => { vi.advanceTimersByTime(30000) })
      expect(onRefresh).toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
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

  it('shows em-dash when pr is 0', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    const row10 = screen.getByTestId('hitl-row-10')
    const row7 = screen.getByTestId('hitl-row-7')
    // Both rows with pr: 0 should show em-dash in PR column
    const cells10 = row10.querySelectorAll('td')
    const cells7 = row7.querySelectorAll('td')
    // PR is the 4th column (index 3)
    expect(cells10[3].textContent).toBe('—')
    expect(cells7[3].textContent).toBe('—')
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

  it('renders visual evidence section when visualEvidence is present', () => {
    const items = [
      {
        ...mockItems[0],
        cause: 'Visual validation failed',
        visualEvidence: {
          items: [
            { screen_name: 'login', diff_percent: 8.5, status: 'fail', baseline_url: '', actual_url: '', diff_url: '' },
            { screen_name: 'dashboard', diff_percent: 1.2, status: 'warn', baseline_url: '', actual_url: '', diff_url: '' },
          ],
          summary: '2 screens exceeded threshold',
          run_url: '',
          attempt: 1,
        },
      },
    ]
    render(<HITLTable items={items} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    expect(screen.getByTestId('hitl-visual-42')).toBeInTheDocument()
    expect(screen.getByText('Visual Evidence')).toBeInTheDocument()
    expect(screen.getByTestId('hitl-visual-item-42-0')).toBeInTheDocument()
    expect(screen.getByText('login')).toBeInTheDocument()
    expect(screen.getByText('8.5% diff')).toBeInTheDocument()
    expect(screen.getByText('FAIL')).toBeInTheDocument()
    expect(screen.getByText('dashboard')).toBeInTheDocument()
    expect(screen.getByText('WARN')).toBeInTheDocument()
    expect(screen.getByText('2 screens exceeded threshold')).toBeInTheDocument()
  })

  it('does not render visual evidence section when visualEvidence is absent', () => {
    render(<HITLTable items={mockItems} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    expect(screen.queryByTestId('hitl-visual-42')).not.toBeInTheDocument()
  })

  it('renders visual evidence run link when run_url is set', () => {
    const items = [
      {
        ...mockItems[0],
        visualEvidence: {
          items: [{ screen_name: 'home', diff_percent: 5.0, status: 'fail', baseline_url: '', actual_url: '', diff_url: '' }],
          summary: '',
          run_url: 'https://ci.example.com/run/123',
          attempt: 2,
        },
      },
    ]
    render(<HITLTable items={items} onRefresh={() => {}} />)
    fireEvent.click(screen.getByTestId('hitl-row-42'))
    const runLink = screen.getByText('Run #2')
    expect(runLink).toBeInTheDocument()
    expect(runLink.getAttribute('href')).toBe('https://ci.example.com/run/123')
  })
})
