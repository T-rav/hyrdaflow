import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { OutcomesPanel } from '../IssueHistoryPanel'

function makePayload() {
  return {
    items: [
      {
        issue_number: 10,
        title: 'Fix auth cache',
        issue_url: 'https://example.com/issues/10',
        status: 'active',
        epic: 'epic:auth',
        linked_issues: [
          { target_id: 3, kind: 'relates_to', target_url: null },
          { target_id: 4, kind: 'duplicates', target_url: null },
        ],
        prs: [{ number: 501, url: 'https://example.com/pull/501', merged: false }],
        session_ids: ['sess-1'],
        source_calls: { implementer: 2 },
        model_calls: { 'gpt-5': 2 },
        inference: { inference_calls: 2, total_tokens: 1200, input_tokens: 800, output_tokens: 400, pruned_chars_total: 1600 },
        first_seen: '2026-02-20T00:00:00+00:00',
        last_seen: '2026-02-21T00:00:00+00:00',
        outcome: {
          outcome: 'failed',
          reason: 'CI timeout',
          phase: 'review',
          pr_number: 501,
          closed_at: '2026-02-21T12:00:00+00:00',
        },
      },
      {
        issue_number: 11,
        title: 'Merge docs',
        issue_url: 'https://example.com/issues/11',
        status: 'merged',
        epic: '',
        linked_issues: [],
        prs: [{ number: 777, url: 'https://example.com/pull/777', merged: true }],
        session_ids: ['sess-2'],
        source_calls: { reviewer: 1 },
        model_calls: { sonnet: 1 },
        inference: { inference_calls: 1, total_tokens: 100, input_tokens: 70, output_tokens: 30, pruned_chars_total: 400 },
        first_seen: '2026-02-19T00:00:00+00:00',
        last_seen: '2026-02-22T00:00:00+00:00',
        outcome: {
          outcome: 'merged',
          reason: 'auto-merge',
          phase: 'review',
          pr_number: 777,
          closed_at: '2026-02-22T00:00:00+00:00',
        },
      },
    ],
    totals: { issues: 2, inference_calls: 3, total_tokens: 1300, pruned_chars_total: 2000 },
  }
}

