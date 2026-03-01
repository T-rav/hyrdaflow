import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { EpicWorkDetail } from '../EpicWorkDetail'

const baseIssue = {
  issue_number: 42,
  title: 'Fix widget',
  url: 'https://github.com/org/repo/issues/42',
  current_stage: 'implement',
  status: 'running',
  stage_entered_at: new Date(Date.now() - 30 * 60000).toISOString(),
  pr_number: 99,
  pr_url: 'https://github.com/org/repo/pull/99',
  pr_state: 'open',
  approval_state: 'pending',
  ci_status: 'passing',
  branch: 'agent/issue-42',
  worker: 'worker-1',
  transcript: ['> Running tests...', '> All tests passed', '> Committing changes'],
}

describe('EpicWorkDetail', () => {
  it('renders the detail panel with data-testid', () => {
    render(<EpicWorkDetail issue={baseIssue} />)
    expect(screen.getByTestId('work-detail-42')).toBeInTheDocument()
  })

  it('renders PR number as a link', () => {
    render(<EpicWorkDetail issue={baseIssue} />)
    const prLink = screen.getByText('#99')
    expect(prLink).toBeInTheDocument()
    expect(prLink.tagName).toBe('A')
    expect(prLink).toHaveAttribute('href', 'https://github.com/org/repo/pull/99')
  })

  it('renders PR state badge', () => {
    render(<EpicWorkDetail issue={baseIssue} />)
    expect(screen.getByText('open')).toBeInTheDocument()
  })

  it('renders merged PR state badge', () => {
    const issue = { ...baseIssue, pr_state: 'merged' }
    render(<EpicWorkDetail issue={issue} />)
    expect(screen.getByText('merged')).toBeInTheDocument()
  })

  it('renders CI status badge', () => {
    render(<EpicWorkDetail issue={baseIssue} />)
    expect(screen.getByText('passing')).toBeInTheDocument()
  })

  it('renders failing CI status', () => {
    const issue = { ...baseIssue, ci_status: 'failing' }
    render(<EpicWorkDetail issue={issue} />)
    expect(screen.getByText('failing')).toBeInTheDocument()
  })

  it('renders review verdict', () => {
    const issue = { ...baseIssue, approval_state: 'approved' }
    render(<EpicWorkDetail issue={issue} />)
    expect(screen.getByText('approved')).toBeInTheDocument()
  })

  it('renders changes_requested verdict', () => {
    const issue = { ...baseIssue, approval_state: 'changes_requested' }
    render(<EpicWorkDetail issue={issue} />)
    expect(screen.getByText('changes requested')).toBeInTheDocument()
  })

  it('renders branch name', () => {
    render(<EpicWorkDetail issue={baseIssue} />)
    expect(screen.getByText('agent/issue-42')).toBeInTheDocument()
  })

  it('renders worker name', () => {
    render(<EpicWorkDetail issue={baseIssue} />)
    expect(screen.getByText('worker-1')).toBeInTheDocument()
  })

  it('renders time in stage', () => {
    render(<EpicWorkDetail issue={baseIssue} />)
    expect(screen.getByText('30m')).toBeInTheDocument()
  })

  it('renders transcript preview', () => {
    render(<EpicWorkDetail issue={baseIssue} />)
    expect(screen.getByTestId('transcript-preview')).toBeInTheDocument()
  })

  it('renders View PR action button', () => {
    render(<EpicWorkDetail issue={baseIssue} />)
    const btn = screen.getByText('View PR ↗')
    expect(btn).toBeInTheDocument()
    expect(btn).toHaveAttribute('href', 'https://github.com/org/repo/pull/99')
  })

  it('renders View Issue action button', () => {
    render(<EpicWorkDetail issue={baseIssue} />)
    const btn = screen.getByText('View Issue ↗')
    expect(btn).toBeInTheDocument()
    expect(btn).toHaveAttribute('href', 'https://github.com/org/repo/issues/42')
  })

  it('renders Request Changes button when callback provided', () => {
    const fn = vi.fn()
    render(<EpicWorkDetail issue={baseIssue} onRequestChanges={fn} />)
    const btn = screen.getByTestId('request-changes-42')
    expect(btn).toBeInTheDocument()
    fireEvent.click(btn)
    expect(fn).toHaveBeenCalledWith(42)
  })

  it('does not render Request Changes button without callback', () => {
    render(<EpicWorkDetail issue={baseIssue} />)
    expect(screen.queryByTestId('request-changes-42')).not.toBeInTheDocument()
  })

  it('handles missing PR gracefully', () => {
    const issue = { ...baseIssue, pr_number: null, pr_url: null }
    render(<EpicWorkDetail issue={issue} />)
    expect(screen.queryByText('#99')).not.toBeInTheDocument()
    expect(screen.queryByText('View PR ↗')).not.toBeInTheDocument()
  })

  it('handles empty transcript', () => {
    const issue = { ...baseIssue, transcript: [] }
    render(<EpicWorkDetail issue={issue} />)
    expect(screen.queryByTestId('transcript-preview')).not.toBeInTheDocument()
  })

  it('handles missing stage_entered_at', () => {
    const issue = { ...baseIssue, stage_entered_at: null }
    render(<EpicWorkDetail issue={issue} />)
    expect(screen.getByTestId('work-detail-42')).toBeInTheDocument()
  })
})
