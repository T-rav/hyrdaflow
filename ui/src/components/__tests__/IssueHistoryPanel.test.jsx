import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { IssueHistoryPanel } from '../IssueHistoryPanel'

function makePayload() {
  return {
    items: [
      {
        issue_number: 10,
        title: 'Fix auth cache',
        issue_url: 'https://example.com/issues/10',
        status: 'active',
        epic: 'epic:auth',
        linked_issues: [3, 4],
        prs: [{ number: 501, url: 'https://example.com/pull/501', merged: false }],
        session_ids: ['sess-1'],
        source_calls: { implementer: 2 },
        model_calls: { 'gpt-5': 2 },
        inference: { inference_calls: 2, total_tokens: 1200, input_tokens: 800, output_tokens: 400 },
        first_seen: '2026-02-20T00:00:00+00:00',
        last_seen: '2026-02-21T00:00:00+00:00',
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
        inference: { inference_calls: 1, total_tokens: 100, input_tokens: 70, output_tokens: 30 },
        first_seen: '2026-02-19T00:00:00+00:00',
        last_seen: '2026-02-22T00:00:00+00:00',
      },
    ],
    totals: { issues: 2, inference_calls: 3, total_tokens: 1300 },
  }
}

describe('IssueHistoryPanel', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => makePayload(),
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches and renders issue rows', async () => {
    render(<IssueHistoryPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())
    expect(screen.getByText('Merge docs')).toBeInTheDocument()
    expect(global.fetch).toHaveBeenCalledTimes(1)
    const [url] = global.fetch.mock.calls[0]
    expect(url).toContain('/api/issues/history?')
    expect(url).toContain('limit=500')
  })

  it('filters by status and search text client-side', async () => {
    render(<IssueHistoryPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'merged' } })
    expect(screen.queryByText('Fix auth cache')).not.toBeInTheDocument()
    expect(screen.getByText('Merge docs')).toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('Search issue #, title, epic'), { target: { value: 'auth' } })
    expect(screen.getByText('No issues match this filter.')).toBeInTheDocument()
  })

  it('expands an issue row to show rollup details', async () => {
    render(<IssueHistoryPanel />)
    await waitFor(() => expect(screen.getByText('Fix auth cache')).toBeInTheDocument())

    fireEvent.click(screen.getByLabelText('Toggle issue 10'))
    expect(screen.getByText('Linked Issues')).toBeInTheDocument()
    expect(screen.getByText('#3')).toBeInTheDocument()
    expect(screen.getByText('#4')).toBeInTheDocument()
    expect(screen.getByText(/2 calls/)).toBeInTheDocument()
  })
})
