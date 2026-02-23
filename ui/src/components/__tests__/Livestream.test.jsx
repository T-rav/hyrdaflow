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
      { type: 'batch_start', timestamp: '2026-01-15T10:30:00Z', data: { batch: 3 } },
      { type: 'pr_created', timestamp: '2026-01-15T10:31:00Z', data: { pr: 42, issue: 10, draft: false } },
    ]
    render(<Livestream events={events} />)

    expect(screen.getByText('batch start')).toBeInTheDocument()
    expect(screen.getByText('Batch 3 started')).toBeInTheDocument()
    expect(screen.getByText('pr created')).toBeInTheDocument()
    expect(screen.getByText('PR #42 for #10')).toBeInTheDocument()
  })

  it('shows transcript_line events (no filter)', () => {
    const events = [
      { type: 'transcript_line', timestamp: '2026-01-15T10:30:00Z', data: { issue: 1 } },
      { type: 'error', timestamp: '2026-01-15T10:31:00Z', data: { message: 'something broke' } },
    ]
    render(<Livestream events={events} />)

    expect(screen.getByText('transcript line')).toBeInTheDocument()
    expect(screen.getByText('error')).toBeInTheDocument()
    expect(screen.getByText('something broke')).toBeInTheDocument()
  })

  it('applies typeSpanStyles for known event types', () => {
    const events = [
      { type: 'error', timestamp: '2026-01-15T10:30:00Z', data: { message: 'fail' } },
    ]
    const { container } = render(<Livestream events={events} />)

    const typeBadge = screen.getByText('error')
    expect(typeBadge.style.color).toBe(typeSpanStyles.error.color)
    expect(typeBadge.style.fontWeight).toBe(String(typeSpanStyles.error.fontWeight))
  })

  it('applies defaultTypeStyle for unknown event types', () => {
    const events = [
      { type: 'custom_event', timestamp: '2026-01-15T10:30:00Z', data: { foo: 'bar' } },
    ]
    render(<Livestream events={events} />)

    const typeBadge = screen.getByText('custom event')
    expect(typeBadge.style.color).toBe(defaultTypeStyle.color)
    expect(typeBadge.style.fontWeight).toBe(String(defaultTypeStyle.fontWeight))
  })

  it('renders timestamps via toLocaleTimeString', () => {
    const events = [
      { type: 'batch_start', timestamp: '2026-01-15T10:30:00Z', data: { batch: 1 } },
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
      { type: 'batch_complete', timestamp: '2026-01-15T10:34:00Z', data: { merged: 2, implemented: 3 } },
    ]
    render(<Livestream events={events} />)

    expect(screen.getByText('implement')).toBeInTheDocument()
    expect(screen.getByText('#5 → running')).toBeInTheDocument()
    expect(screen.getByText('PR #20 → approved')).toBeInTheDocument()
    expect(screen.getByText('PR #20 merged')).toBeInTheDocument()
    expect(screen.getByText('2 merged, 3 implemented')).toBeInTheDocument()
  })

  it('does not show resume button when auto-scroll is active (at top)', () => {
    const events = [
      { type: 'batch_start', timestamp: '2026-01-15T10:30:00Z', data: { batch: 1 } },
    ]
    render(<Livestream events={events} />)

    expect(screen.queryByText(/resume auto-scroll/)).not.toBeInTheDocument()
  })
})
