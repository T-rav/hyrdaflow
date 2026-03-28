import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

// Mock useReportPoller so we control its return values
const mockPoller = {
  reports: [],
  loading: false,
  error: null,
  refresh: vi.fn(),
  submitReport: vi.fn(),
  updateReport: vi.fn(),
}

vi.mock('../../hooks/useReportPoller', () => ({
  useReportPoller: () => mockPoller,
}))

const { BugReportPanel } = await import('../BugReportPanel')

function makeReport(overrides = {}) {
  return {
    id: 'r1',
    reporter_id: 'user-1',
    description: 'Test bug report',
    status: 'queued',
    linked_issue_url: '',
    linked_pr_url: '',
    progress_summary: '',
    created_at: '2026-03-28T00:00:00Z',
    updated_at: '2026-03-28T00:00:00Z',
    history: [],
    ...overrides,
  }
}

describe('BugReportPanel', () => {
  let onOpenReportModal

  beforeEach(() => {
    onOpenReportModal = vi.fn()
    mockPoller.reports = []
    mockPoller.loading = false
    mockPoller.error = null
    mockPoller.refresh.mockClear()
    mockPoller.submitReport.mockClear()
    mockPoller.updateReport.mockClear()
  })

  it('renders table headers when reports exist', () => {
    mockPoller.reports = [makeReport()]
    render(<BugReportPanel apiBaseUrl="" reporterId="u1" onOpenReportModal={onOpenReportModal} />)
    expect(screen.getByText('Status')).toBeTruthy()
    expect(screen.getByText('Description')).toBeTruthy()
    expect(screen.getByText('Created')).toBeTruthy()
    expect(screen.getByText('Issue')).toBeTruthy()
  })

  it('shows empty state when no reports', () => {
    render(<BugReportPanel apiBaseUrl="" reporterId="u1" onOpenReportModal={onOpenReportModal} />)
    expect(screen.getByTestId('report-panel-empty')).toBeTruthy()
  })

  it('renders report rows', () => {
    mockPoller.reports = [
      makeReport({ id: 'r1', description: 'First bug', status: 'queued' }),
      makeReport({ id: 'r2', description: 'Second bug', status: 'filed' }),
    ]
    render(<BugReportPanel apiBaseUrl="" reporterId="u1" onOpenReportModal={onOpenReportModal} />)
    expect(screen.getByText('First bug')).toBeTruthy()
    expect(screen.getByText('Second bug')).toBeTruthy()
  })

  it('status filter pills show counts and filter the table', () => {
    mockPoller.reports = [
      makeReport({ id: 'r1', status: 'queued' }),
      makeReport({ id: 'r2', status: 'queued' }),
      makeReport({ id: 'r3', status: 'filed', description: 'Filed bug' }),
    ]
    render(<BugReportPanel apiBaseUrl="" reporterId="u1" onOpenReportModal={onOpenReportModal} />)

    // All pill should show all 3
    const allPill = screen.getByTestId('filter-all')
    expect(allPill.textContent).toContain('3')

    // Click Filed filter
    const filedPill = screen.getByTestId('filter-filed')
    fireEvent.click(filedPill)

    // Only filed report visible
    expect(screen.getByText('Filed bug')).toBeTruthy()
    expect(screen.queryByText('Test bug report')).toBeNull()
  })

  it('text search filters by description', () => {
    mockPoller.reports = [
      makeReport({ id: 'r1', description: 'Login page broken' }),
      makeReport({ id: 'r2', description: 'Dashboard widget crash' }),
    ]
    render(<BugReportPanel apiBaseUrl="" reporterId="u1" onOpenReportModal={onOpenReportModal} />)

    const searchInput = screen.getByTestId('report-search')
    fireEvent.change(searchInput, { target: { value: 'Login' } })

    expect(screen.getByText('Login page broken')).toBeTruthy()
    expect(screen.queryByText('Dashboard widget crash')).toBeNull()
  })

  it('expanding a row shows timeline and actions', () => {
    mockPoller.reports = [
      makeReport({
        id: 'r1',
        status: 'filed',
        history: [
          { timestamp: '2026-03-28T00:00:00Z', action: 'submitted', detail: '' },
          { timestamp: '2026-03-28T01:00:00Z', action: 'filed', detail: 'Issue #42' },
        ],
      }),
    ]
    render(<BugReportPanel apiBaseUrl="" reporterId="u1" onOpenReportModal={onOpenReportModal} />)

    // Click the expand button
    const expandBtn = screen.getByTestId('expand-r1')
    fireEvent.click(expandBtn)

    expect(screen.getByTestId('detail-r1')).toBeTruthy()
    expect(screen.getByText('submitted')).toBeTruthy()
    expect(screen.getByText('filed')).toBeTruthy()
  })

  it('cancel action calls updateReport', () => {
    mockPoller.reports = [makeReport({ id: 'r1', status: 'filed' })]
    render(<BugReportPanel apiBaseUrl="" reporterId="u1" onOpenReportModal={onOpenReportModal} />)

    fireEvent.click(screen.getByTestId('expand-r1'))
    fireEvent.click(screen.getByTestId('action-cancel-r1'))

    expect(mockPoller.updateReport).toHaveBeenCalledWith('r1', 'cancel', '')
  })

  it('Report Bug button calls onOpenReportModal', () => {
    render(<BugReportPanel apiBaseUrl="" reporterId="u1" onOpenReportModal={onOpenReportModal} />)
    fireEvent.click(screen.getByTestId('report-bug-btn'))
    expect(onOpenReportModal).toHaveBeenCalled()
  })

  it('shows linked issue URL when available', () => {
    mockPoller.reports = [
      makeReport({
        id: 'r1',
        status: 'filed',
        linked_issue_url: 'https://github.com/owner/repo/issues/42',
      }),
    ]
    render(<BugReportPanel apiBaseUrl="" reporterId="u1" onOpenReportModal={onOpenReportModal} />)
    expect(screen.getByText('#42')).toBeTruthy()
  })

  it('queued status hides Reopen input but shows Cancel', () => {
    mockPoller.reports = [makeReport({ id: 'r1', status: 'queued' })]
    render(<BugReportPanel apiBaseUrl="" reporterId="u1" onOpenReportModal={onOpenReportModal} />)
    fireEvent.click(screen.getByTestId('expand-r1'))
    expect(screen.getByTestId('action-cancel-r1')).toBeTruthy()
    expect(screen.queryByTestId('action-reopen-r1')).toBeNull()
    expect(screen.queryByTestId('action-confirm-r1')).toBeNull()
  })

  it('closed status hides all action buttons', () => {
    mockPoller.reports = [makeReport({ id: 'r1', status: 'closed' })]
    render(<BugReportPanel apiBaseUrl="" reporterId="u1" onOpenReportModal={onOpenReportModal} />)
    fireEvent.click(screen.getByTestId('expand-r1'))
    expect(screen.queryByTestId('action-cancel-r1')).toBeNull()
    expect(screen.queryByTestId('action-reopen-r1')).toBeNull()
    expect(screen.queryByTestId('action-confirm-r1')).toBeNull()
  })

  it('shows error bar when error is set', () => {
    mockPoller.error = 'Network error'
    mockPoller.reports = [makeReport()]
    render(<BugReportPanel apiBaseUrl="" reporterId="u1" onOpenReportModal={onOpenReportModal} />)
    expect(screen.getByText(/Network error/)).toBeTruthy()
  })

  it('shows loading state', () => {
    mockPoller.loading = true
    render(<BugReportPanel apiBaseUrl="" reporterId="u1" onOpenReportModal={onOpenReportModal} />)
    expect(screen.getByTestId('report-panel-loading')).toBeTruthy()
  })
})
