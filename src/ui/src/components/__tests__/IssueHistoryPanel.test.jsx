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
        session_ids: ['acme-app-20260220T000000'],
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
        session_ids: ['other-repo-20260221T000000'],
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
    mockUseHydraFlow.mockReturnValue({ issueHistory: makePayload(), selectedRepoSlug: null })
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

  it('filters rows by selected repo slug based on session ids', () => {
    mockUseHydraFlow.mockReturnValue({ issueHistory: makePayload(), selectedRepoSlug: 'acme-app' })
    render(<OutcomesPanel />)
    expect(screen.getByText('Fix auth cache')).toBeInTheDocument()
    expect(screen.queryByText('Merge docs')).toBeNull()
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
    mockUseHydraFlow.mockReturnValue({ issueHistory: payload, selectedRepoSlug: null })
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

  it('skips linked issues with null target_id instead of rendering #null pill', () => {
    const payload = makePayload()
    payload.items[0].linked_issues = [
      { target_id: null, kind: 'supersedes', target_url: null },
      { target_id: 5, kind: 'relates_to', target_url: null },
    ]
    mockUseHydraFlow.mockReturnValue({ issueHistory: payload, selectedRepoSlug: null })
    render(<OutcomesPanel />)
    fireEvent.click(screen.getByLabelText('Toggle issue 10'))
    // Should render the valid linked issue
    expect(screen.getByText('relates to #5')).toBeInTheDocument()
    // Should NOT render #null
    expect(screen.queryByText(/#null/)).not.toBeInTheDocument()
  })

  it('skips linked issues with undefined target_id', () => {
    const payload = makePayload()
    payload.items[0].linked_issues = [
      { kind: 'supersedes', target_url: null },
      { target_id: 7, kind: 'duplicates', target_url: null },
    ]
    mockUseHydraFlow.mockReturnValue({ issueHistory: payload, selectedRepoSlug: null })
    render(<OutcomesPanel />)
    fireEvent.click(screen.getByLabelText('Toggle issue 10'))
    expect(screen.getByText('duplicates #7')).toBeInTheDocument()
    expect(screen.queryByText(/supersedes/)).not.toBeInTheDocument()
  })

  it('skips linked issue objects with target_id of 0', () => {
    const payload = makePayload()
    payload.items[0].linked_issues = [
      { target_id: 0, kind: 'relates_to', target_url: null },
    ]
    mockUseHydraFlow.mockReturnValue({ issueHistory: payload, selectedRepoSlug: null })
    render(<OutcomesPanel />)
    fireEvent.click(screen.getByLabelText('Toggle issue 10'))
    // target_id=0 is falsy, should be skipped
    expect(screen.queryByText('relates to #0')).not.toBeInTheDocument()
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

  describe('column sorting', () => {
    it('sorts ascending on first click, descending on second, removes sort on third', () => {
      render(<OutcomesPanel />)
      const header = screen.getByRole('columnheader', { name: /^#/ })

      // First click: ascending (issue 10 before 11 — already natural order)
      fireEvent.click(header)
      expect(header).toHaveAttribute('aria-sort', 'ascending')
      expect(screen.getByTestId('sort-indicator-number')).toHaveTextContent('\u25B2')

      // Second click: descending
      fireEvent.click(header)
      expect(header).toHaveAttribute('aria-sort', 'descending')
      expect(screen.getByTestId('sort-indicator-number')).toHaveTextContent('\u25BC')

      // Third click: remove sort
      fireEvent.click(header)
      expect(header).toHaveAttribute('aria-sort', 'none')
      expect(screen.queryByTestId('sort-indicator-number')).not.toBeInTheDocument()
    })

    it('sorts rows by issue number descending', () => {
      render(<OutcomesPanel />)
      const header = screen.getByRole('columnheader', { name: /^#/ })

      // Click twice for descending
      fireEvent.click(header)
      fireEvent.click(header)

      // Issue 11 should appear before issue 10 in DOM order
      const links = screen.getAllByText(/^#\d+$/).filter(el => el.tagName === 'A')
      expect(links[0]).toHaveTextContent('#11')
      expect(links[1]).toHaveTextContent('#10')
    })

    it('sorts rows by title ascending', () => {
      render(<OutcomesPanel />)
      const header = screen.getByRole('columnheader', { name: 'Title' })
      fireEvent.click(header)

      // 'Fix auth cache' < 'Merge docs' alphabetically
      const titles = screen.getAllByText(/Fix auth cache|Merge docs/)
      expect(titles[0]).toHaveTextContent('Fix auth cache')
      expect(titles[1]).toHaveTextContent('Merge docs')
    })

    it('switching sort column resets to ascending', () => {
      render(<OutcomesPanel />)
      const numHeader = screen.getByRole('columnheader', { name: /^#/ })
      const titleHeader = screen.getByRole('columnheader', { name: 'Title' })

      // Sort by # descending
      fireEvent.click(numHeader)
      fireEvent.click(numHeader)
      expect(numHeader).toHaveAttribute('aria-sort', 'descending')

      // Switch to Title — should start ascending
      fireEvent.click(titleHeader)
      expect(titleHeader).toHaveAttribute('aria-sort', 'ascending')
      expect(numHeader).toHaveAttribute('aria-sort', 'none')
    })

    it('sorting works in grouped view', () => {
      const payload = makePayload()
      payload.items[0].epic = 'epic:auth'
      payload.items[1].epic = 'epic:auth'
      payload.items[1].issue_number = 5
      mockUseHydraFlow.mockReturnValue({ issueHistory: payload, selectedRepoSlug: null })
      render(<OutcomesPanel />)

      // Group by epic
      const groupSelect = screen.getAllByRole('combobox').find(
        el => el.querySelector('option[value="epic"]')
      )
      fireEvent.change(groupSelect, { target: { value: 'epic' } })

      // Sort by # descending
      const numHeader = screen.getByRole('columnheader', { name: /^#/ })
      fireEvent.click(numHeader)
      fireEvent.click(numHeader)

      // Within the group, issue 10 should appear before issue 5
      const links = screen.getAllByText(/^#\d+$/).filter(el => el.tagName === 'A')
      expect(links[0]).toHaveTextContent('#10')
      expect(links[1]).toHaveTextContent('#5')
    })
  })

  describe('column reordering', () => {
    it('reorders columns via drag and drop', () => {
      render(<OutcomesPanel />)
      const headers = screen.getAllByRole('columnheader')
      // Default order: #, Title, Repo, Stage, Outcome, PRs, Tokens, Timing
      expect(headers[0]).toHaveTextContent('#')
      expect(headers[1]).toHaveTextContent('Title')

      // Simulate dragging Title to before #
      const titleHeader = headers[1]
      const numHeader = headers[0]

      const dataTransfer = {
        effectAllowed: '',
        dropEffect: '',
        setData: vi.fn(),
        getData: vi.fn(),
      }

      fireEvent.dragStart(titleHeader, { dataTransfer })
      fireEvent.dragOver(numHeader, { dataTransfer })
      fireEvent.drop(numHeader, { dataTransfer })

      // After reorder, Title should be first column
      const updatedHeaders = screen.getAllByRole('columnheader')
      expect(updatedHeaders[0]).toHaveTextContent('Title')
      expect(updatedHeaders[1]).toHaveTextContent('#')
    })

    it('cancelled drag does not reorder columns', () => {
      render(<OutcomesPanel />)
      const headers = screen.getAllByRole('columnheader')
      const titleHeader = headers[1]

      const dataTransfer = {
        effectAllowed: '',
        dropEffect: '',
        setData: vi.fn(),
        getData: vi.fn(),
      }

      fireEvent.dragStart(titleHeader, { dataTransfer })
      // Drag ends without drop
      fireEvent.dragEnd(titleHeader, { dataTransfer })

      // Order should be unchanged
      const updatedHeaders = screen.getAllByRole('columnheader')
      expect(updatedHeaders[0]).toHaveTextContent('#')
      expect(updatedHeaders[1]).toHaveTextContent('Title')
    })

    it('column order persists across grouping changes', () => {
      render(<OutcomesPanel />)
      const headers = screen.getAllByRole('columnheader')

      // Reorder: drag Title before #
      const dataTransfer = {
        effectAllowed: '',
        dropEffect: '',
        setData: vi.fn(),
        getData: vi.fn(),
      }
      fireEvent.dragStart(headers[1], { dataTransfer })
      fireEvent.drop(headers[0], { dataTransfer })

      // Switch to grouped view and back
      const groupSelect = screen.getAllByRole('combobox').find(
        el => el.querySelector('option[value="epic"]')
      )
      fireEvent.change(groupSelect, { target: { value: 'epic' } })
      fireEvent.change(groupSelect, { target: { value: 'none' } })

      // Column order should be preserved
      const finalHeaders = screen.getAllByRole('columnheader')
      expect(finalHeaders[0]).toHaveTextContent('Title')
      expect(finalHeaders[1]).toHaveTextContent('#')
    })

    it('dropping column on itself does not change order', () => {
      render(<OutcomesPanel />)
      const headers = screen.getAllByRole('columnheader')
      const numHeader = headers[0]

      const dataTransfer = {
        effectAllowed: '',
        dropEffect: '',
        setData: vi.fn(),
        getData: vi.fn(),
      }

      fireEvent.dragStart(numHeader, { dataTransfer })
      fireEvent.drop(numHeader, { dataTransfer })

      const updatedHeaders = screen.getAllByRole('columnheader')
      expect(updatedHeaders[0]).toHaveTextContent('#')
      expect(updatedHeaders[1]).toHaveTextContent('Title')
    })
  })
})
