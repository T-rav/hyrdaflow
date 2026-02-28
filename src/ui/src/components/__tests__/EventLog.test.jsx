import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { EventLog, processLabel, typeSpanStyles, defaultTypeStyle, eventSummary, eventMessage, typeColors } from '../EventLog'

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

  it('renders events with bracketed process labels', () => {
    const events = [
      { type: 'phase_change', timestamp: Date.now(), data: { phase: 'plan' } },
      { type: 'error', timestamp: Date.now(), data: { message: 'fail' } },
    ]
    render(<EventLog events={events} />)
    expect(screen.getByText('[orchestrator]')).toBeInTheDocument()
    expect(screen.getByText('[system]')).toBeInTheDocument()
  })

  it('filters out transcript_line events', () => {
    const events = [
      { type: 'transcript_line', timestamp: Date.now(), data: { issue: 1 } },
      { type: 'error', timestamp: Date.now(), data: { message: 'fail' } },
    ]
    render(<EventLog events={events} />)
    expect(screen.queryByText('[agent]')).not.toBeInTheDocument()
    expect(screen.getByText('[system]')).toBeInTheDocument()
  })
})

describe('eventSummary', () => {
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

  it('formats hitl_update with awaiting_retry when no action or status', () => {
    expect(eventSummary('hitl_update', { issue: 10 })).toBe('#10 awaiting_retry')
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

describe('eventMessage', () => {
  it('returns phase_change text as-is', () => {
    expect(eventMessage('phase_change', { phase: 'implement' })).toBe('implement')
  })

  it('drops issue prefix for worker_update', () => {
    expect(eventMessage('worker_update', { issue: 10, status: 'running' })).toBe('→ running')
  })

  it('returns transcript lines without issue prefix', () => {
    expect(eventMessage('transcript_line', { issue: 3, line: 'Writing tests...' })).toBe('Writing tests...')
    expect(eventMessage('transcript_line', { pr: 7 })).toBe('')
  })

  it('keeps pr_created contextual text', () => {
    expect(eventMessage('pr_created', { pr: 42, issue: 10, draft: false })).toBe('PR #42 for #10')
    expect(eventMessage('pr_created', { pr: 42, issue: 10, draft: true })).toBe('PR #42 for #10 (draft)')
  })

  it('keeps review_update text', () => {
    expect(eventMessage('review_update', { pr: 20, verdict: 'approved' })).toBe('PR #20 → approved')
    expect(eventMessage('review_update', { pr: 20, status: 'running' })).toBe('PR #20 → running')
  })

  it('keeps merge_update text', () => {
    expect(eventMessage('merge_update', { pr: 20, status: 'merged' })).toBe('PR #20 merged')
  })

  it('passes through error message', () => {
    expect(eventMessage('error', { message: 'something broke' })).toBe('something broke')
    expect(eventMessage('error', {})).toBe('Error')
  })

  it('drops issue prefix for triage updates', () => {
    expect(eventMessage('triage_update', { issue: 5, status: 'evaluating' })).toBe('→ evaluating')
  })

  it('drops issue prefix for planner updates', () => {
    expect(eventMessage('planner_update', { issue: 7, status: 'planning' })).toBe('→ planning')
  })

  it('keeps orchestrator status text', () => {
    expect(eventMessage('orchestrator_status', { status: 'running' })).toBe('running')
  })

  it('leaves pr-scoped hitl_escalation untouched; strips issue prefix from issue-scoped hitl_escalation', () => {
    expect(eventMessage('hitl_escalation', { pr: 42 })).toBe('PR #42 escalated to HITL')
    expect(eventMessage('hitl_escalation', { issue: 99 })).toBe('escalated to HITL')
    // both pr and issue set: pr takes priority in eventSummary so no issue prefix to strip
    expect(eventMessage('hitl_escalation', { pr: 42, issue: 99 })).toBe('PR #42 escalated to HITL')
  })

  it('drops issue prefix for hitl_update', () => {
    expect(eventMessage('hitl_update', { issue: 10, action: 'resolved' })).toBe('resolved')
    expect(eventMessage('hitl_update', { issue: 10, status: 'pending' })).toBe('pending')
  })

  it('keeps ci_check text', () => {
    expect(eventMessage('ci_check', { pr: 20, status: 'passed' })).toBe('PR #20 CI passed')
  })

  it('drops issue prefix for issue_created', () => {
    expect(eventMessage('issue_created', { issue: 99 })).toBe('created')
  })

  it('keeps background_worker_status text', () => {
    expect(eventMessage('background_worker_status', { worker: 'memory_sync', status: 'ok' })).toBe('memory_sync → ok')
  })

  it('falls back to truncated JSON for unknown types', () => {
    const result = eventMessage('unknown_type', { foo: 'bar' })
    expect(result).toBe('{"foo":"bar"}')
  })
})

describe('processLabel', () => {
  it('returns bracketed process name for known event types', () => {
    expect(processLabel('worker_update')).toBe('[implement]')
    expect(processLabel('triage_update')).toBe('[triage]')
    expect(processLabel('planner_update')).toBe('[plan]')
    expect(processLabel('review_update')).toBe('[review]')
    expect(processLabel('error')).toBe('[system]')
    expect(processLabel('hitl_escalation')).toBe('[hitl]')
    expect(processLabel('ci_check')).toBe('[ci]')
    expect(processLabel('background_worker_status')).toBe('[bg_worker]')
    expect(processLabel('orchestrator_status')).toBe('[orchestrator]')
  })

  it('returns [unknown] for unmapped event types', () => {
    expect(processLabel('some_future_event')).toBe('[unknown]')
  })

  it('covers all typeColors keys', () => {
    for (const key of Object.keys(typeColors)) {
      const label = processLabel(key)
      expect(label).toMatch(/^\[.+\]$/)
      expect(label).not.toBe('[unknown]')
    }
  })
})

describe('typeColors', () => {
  it('has entries for all known event types', () => {
    const expectedTypes = [
      'worker_update', 'phase_change', 'pr_created', 'review_update',
      'merge_update', 'error', 'transcript_line',
      'triage_update', 'planner_update', 'orchestrator_status',
      'hitl_escalation', 'hitl_update', 'ci_check', 'issue_created',
      'background_worker_status',
    ]
    for (const type of expectedTypes) {
      expect(typeColors).toHaveProperty(type)
    }
  })
})
