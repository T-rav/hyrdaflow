import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Livestream } from '../Livestream'
import { typeSpanStyles, defaultTypeStyle } from '../EventLog'

describe('Livestream component', () => {
  it('renders empty state when no events', () => {
    render(<Livestream events={[]} />)
    expect(screen.getByText('Waiting for events...')).toBeInTheDocument()
  })

  it('renders formatted events with timestamp, type badge, and summary', () => {
    const events = [
      { type: 'phase_change', timestamp: '2026-01-15T10:30:00Z', data: { phase: 'plan' } },
      { type: 'pr_created', timestamp: '2026-01-15T10:31:00Z', data: { pr: 42, issue: 10, draft: false } },
    ]
    render(<Livestream events={events} />)

    expect(screen.getByText('[orchestrator]')).toBeInTheDocument()
    expect(screen.getByText('issue: n/a line plan')).toBeInTheDocument()
    expect(screen.getByText('[implement]')).toBeInTheDocument()
    expect(screen.getByText('issue: 10 line PR #42 for #10')).toBeInTheDocument()
  })

  it('shows transcript_line events (no filter)', () => {
    const events = [
      { type: 'transcript_line', timestamp: '2026-01-15T10:30:00Z', data: { issue: 1 } },
      { type: 'error', timestamp: '2026-01-15T10:31:00Z', data: { message: 'something broke' } },
    ]
    render(<Livestream events={events} />)

    expect(screen.getByText('[agent]')).toBeInTheDocument()
    expect(screen.getByText('[system]')).toBeInTheDocument()
    expect(screen.getByText('issue: 1 line')).toBeInTheDocument()
    expect(screen.getByText('issue: n/a line something broke')).toBeInTheDocument()
  })

  it('applies typeSpanStyles for known event types', () => {
    const events = [
      { type: 'error', timestamp: '2026-01-15T10:30:00Z', data: { message: 'fail' } },
    ]
    const { container } = render(<Livestream events={events} />)

    const typeBadge = screen.getByText('[system]')
    expect(typeBadge.style.color).toBe(typeSpanStyles.error.color)
    expect(typeBadge.style.fontWeight).toBe(String(typeSpanStyles.error.fontWeight))
  })

  it('applies defaultTypeStyle for unknown event types', () => {
    const events = [
      { type: 'custom_event', timestamp: '2026-01-15T10:30:00Z', data: { foo: 'bar' } },
    ]
    render(<Livestream events={events} />)

    const typeBadge = screen.getByText('[unknown]')
    expect(typeBadge.style.color).toBe(defaultTypeStyle.color)
    expect(typeBadge.style.fontWeight).toBe(String(defaultTypeStyle.fontWeight))
  })

  it('renders timestamps via toLocaleTimeString', () => {
    const events = [
      { type: 'phase_change', timestamp: '2026-01-15T10:30:00Z', data: { phase: 'plan' } },
    ]
    const { container } = render(<Livestream events={events} />)

    // Verify a time string is rendered (format varies by locale)
    const expected = new Date('2026-01-15T10:30:00Z').toLocaleTimeString()
    expect(screen.getByText(expected)).toBeInTheDocument()
  })

  it('renders multiple event types correctly', () => {
    const events = [
      { type: 'phase_change', timestamp: '2026-01-15T10:30:00Z', data: { phase: 'implement' } },
      { type: 'worker_update', timestamp: '2026-01-15T10:31:00Z', data: { issue: 5, status: 'running' } },
      { type: 'review_update', timestamp: '2026-01-15T10:32:00Z', data: { pr: 20, verdict: 'approved' } },
      { type: 'merge_update', timestamp: '2026-01-15T10:33:00Z', data: { pr: 20, status: 'merged' } },
    ]
    render(<Livestream events={events} />)

    expect(screen.getByText('issue: n/a line implement')).toBeInTheDocument()
    expect(screen.getByText('issue: 5 line → running')).toBeInTheDocument()
    expect(screen.getByText('issue: n/a line PR #20 → approved')).toBeInTheDocument()
    expect(screen.getByText('issue: n/a line PR #20 merged')).toBeInTheDocument()
  })

  it('deduplicates issue numbers for hitl_escalation events', () => {
    const events = [
      { type: 'hitl_escalation', timestamp: '2026-01-15T10:34:00Z', data: { issue: 99, cause: 'Needs HITL review' } },
    ]
    render(<Livestream events={events} />)

    expect(screen.getByText('issue: 99 line escalated to HITL')).toBeInTheDocument()
  })

  it('does not show resume button when auto-scroll is active (at top)', () => {
    const events = [
      { type: 'phase_change', timestamp: '2026-01-15T10:30:00Z', data: { phase: 'plan' } },
    ]
    render(<Livestream events={events} />)

    expect(screen.queryByText(/resume auto-scroll/)).not.toBeInTheDocument()
  })
})
