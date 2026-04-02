import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

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
        epic: '',
        linked_issues: [],
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

describe('IssueHistoryPanel sortable outcome columns', () => {
  beforeEach(() => {
    mockUseHydraFlow.mockReturnValue({ issueHistory: makePayload(), selectedRepoSlug: null })
  })

  it('default sort has no active sort column (natural order)', () => {
    render(<OutcomesPanel />)
    // No column should have an active sort indicator initially
    const headers = screen.getAllByRole('columnheader')
    for (const header of headers) {
      expect(header).toHaveAttribute('aria-sort', 'none')
    }
  })

  it('clicking Timing header toggles sort direction', () => {
    render(<OutcomesPanel />)
    const header = screen.getByRole('columnheader', { name: 'Timing' })

    // First click: ascending
    fireEvent.click(header)
    expect(header).toHaveAttribute('aria-sort', 'ascending')

    // Second click: descending
    fireEvent.click(header)
    expect(header).toHaveAttribute('aria-sort', 'descending')

    // Third click: removes sort
    fireEvent.click(header)
    expect(header).toHaveAttribute('aria-sort', 'none')
  })

  it('clicking Stage header sorts by status', () => {
    render(<OutcomesPanel />)
    const header = screen.getByRole('columnheader', { name: 'Stage' })

    // Click for ascending sort
    fireEvent.click(header)
    expect(header).toHaveAttribute('aria-sort', 'ascending')

    // 'active' < 'merged' alphabetically, so issue 10 (active) should come first
    const links = screen.getAllByText(/^#\d+$/).filter(el => el.tagName === 'A')
    expect(links[0]).toHaveTextContent('#10')
    expect(links[1]).toHaveTextContent('#11')
  })

  it('sort indicator shows on active column only', () => {
    render(<OutcomesPanel />)
    const numHeader = screen.getByRole('columnheader', { name: /^#/ })
    const outcomeHeader = screen.getByRole('columnheader', { name: 'Outcome' })

    // Click # to sort
    fireEvent.click(numHeader)
    expect(screen.getByTestId('sort-indicator-number')).toHaveTextContent('\u25B2')
    expect(screen.queryByTestId('sort-indicator-outcome')).not.toBeInTheDocument()

    // Switch to Outcome
    fireEvent.click(outcomeHeader)
    expect(screen.queryByTestId('sort-indicator-number')).not.toBeInTheDocument()
    expect(screen.getByTestId('sort-indicator-outcome')).toHaveTextContent('\u25B2')
  })

  it('sorts by Outcome column ascending puts failed before merged', () => {
    render(<OutcomesPanel />)
    const header = screen.getByRole('columnheader', { name: 'Outcome' })

    fireEvent.click(header)
    expect(header).toHaveAttribute('aria-sort', 'ascending')

    // 'failed' < 'merged' alphabetically, so issue 10 (failed) first
    const links = screen.getAllByText(/^#\d+$/).filter(el => el.tagName === 'A')
    expect(links[0]).toHaveTextContent('#10')
    expect(links[1]).toHaveTextContent('#11')
  })

  it('sorts by Title column ascending', () => {
    render(<OutcomesPanel />)
    const header = screen.getByRole('columnheader', { name: 'Title' })

    fireEvent.click(header)
    // 'Fix auth cache' < 'Merge docs' alphabetically
    const titles = screen.getAllByText(/Fix auth cache|Merge docs/)
    expect(titles[0]).toHaveTextContent('Fix auth cache')
    expect(titles[1]).toHaveTextContent('Merge docs')
  })

  it('descending sort on # column puts higher number first', () => {
    render(<OutcomesPanel />)
    const header = screen.getByRole('columnheader', { name: /^#/ })

    // Two clicks for descending
    fireEvent.click(header)
    fireEvent.click(header)
    expect(header).toHaveAttribute('aria-sort', 'descending')

    const links = screen.getAllByText(/^#\d+$/).filter(el => el.tagName === 'A')
    expect(links[0]).toHaveTextContent('#11')
    expect(links[1]).toHaveTextContent('#10')
  })
})
