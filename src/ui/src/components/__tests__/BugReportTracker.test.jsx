import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { BugReportTracker } from '../BugReportTracker'

function makeReport(overrides = {}) {
  return {
    id: 'r1',
    reporter_id: 'user-1',
    description: 'Test bug report',
    status: 'queued',
    linked_issue_url: '',
    linked_pr_url: '',
    progress_summary: '',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    history: [],
    ...overrides,
  }
}

describe('BugReportTracker', () => {
  let onClose
  let onAction

  beforeEach(() => {
    onClose = vi.fn()
    onAction = vi.fn()
  })

  it('renders nothing when not open', () => {
    const { container } = render(
      <BugReportTracker isOpen={false} onClose={onClose} reports={[]} onAction={onAction} />
    )
    expect(container.innerHTML).toBe('')
  })

  it('shows empty state when no reports', () => {
    render(
      <BugReportTracker isOpen={true} onClose={onClose} reports={[]} onAction={onAction} />
    )
    expect(screen.getByTestId('tracker-empty')).toBeTruthy()
    expect(screen.getByText('No bug reports submitted yet.')).toBeTruthy()
  })

  it('renders report cards with status and description', () => {
    const reports = [
      makeReport({ id: 'r1', description: 'First bug', status: 'queued' }),
      makeReport({ id: 'r2', description: 'Second bug', status: 'fixed' }),
    ]
    render(
      <BugReportTracker isOpen={true} onClose={onClose} reports={reports} onAction={onAction} />
    )
    expect(screen.getByTestId('tracker-report-r1')).toBeTruthy()
    expect(screen.getByTestId('tracker-report-r2')).toBeTruthy()
    expect(screen.getByText('First bug')).toBeTruthy()
    expect(screen.getByText('Second bug')).toBeTruthy()
    expect(screen.getByTestId('tracker-status-r1').textContent).toBe('Queued')
    expect(screen.getByTestId('tracker-status-r2').textContent).toBe('Fixed')
  })

  it('closes when overlay is clicked', () => {
    render(
      <BugReportTracker isOpen={true} onClose={onClose} reports={[]} onAction={onAction} />
    )
    fireEvent.click(screen.getByTestId('tracker-overlay'))
    expect(onClose).toHaveBeenCalled()
  })

  it('closes when close button is clicked', () => {
    render(
      <BugReportTracker isOpen={true} onClose={onClose} reports={[]} onAction={onAction} />
    )
    fireEvent.click(screen.getByTestId('tracker-close'))
    expect(onClose).toHaveBeenCalled()
  })

  it('expands report on click to show actions', () => {
    const reports = [makeReport({ id: 'r1', status: 'in-progress' })]
    render(
      <BugReportTracker isOpen={true} onClose={onClose} reports={reports} onAction={onAction} />
    )
    // Click to expand
    fireEvent.click(screen.getByText('Test bug report'))
    expect(screen.getByTestId('tracker-expanded-r1')).toBeTruthy()
    expect(screen.getByTestId('tracker-actions-r1')).toBeTruthy()
  })

  it('shows confirm fixed button for in-progress reports', () => {
    const reports = [makeReport({ id: 'r1', status: 'in-progress' })]
    render(
      <BugReportTracker isOpen={true} onClose={onClose} reports={reports} onAction={onAction} />
    )
    fireEvent.click(screen.getByText('Test bug report'))
    const confirmBtn = screen.getByTestId('tracker-confirm-r1')
    expect(confirmBtn).toBeTruthy()
    fireEvent.click(confirmBtn)
    expect(onAction).toHaveBeenCalledWith('r1', 'confirm_fixed', '')
  })

  it('shows cancel button and triggers cancel action', () => {
    const reports = [makeReport({ id: 'r1', status: 'queued' })]
    render(
      <BugReportTracker isOpen={true} onClose={onClose} reports={reports} onAction={onAction} />
    )
    fireEvent.click(screen.getByText('Test bug report'))
    const cancelBtn = screen.getByTestId('tracker-cancel-r1')
    fireEvent.click(cancelBtn)
    expect(onAction).toHaveBeenCalledWith('r1', 'cancel', '')
  })

  it('shows reopen input and button for non-queued reports', () => {
    const reports = [makeReport({ id: 'r1', status: 'fixed' })]
    render(
      <BugReportTracker isOpen={true} onClose={onClose} reports={reports} onAction={onAction} />
    )
    fireEvent.click(screen.getByText('Test bug report'))
    const input = screen.getByTestId('tracker-reopen-input-r1')
    fireEvent.change(input, { target: { value: 'More details' } })
    fireEvent.click(screen.getByTestId('tracker-reopen-r1'))
    expect(onAction).toHaveBeenCalledWith('r1', 'reopen', 'More details')
  })

  it('hides actions for closed reports', () => {
    const reports = [makeReport({ id: 'r1', status: 'closed' })]
    render(
      <BugReportTracker isOpen={true} onClose={onClose} reports={reports} onAction={onAction} />
    )
    fireEvent.click(screen.getByText('Test bug report'))
    expect(screen.queryByTestId('tracker-actions-r1')).toBeNull()
  })

  it('shows history timeline when expanded', () => {
    const reports = [
      makeReport({
        id: 'r1',
        status: 'in-progress',
        history: [
          { timestamp: '2026-01-01T00:00:00Z', action: 'submitted', detail: 'Submitted' },
          { timestamp: '2026-01-02T00:00:00Z', action: 'processing', detail: 'Working on it' },
        ],
      }),
    ]
    render(
      <BugReportTracker isOpen={true} onClose={onClose} reports={reports} onAction={onAction} />
    )
    fireEvent.click(screen.getByText('Test bug report'))
    expect(screen.getByTestId('tracker-history-r1')).toBeTruthy()
    expect(screen.getByText('submitted')).toBeTruthy()
    expect(screen.getByText('processing')).toBeTruthy()
  })

  it('shows progress summary when available', () => {
    const reports = [
      makeReport({ id: 'r1', progress_summary: 'PR #42 created' }),
    ]
    render(
      <BugReportTracker isOpen={true} onClose={onClose} reports={reports} onAction={onAction} />
    )
    fireEvent.click(screen.getByText('Test bug report'))
    expect(screen.getByText('PR #42 created')).toBeTruthy()
  })

  it('shows linked issue and PR URLs when available', () => {
    const reports = [
      makeReport({
        id: 'r1',
        linked_issue_url: 'https://github.com/owner/repo/issues/1',
        linked_pr_url: 'https://github.com/owner/repo/pull/2',
      }),
    ]
    render(
      <BugReportTracker isOpen={true} onClose={onClose} reports={reports} onAction={onAction} />
    )
    fireEvent.click(screen.getByText('Test bug report'))
    expect(screen.getByText('https://github.com/owner/repo/issues/1')).toBeTruthy()
    expect(screen.getByText('https://github.com/owner/repo/pull/2')).toBeTruthy()
  })

  it('collapses report when clicked again', () => {
    const reports = [makeReport({ id: 'r1' })]
    render(
      <BugReportTracker isOpen={true} onClose={onClose} reports={reports} onAction={onAction} />
    )
    fireEvent.click(screen.getByText('Test bug report'))
    expect(screen.getByTestId('tracker-expanded-r1')).toBeTruthy()
    // Click again to collapse
    fireEvent.click(screen.getByText('Test bug report'))
    expect(screen.queryByTestId('tracker-expanded-r1')).toBeNull()
  })
})