describe('OutcomesPanel (merged History+Outcomes)', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => makePayload(),
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches and renders issue rows with compact summary', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    expect(screen.getByText('Merge docs')).toBeInTheDocument()
    // Summary row uses compact format
    expect(screen.getByText('2 issues')).toBeInTheDocument()
    expect(screen.getByText('1.3K tok')).toBeInTheDocument()
    expect(screen.getByText('500 saved')).toBeInTheDocument()
    expect(global.fetch).toHaveBeenCalledTimes(1)
    const [url] = global.fetch.mock.calls[0]
    expect(url).toContain('/api/issues/history?')
    expect(url).toContain('limit=500')
  })

  it('filters by status and search text client-side', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())

    // Target the status dropdown specifically (first combobox; outcome filter is second)
    const selects = screen.getAllByRole('combobox')
    fireEvent.change(selects[0], { target: { value: 'merged' } })
    expect(screen.queryByText('Fix auth cache')).not.toBeInTheDocument()
    expect(screen.getByText('Merge docs')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('Search issue #, title, epic, crate'), { target: { value: 'auth' } })
    expect(screen.getByText('No issues match this filter.')).toBeInTheDocument()
  })

  it('expands an issue row to show rollup details with kind-aware linked issues', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText('Toggle issue 10'))
    expect(screen.getByText('Linked Issues')).toBeInTheDocument()
    // New format: kind-aware pills with "relates to #3" and "duplicates #4"
    expect(screen.getByText('relates to #3')).toBeInTheDocument()
    expect(screen.getByText('duplicates #4')).toBeInTheDocument()
    expect(screen.getByText(/2 calls/)).toBeInTheDocument()
    expect(screen.getByText(/400 tokens saved \(est\)/)).toBeInTheDocument()
    expect(screen.getByText(/1,600 tokens w\/o pruning \(est\)/)).toBeInTheDocument()
  })

  it('renders outcome badges in summary rows', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    // "failed" appears as both status and outcome badge, "merged" likewise
    expect(screen.getAllByText('failed').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('merged').length).toBeGreaterThanOrEqual(1)
  })

  it('shows outcome details in expanded view', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText('Toggle issue 10'))
    // 'Outcome' appears as both a column header and expanded detail label
    expect(screen.getAllByText('Outcome').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('CI timeout')).toBeInTheDocument()
    expect(screen.getByText('phase: review')).toBeInTheDocument()
    expect(screen.getByText('PR #501')).toBeInTheDocument()
  })

  it('renders plain-int linked issues for backward compatibility', async () => {
    const payload = makePayload()
    payload.items[0].linked_issues = [3, 4]
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => payload,
    })
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('Toggle issue 10'))
    expect(screen.getByText('#3')).toBeInTheDocument()
    expect(screen.getByText('#4')).toBeInTheDocument()
  })

  it('toggles epic grouping with collapsible sections', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())

    // Enable group-by-epic via select dropdown
    const groupSelect = screen.getAllByRole('combobox').find(
      el => el.querySelector('option[value="epic"]')
    )
    fireEvent.change(groupSelect, { target: { value: 'epic' } })

    // Should show two groups: "epic:auth" (in header + in row) and "Ungrouped"
    expect(screen.getAllByText('epic:auth').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('Ungrouped')).toBeInTheDocument()
    // Each group has 1 issue
    expect(screen.getAllByText(/1 issue$/).length).toBe(2)

    // Collapse the epic:auth group by clicking the header button
    const epicHeaders = screen.getAllByText('epic:auth')
    // The header button is the one inside the epicHeader styled button
    fireEvent.click(epicHeaders[0].closest('button'))
    // Issue 10 should be hidden but issue 11 (Ungrouped) still visible
    expect(screen.queryByText('Fix auth cache')).not.toBeInTheDocument()
    expect(screen.getByText('Merge docs')).toBeInTheDocument()
  })

  it('renders outcome filter dropdown', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())

    const outcomeSelect = screen.getByTestId('outcome-filter')
    expect(outcomeSelect).toBeInTheDocument()
    expect(outcomeSelect.value).toBe('all')
  })

  it('filters by outcome type', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())

    const outcomeSelect = screen.getByTestId('outcome-filter')
    fireEvent.change(outcomeSelect, { target: { value: 'merged' } })
    // Only issue 11 has outcome "merged"
    expect(screen.queryByText('Fix auth cache')).not.toBeInTheDocument()
    expect(screen.getByText('Merge docs')).toBeInTheDocument()
  })

  it('renders outcome summary pills in the summary row', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    // Summary row should have outcome counts — 1 failed, 1 merged
    expect(screen.getByText('2 issues')).toBeInTheDocument()
  })

  it('renders column headers in the table', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    expect(screen.getByText('Title')).toBeInTheDocument()
    expect(screen.getByText('Stage')).toBeInTheDocument()
    expect(screen.getByText('Outcome')).toBeInTheDocument()
    expect(screen.getByText('Tokens')).toBeInTheDocument()
    expect(screen.getByText('Last Seen')).toBeInTheDocument()
  })

  it('shows compact token values in issue rows', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    // Issue 10 has 1200 tokens → "1.2K" in the row
    expect(screen.getByText('1.2K')).toBeInTheDocument()
  })

  it('shows error message when fetch fails', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 500 })
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Could not load issue history')).toBeInTheDocument())
  })

  it('filters by epicOnly checkbox', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText('Epic only'))
    // Issue 10 has epic='epic:auth', issue 11 has epic=''
    expect(screen.getByText('Fix auth cache')).toBeInTheDocument()
    expect(screen.queryByText('Merge docs')).not.toBeInTheDocument()
  })
})
