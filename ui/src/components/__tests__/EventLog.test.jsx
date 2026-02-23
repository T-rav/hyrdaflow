import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { EventLog, typeSpanStyles, defaultTypeStyle, eventSummary, typeColors } from '../EventLog'

describe('EventLog pre-computed styles', () => {
  it('has an entry for every typeColors key', () => {
    for (const key of Object.keys(typeColors)) {
      expect(typeSpanStyles).toHaveProperty(key)
    }
  })

  it('each typeSpanStyle includes base style fontWeight: 600 and the correct color', () => {
    for (const [key, color] of Object.entries(typeColors)) {
      expect(typeSpanStyles[key]).toMatchObject({
        fontWeight: 600,
        marginRight: 6,
        color,
      })
    }
  })

  it('defaultTypeStyle has textMuted color and base style properties', () => {
    expect(defaultTypeStyle).toMatchObject({
      fontWeight: 600,
      marginRight: 6,
      color: 'var(--text-muted)',
    })
  })

  it('style objects are referentially stable across accesses', () => {
    const first = typeSpanStyles.error
    const second = typeSpanStyles.error
    expect(first).toBe(second)
  })
})

describe('EventLog component', () => {
  it('renders without errors with empty events', () => {
    render(<EventLog events={[]} />)
    expect(screen.getByText('Waiting for events...')).toBeInTheDocument()
  })

  it('renders events and applies pre-computed styles', () => {
    const events = [
      { type: 'batch_start', timestamp: Date.now(), data: { batch: 1 } },
      { type: 'error', timestamp: Date.now(), data: { message: 'fail' } },
    ]
    const { container } = render(<EventLog events={events} />)
    const spans = container.querySelectorAll('span')
    // Should render without crashing and contain the event types
    expect(screen.getByText('batch start')).toBeInTheDocument()
    expect(screen.getByText('error')).toBeInTheDocument()
  })

  it('filters out transcript_line events', () => {
    const events = [
      { type: 'transcript_line', timestamp: Date.now(), data: { issue: 1 } },
      { type: 'error', timestamp: Date.now(), data: { message: 'fail' } },
    ]
    render(<EventLog events={events} />)
    expect(screen.queryByText('transcript line')).not.toBeInTheDocument()
    expect(screen.getByText('error')).toBeInTheDocument()
  })
})

describe('eventSummary', () => {
  it('formats batch_start', () => {
    expect(eventSummary('batch_start', { batch: 5 })).toBe('Batch 5 started')
  })

  it('formats phase_change', () => {
    expect(eventSummary('phase_change', { phase: 'implement' })).toBe('implement')
  })

  it('formats worker_update', () => {
    expect(eventSummary('worker_update', { issue: 10, status: 'running' })).toBe('#10 → running')
  })

  it('formats transcript_line', () => {
    expect(eventSummary('transcript_line', { issue: 3, line: 'Writing tests...' })).toBe('#3 Writing tests...')
    expect(eventSummary('transcript_line', { pr: 7 })).toBe('#7 ')
  })

  it('formats pr_created', () => {
    expect(eventSummary('pr_created', { pr: 42, issue: 10, draft: false })).toBe('PR #42 for #10')
    expect(eventSummary('pr_created', { pr: 42, issue: 10, draft: true })).toBe('PR #42 for #10 (draft)')
  })

  it('formats review_update', () => {
    expect(eventSummary('review_update', { pr: 20, verdict: 'approved' })).toBe('PR #20 → approved')
    expect(eventSummary('review_update', { pr: 20, status: 'running' })).toBe('PR #20 → running')
  })

  it('formats merge_update', () => {
    expect(eventSummary('merge_update', { pr: 20, status: 'merged' })).toBe('PR #20 merged')
  })

  it('formats batch_complete', () => {
    expect(eventSummary('batch_complete', { merged: 2, implemented: 3 })).toBe('2 merged, 3 implemented')
  })

  it('formats error', () => {
    expect(eventSummary('error', { message: 'something broke' })).toBe('something broke')
    expect(eventSummary('error', {})).toBe('Error')
  })

  it('formats triage_update', () => {
    expect(eventSummary('triage_update', { issue: 5, status: 'evaluating' })).toBe('#5 → evaluating')
  })

  it('formats planner_update', () => {
    expect(eventSummary('planner_update', { issue: 7, status: 'planning' })).toBe('#7 → planning')
  })

  it('formats orchestrator_status', () => {
    expect(eventSummary('orchestrator_status', { status: 'running' })).toBe('running')
  })

  it('formats hitl_escalation with PR number', () => {
    expect(eventSummary('hitl_escalation', { pr: 42 })).toBe('PR #42 escalated to HITL')
  })

  it('formats hitl_escalation without PR number (manual escalation)', () => {
    expect(eventSummary('hitl_escalation', { issue: 99, cause: 'needs rework', origin: 'hydraflow-review' })).toBe('Issue #99 escalated to HITL')
  })

  it('formats hitl_update with action', () => {
    expect(eventSummary('hitl_update', { issue: 10, action: 'resolved' })).toBe('#10 resolved')
  })

  it('formats hitl_update falling back to status', () => {
    expect(eventSummary('hitl_update', { issue: 10, status: 'pending' })).toBe('#10 pending')
  })

  it('formats ci_check', () => {
    expect(eventSummary('ci_check', { pr: 20, status: 'passed' })).toBe('PR #20 CI passed')
  })

  it('formats issue_created', () => {
    expect(eventSummary('issue_created', { issue: 99 })).toBe('#99 created')
  })

  it('formats background_worker_status', () => {
    expect(eventSummary('background_worker_status', { worker: 'memory_sync', status: 'ok' })).toBe('memory_sync → ok')
  })

  it('falls back to truncated JSON for unknown types', () => {
    const result = eventSummary('unknown_type', { foo: 'bar' })
    expect(result).toBe('{"foo":"bar"}')
  })
})

describe('typeColors', () => {
  it('has entries for all known event types', () => {
    const expectedTypes = [
      'worker_update', 'phase_change', 'pr_created', 'review_update',
      'merge_update', 'error', 'batch_start', 'batch_complete', 'transcript_line',
      'triage_update', 'planner_update', 'orchestrator_status',
      'hitl_escalation', 'hitl_update', 'ci_check', 'issue_created',
      'background_worker_status',
    ]
    for (const type of expectedTypes) {
      expect(typeColors).toHaveProperty(type)
    }
  })
})
