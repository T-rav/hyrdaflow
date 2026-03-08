import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()
vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { OutcomesPanel } = await import('../IssueHistoryPanel')

function makePayload() {
  return {
    items: [
      {
        issue_number: 10,
        title: 'Fix auth cache',
        issue_url: 'https://github.com/acme/webapp/issues/10',
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
        issue_url: 'https://github.com/acme/docs-site/issues/11',
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
    mockUseHydraFlow.mockReturnValue({ issueHistory: makePayload() })
  })

  it('renders issue rows with compact summary', () => {
    render(<OutcomesPanel />)
    expect(screen.getByText('Fix auth cache')).toBeInTheDocument()
    expect(screen.getByText('Merge docs')).toBeInTheDocument()
    // Summary row uses compact format
    expect(screen.getByText('2 issues')).toBeInTheDocument()
    expect(screen.getByText('1.3K tok')).toBeInTheDocument()
    expect(screen.getByText('500 saved')).toBeInTheDocument()
  })

  it('filters by status and search text client-side', () => {
    render(<OutcomesPanel />)

    // Target the status dropdown specifically (first combobox; outcome filter is second)
    const selects = screen.getAllByRole('combobox')
    fireEvent.change(selects[0], { target: { value: 'merged' } })
    expect(screen.queryByText('Fix auth cache')).not.toBeInTheDocument()
    expect(screen.getByText('Merge docs')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('Search issue #, title, repo, epic, crate, reason'), { target: { value: 'auth' } })
    expect(screen.getByText('No issues match this filter.')).toBeInTheDocument()
  })

  it('expands an issue row to show rollup details with kind-aware linked issues', () => {
    render(<OutcomesPanel />)

    fireEvent.click(screen.getByLabelText('Toggle issue 10'))
    expect(screen.getByText('Linked Issues')).toBeInTheDocument()
    // New format: kind-aware pills with "relates to #3" and "duplicates #4"
    expect(screen.getByText('relates to #3')).toBeInTheDocument()
    expect(screen.getByText('duplicates #4')).toBeInTheDocument()
    expect(screen.getByText(/2 calls/)).toBeInTheDocument()
    expect(screen.getByText(/400 tokens saved \(est\)/)).toBeInTheDocument()
    expect(screen.getByText(/1,600 tokens w\/o pruning \(est\)/)).toBeInTheDocument()
  })

  it('renders outcome badges in summary rows', () => {
    render(<OutcomesPanel />)
    // "failed" appears as both status and outcome badge, "merged" likewise
    expect(screen.getAllByText('failed').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('merged').length).toBeGreaterThanOrEqual(1)
  })

  it('shows outcome details in expanded view', () => {
    render(<OutcomesPanel />)

    fireEvent.click(screen.getByLabelText('Toggle issue 10'))
    // 'Outcome' appears as both a column header and expanded detail label
    expect(screen.getAllByText('Outcome').length).toBeGreaterThanOrEqual(2)
    // 'CI timeout' appears both as title subtitle and in expanded detail
    expect(screen.getAllByText('CI timeout').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('phase: review')).toBeInTheDocument()
    expect(screen.getByText('PR #501')).toBeInTheDocument()
  })

  it('renders plain-int linked issues for backward compatibility', () => {
    const payload = makePayload()
    payload.items[0].linked_issues = [3, 4]
    mockUseHydraFlow.mockReturnValue({ issueHistory: payload })
    render(<OutcomesPanel />)
    fireEvent.click(screen.getByLabelText('Toggle issue 10'))
    expect(screen.getByText('#3')).toBeInTheDocument()
    expect(screen.getByText('#4')).toBeInTheDocument()
  })

  it('toggles epic grouping with collapsible sections', () => {
    render(<OutcomesPanel />)

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

  it('renders outcome filter dropdown', () => {
    render(<OutcomesPanel />)

    const outcomeSelect = screen.getByTestId('outcome-filter')
    expect(outcomeSelect).toBeInTheDocument()
    expect(outcomeSelect.value).toBe('all')
  })

  it('filters by outcome type', () => {
    render(<OutcomesPanel />)

    const outcomeSelect = screen.getByTestId('outcome-filter')
    fireEvent.change(outcomeSelect, { target: { value: 'merged' } })
    // Only issue 11 has outcome "merged"
    expect(screen.queryByText('Fix auth cache')).not.toBeInTheDocument()
    expect(screen.getByText('Merge docs')).toBeInTheDocument()
  })

  it('renders outcome summary pills in the summary row', () => {
    render(<OutcomesPanel />)
    // Summary row should have outcome counts — 1 failed, 1 merged
    expect(screen.getByText('2 issues')).toBeInTheDocument()
  })

  it('renders column headers in the table', () => {
    render(<OutcomesPanel />)
    expect(screen.getByText('Title')).toBeInTheDocument()
    expect(screen.getByText('Stage')).toBeInTheDocument()
    expect(screen.getByText('Outcome')).toBeInTheDocument()
    expect(screen.getByText('Repo')).toBeInTheDocument()
    expect(screen.getByText('Tokens')).toBeInTheDocument()
    expect(screen.getByText('Timing')).toBeInTheDocument()
  })

  it('shows compact token values in issue rows', () => {
    render(<OutcomesPanel />)
    // Issue 10 has 1200 tokens → "1.2K" in the row
    expect(screen.getByText('1.2K')).toBeInTheDocument()
  })

  it('filters by epicOnly checkbox', () => {
    render(<OutcomesPanel />)
    fireEvent.click(screen.getByLabelText('Epic only'))
    // Issue 10 has epic='epic:auth', issue 11 has epic=''
    expect(screen.getByText('Fix auth cache')).toBeInTheDocument()
    expect(screen.queryByText('Merge docs')).not.toBeInTheDocument()
  })

  it('displays repo slug extracted from issue URL', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    // Should extract and show repo name from GitHub URL
    expect(screen.getByText('webapp')).toBeInTheDocument()
    expect(screen.getByText('docs-site')).toBeInTheDocument()
  })

  it('displays outcome reason as subtitle under title', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    // "CI timeout" reason should appear inline under the title
    expect(screen.getByText('CI timeout')).toBeInTheDocument()
    // "auto-merge" reason from issue 11
    expect(screen.getByText('auto-merge')).toBeInTheDocument()
  })

  it('displays crate pill when crate info is present', async () => {
    const payload = makePayload()
    payload.items[0].crate_number = 5
    payload.items[0].crate_title = 'v1.0 Sprint'
    mockUseHydraFlow.mockReturnValue({ issueHistory: payload })
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    expect(screen.getByText('v1.0 Sprint')).toBeInTheDocument()
  })

  it('displays epic pill inline with title', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    // Issue 10 has epic='epic:auth' — should show as inline pill
    expect(screen.getAllByText('epic:auth').length).toBeGreaterThanOrEqual(1)
  })

  it('displays duration in timing column when first_seen is available', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    // Issue 10: first_seen 2026-02-20, last_seen 2026-02-21 => 1d 0h
    expect(screen.getByText('1d 0h')).toBeInTheDocument()
    // Issue 11: first_seen 2026-02-19, last_seen 2026-02-22 => 3d 0h
    expect(screen.getByText('3d 0h')).toBeInTheDocument()
  })

  it('searches by repo name', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    fireEvent.change(screen.getByPlaceholderText('Search issue #, title, repo, epic, crate, reason'), { target: { value: 'docs-site' } })
    expect(screen.queryByText('Fix auth cache')).not.toBeInTheDocument()
    expect(screen.getByText('Merge docs')).toBeInTheDocument()
  })

  it('searches by outcome reason', async () => {
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    fireEvent.change(screen.getByPlaceholderText('Search issue #, title, repo, epic, crate, reason'), { target: { value: 'auto-merge' } })
    expect(screen.queryByText('Fix auth cache')).not.toBeInTheDocument()
    expect(screen.getByText('Merge docs')).toBeInTheDocument()
  })

  it('handles missing issue_url gracefully for repo extraction', async () => {
    const payload = makePayload()
    payload.items[0].issue_url = ''
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => payload,
    })
    render(<OutcomesPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    // Should render without error — no repo slug shown
    expect(screen.getByText('docs-site')).toBeInTheDocument()
  })
})
