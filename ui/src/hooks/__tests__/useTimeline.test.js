import { describe, it, expect } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import {
  deriveIssueTimelines,
  applyFiltersAndSort,
  formatDuration,
  useTimeline,
  STAGE_KEYS,
  STAGE_META,
} from '../useTimeline'

// ── Constants ────────────────────────────────────────────────────────

describe('STAGE_KEYS', () => {
  it('contains all five pipeline stages in order', () => {
    expect(STAGE_KEYS).toEqual(['triage', 'plan', 'implement', 'review', 'merged'])
  })
})

describe('STAGE_META', () => {
  it('has color and label for each stage', () => {
    for (const key of STAGE_KEYS) {
      expect(STAGE_META[key]).toHaveProperty('color')
      expect(STAGE_META[key]).toHaveProperty('label')
      expect(STAGE_META[key]).toHaveProperty('subtleColor')
    }
  })
})

// ── formatDuration ───────────────────────────────────────────────────

describe('formatDuration', () => {
  it('returns empty string for null/negative', () => {
    expect(formatDuration(null)).toBe('')
    expect(formatDuration(-1)).toBe('')
  })

  it('returns "< 1s" for very short durations', () => {
    expect(formatDuration(0)).toBe('< 1s')
    expect(formatDuration(500)).toBe('< 1s')
  })

  it('formats seconds', () => {
    expect(formatDuration(5000)).toBe('5s')
    expect(formatDuration(59000)).toBe('59s')
  })

  it('formats minutes and seconds', () => {
    expect(formatDuration(90000)).toBe('1m 30s')
    expect(formatDuration(120000)).toBe('2m')
  })

  it('formats hours and minutes', () => {
    expect(formatDuration(3600000)).toBe('1h')
    expect(formatDuration(3660000)).toBe('1h 1m')
    expect(formatDuration(7200000)).toBe('2h')
  })
})

// ── deriveIssueTimelines ─────────────────────────────────────────────

describe('deriveIssueTimelines', () => {
  it('returns empty array when no events and no workers', () => {
    expect(deriveIssueTimelines([], {}, [])).toEqual([])
  })

  it('creates an issue entry from a triage_update event', () => {
    const events = [
      { type: 'triage_update', timestamp: '2026-01-15T10:00:00Z', data: { issue: 42, status: 'running' } },
    ]
    const result = deriveIssueTimelines(events, {}, [])

    expect(result).toHaveLength(1)
    expect(result[0].issueNumber).toBe(42)
    expect(result[0].stages.triage.status).toBe('active')
    expect(result[0].stages.triage.startTime).toBe('2026-01-15T10:00:00Z')
    expect(result[0].currentStage).toBe('triage')
  })

  it('creates an issue entry from a planner_update event', () => {
    const events = [
      { type: 'planner_update', timestamp: '2026-01-15T10:01:00Z', data: { issue: 10, status: 'planning' } },
    ]
    const result = deriveIssueTimelines(events, {}, [])

    expect(result).toHaveLength(1)
    expect(result[0].stages.plan.status).toBe('active')
    expect(result[0].currentStage).toBe('plan')
  })

  it('creates an issue entry from a worker_update event', () => {
    const events = [
      { type: 'worker_update', timestamp: '2026-01-15T10:02:00Z', data: { issue: 5, status: 'running' } },
    ]
    const result = deriveIssueTimelines(events, {}, [])

    expect(result).toHaveLength(1)
    expect(result[0].stages.implement.status).toBe('active')
    expect(result[0].currentStage).toBe('implement')
  })

  it('creates an issue entry from a review_update event', () => {
    const events = [
      { type: 'review_update', timestamp: '2026-01-15T10:03:00Z', data: { issue: 5, pr: 20, status: 'reviewing' } },
    ]
    const result = deriveIssueTimelines(events, {}, [])

    expect(result).toHaveLength(1)
    expect(result[0].stages.review.status).toBe('active')
    expect(result[0].currentStage).toBe('review')
  })

  it('marks merged stage from merge_update with status=merged', () => {
    const events = [
      { type: 'worker_update', timestamp: '2026-01-15T10:00:00Z', data: { issue: 7, status: 'done' } },
      { type: 'merge_update', timestamp: '2026-01-15T10:05:00Z', data: { issue: 7, pr: 30, status: 'merged' } },
    ]
    const result = deriveIssueTimelines(events, {}, [])

    expect(result).toHaveLength(1)
    expect(result[0].stages.merged.status).toBe('done')
    expect(result[0].overallStatus).toBe('done')
  })

  it('groups multiple stages for the same issue', () => {
    const events = [
      // Newest first (as from useHydraFlowSocket)
      { type: 'worker_update', timestamp: '2026-01-15T10:03:00Z', data: { issue: 42, status: 'running' } },
      { type: 'planner_update', timestamp: '2026-01-15T10:02:00Z', data: { issue: 42, status: 'done' } },
      { type: 'triage_update', timestamp: '2026-01-15T10:01:00Z', data: { issue: 42, status: 'done' } },
    ]
    const result = deriveIssueTimelines(events, {}, [])

    expect(result).toHaveLength(1)
    expect(result[0].stages.triage.status).toBe('done')
    expect(result[0].stages.plan.status).toBe('done')
    expect(result[0].stages.implement.status).toBe('active')
    expect(result[0].currentStage).toBe('implement')
  })

  it('tracks separate issues', () => {
    const events = [
      { type: 'triage_update', timestamp: '2026-01-15T10:00:00Z', data: { issue: 1, status: 'running' } },
      { type: 'triage_update', timestamp: '2026-01-15T10:01:00Z', data: { issue: 2, status: 'running' } },
    ]
    const result = deriveIssueTimelines(events, {}, [])

    expect(result).toHaveLength(2)
    const issueNums = result.map(r => r.issueNumber).sort()
    expect(issueNums).toEqual([1, 2])
  })

  it('sets failed status from event data', () => {
    const events = [
      { type: 'worker_update', timestamp: '2026-01-15T10:00:00Z', data: { issue: 3, status: 'failed' } },
    ]
    const result = deriveIssueTimelines(events, {}, [])

    expect(result[0].stages.implement.status).toBe('failed')
    expect(result[0].overallStatus).toBe('failed')
  })

  it('sets hitl status from escalated event', () => {
    const events = [
      { type: 'review_update', timestamp: '2026-01-15T10:00:00Z', data: { issue: 3, pr: 10, status: 'escalated' } },
    ]
    const result = deriveIssueTimelines(events, {}, [])

    expect(result[0].stages.review.status).toBe('hitl')
    expect(result[0].overallStatus).toBe('hitl')
  })

  it('attaches PR info from pr_created event', () => {
    const events = [
      { type: 'pr_created', timestamp: '2026-01-15T10:00:00Z', data: { issue: 5, pr: 25, url: 'https://github.com/pr/25' } },
    ]
    const result = deriveIssueTimelines(events, {}, [])

    expect(result[0].pr).toEqual({ number: 25, url: 'https://github.com/pr/25' })
  })

  it('routes transcript_line events to correct stage', () => {
    const events = [
      { type: 'triage_update', timestamp: '2026-01-15T10:00:00Z', data: { issue: 5, status: 'running' } },
      { type: 'transcript_line', timestamp: '2026-01-15T10:01:00Z', data: { issue: 5, source: 'triage', line: 'Analyzing issue...' } },
      { type: 'transcript_line', timestamp: '2026-01-15T10:02:00Z', data: { issue: 5, source: 'planner', line: 'Creating plan...' } },
    ]
    const result = deriveIssueTimelines(events, {}, [])

    expect(result[0].stages.triage.transcript).toContain('Analyzing issue...')
    expect(result[0].stages.plan.transcript).toContain('Creating plan...')
  })

  it('limits transcript lines to 10 per stage', () => {
    const events = [
      { type: 'triage_update', timestamp: '2026-01-15T10:00:00Z', data: { issue: 5, status: 'running' } },
    ]
    for (let i = 0; i < 15; i++) {
      events.push({
        type: 'transcript_line',
        timestamp: `2026-01-15T10:0${String(i).padStart(2, '0')}:00Z`,
        data: { issue: 5, source: 'triage', line: `Line ${i}` },
      })
    }
    const result = deriveIssueTimelines(events, {}, [])
    expect(result[0].stages.triage.transcript).toHaveLength(10)
  })

  it('augments from workers state for real-time status', () => {
    const workers = {
      'triage-8': { status: 'running', role: 'triage', title: 'Triage Issue #8', branch: '', transcript: [], pr: null },
    }
    const result = deriveIssueTimelines([], workers, [])

    expect(result).toHaveLength(1)
    expect(result[0].issueNumber).toBe(8)
    expect(result[0].stages.triage.status).toBe('active')
  })

  it('augments from plan workers', () => {
    const workers = {
      'plan-12': { status: 'done', role: 'planner', title: 'Plan Issue #12', branch: '', transcript: [], pr: null },
    }
    const result = deriveIssueTimelines([], workers, [])

    expect(result[0].stages.plan.status).toBe('done')
  })

  it('augments from implement workers (numeric key)', () => {
    const workers = {
      42: { status: 'running', role: 'implementer', title: 'Issue #42', branch: 'agent/issue-42', transcript: ['line1'], pr: null },
    }
    const result = deriveIssueTimelines([], workers, [])

    expect(result[0].issueNumber).toBe(42)
    expect(result[0].stages.implement.status).toBe('active')
    expect(result[0].stages.implement.transcript).toEqual(['line1'])
    expect(result[0].branch).toBe('agent/issue-42')
  })

  it('augments from review workers (keyed by PR, extracts issue from title)', () => {
    const workers = {
      'review-50': { status: 'reviewing', role: 'reviewer', title: 'PR #50 (Issue #15)', branch: '', transcript: [], pr: 50 },
    }
    const result = deriveIssueTimelines([], workers, [])

    expect(result[0].issueNumber).toBe(15)
    expect(result[0].stages.review.status).toBe('active')
    expect(result[0].pr).toEqual({ number: 50, url: null })
  })

  it('marks issue as done when PR is merged via prs array', () => {
    const events = [
      { type: 'worker_update', timestamp: '2026-01-15T10:00:00Z', data: { issue: 7, status: 'done' } },
    ]
    const prs = [{ pr: 30, issue: 7, merged: true }]
    const result = deriveIssueTimelines(events, {}, prs)

    expect(result[0].stages.merged.status).toBe('done')
    expect(result[0].overallStatus).toBe('done')
  })

  it('computes startTime from earliest event', () => {
    const events = [
      { type: 'worker_update', timestamp: '2026-01-15T10:05:00Z', data: { issue: 1, status: 'running' } },
      { type: 'triage_update', timestamp: '2026-01-15T10:00:00Z', data: { issue: 1, status: 'done' } },
    ]
    const result = deriveIssueTimelines(events, {}, [])

    expect(result[0].startTime).toBe('2026-01-15T10:00:00Z')
  })

  it('sets stage endTime when stage completes', () => {
    const events = [
      { type: 'triage_update', timestamp: '2026-01-15T10:01:00Z', data: { issue: 1, status: 'done' } },
      { type: 'triage_update', timestamp: '2026-01-15T10:00:00Z', data: { issue: 1, status: 'running' } },
    ]
    const result = deriveIssueTimelines(events, {}, [])

    expect(result[0].stages.triage.endTime).toBe('2026-01-15T10:01:00Z')
  })

  it('ignores events with no issue number', () => {
    const events = [
      { type: 'phase_change', timestamp: '2026-01-15T10:00:00Z', data: { phase: 'plan' } },
    ]
    const result = deriveIssueTimelines(events, {}, [])
    expect(result).toHaveLength(0)
  })

  it('uses worker title as issue title when available', () => {
    const workers = {
      42: { status: 'running', role: 'implementer', title: 'Add dark mode toggle', branch: 'agent/issue-42', transcript: [], pr: null },
    }
    const result = deriveIssueTimelines([], workers, [])
    expect(result[0].title).toBe('Add dark mode toggle')
  })

  it('does not override hitl status with active from worker', () => {
    const events = [
      { type: 'review_update', timestamp: '2026-01-15T10:00:00Z', data: { issue: 11, pr: 60, status: 'escalated' } },
    ]
    const workers = {
      'review-60': { status: 'running', role: 'reviewer', title: 'PR #60 (Issue #11)', branch: '', transcript: [], pr: 60 },
    }
    const result = deriveIssueTimelines(events, workers, [])

    expect(result[0].stages.review.status).toBe('hitl')
    expect(result[0].overallStatus).toBe('hitl')
  })

  it('does not mark issue as done when all stages except merged are done', () => {
    const events = [
      { type: 'triage_update', timestamp: '2026-01-15T10:00:00Z', data: { issue: 9, status: 'done' } },
      { type: 'planner_update', timestamp: '2026-01-15T10:01:00Z', data: { issue: 9, status: 'done' } },
      { type: 'worker_update', timestamp: '2026-01-15T10:02:00Z', data: { issue: 9, status: 'done' } },
      { type: 'review_update', timestamp: '2026-01-15T10:03:00Z', data: { issue: 9, pr: 40, status: 'done' } },
    ]
    const result = deriveIssueTimelines(events, {}, [])

    expect(result[0].stages.triage.status).toBe('done')
    expect(result[0].stages.plan.status).toBe('done')
    expect(result[0].stages.implement.status).toBe('done')
    expect(result[0].stages.review.status).toBe('done')
    expect(result[0].stages.merged.status).toBe('pending')
    // Should NOT be 'done' — merge hasn't happened yet
    expect(result[0].overallStatus).toBe('active')
  })
})

// ── applyFiltersAndSort ──────────────────────────────────────────────

describe('applyFiltersAndSort', () => {
  const issues = [
    { issueNumber: 1, currentStage: 'triage', overallStatus: 'active', startTime: '2026-01-15T10:00:00Z', endTime: null },
    { issueNumber: 2, currentStage: 'implement', overallStatus: 'active', startTime: '2026-01-15T10:05:00Z', endTime: null },
    { issueNumber: 3, currentStage: 'merged', overallStatus: 'done', startTime: '2026-01-15T10:01:00Z', endTime: '2026-01-15T10:10:00Z' },
    { issueNumber: 4, currentStage: 'review', overallStatus: 'failed', startTime: '2026-01-15T10:03:00Z', endTime: '2026-01-15T10:08:00Z' },
  ]

  it('returns all issues with "all" filters', () => {
    const result = applyFiltersAndSort(issues, 'all', 'all', 'recency')
    expect(result).toHaveLength(4)
  })

  it('filters by stage', () => {
    const result = applyFiltersAndSort(issues, 'triage', 'all', 'recency')
    expect(result).toHaveLength(1)
    expect(result[0].issueNumber).toBe(1)
  })

  it('filters by status', () => {
    const result = applyFiltersAndSort(issues, 'all', 'failed', 'recency')
    expect(result).toHaveLength(1)
    expect(result[0].issueNumber).toBe(4)
  })

  it('filters by both stage and status', () => {
    const result = applyFiltersAndSort(issues, 'implement', 'active', 'recency')
    expect(result).toHaveLength(1)
    expect(result[0].issueNumber).toBe(2)
  })

  it('sorts by recency (most recent endTime/startTime first)', () => {
    const result = applyFiltersAndSort(issues, 'all', 'all', 'recency')
    // #3 endTime=10:10 > #4 endTime=10:08 > #2 startTime=10:05 > #1 startTime=10:00
    expect(result.map(i => i.issueNumber)).toEqual([3, 4, 2, 1])
  })

  it('sorts by issue number descending', () => {
    const result = applyFiltersAndSort(issues, 'all', 'all', 'issue')
    expect(result.map(i => i.issueNumber)).toEqual([4, 3, 2, 1])
  })
})

// ── useTimeline hook ─────────────────────────────────────────────────

describe('useTimeline', () => {
  it('returns issues derived from events', () => {
    const events = [
      { type: 'triage_update', timestamp: '2026-01-15T10:00:00Z', data: { issue: 42, status: 'running' } },
    ]
    const { result } = renderHook(() => useTimeline(events, {}, []))

    expect(result.current.issues).toHaveLength(1)
    expect(result.current.issues[0].issueNumber).toBe(42)
  })

  it('returns empty issues for null/undefined inputs', () => {
    const { result } = renderHook(() => useTimeline(null, null, null))
    expect(result.current.issues).toEqual([])
  })

  it('provides filter and sort state', () => {
    const { result } = renderHook(() => useTimeline([], {}, []))

    expect(result.current.filterStage).toBe('all')
    expect(result.current.filterStatus).toBe('all')
    expect(result.current.sortBy).toBe('recency')
    expect(typeof result.current.setFilterStage).toBe('function')
    expect(typeof result.current.setFilterStatus).toBe('function')
    expect(typeof result.current.setSortBy).toBe('function')
  })

  it('updates filter and re-derives', () => {
    const events = [
      { type: 'triage_update', timestamp: '2026-01-15T10:00:00Z', data: { issue: 1, status: 'running' } },
      { type: 'worker_update', timestamp: '2026-01-15T10:01:00Z', data: { issue: 2, status: 'running' } },
    ]
    const { result } = renderHook(() => useTimeline(events, {}, []))

    expect(result.current.issues).toHaveLength(2)

    act(() => result.current.setFilterStage('triage'))
    expect(result.current.issues).toHaveLength(1)
    expect(result.current.issues[0].issueNumber).toBe(1)
  })

  it('updates sort and re-orders', () => {
    const events = [
      { type: 'triage_update', timestamp: '2026-01-15T10:00:00Z', data: { issue: 1, status: 'running' } },
      { type: 'triage_update', timestamp: '2026-01-15T10:05:00Z', data: { issue: 5, status: 'running' } },
    ]
    const { result } = renderHook(() => useTimeline(events, {}, []))

    act(() => result.current.setSortBy('issue'))
    expect(result.current.issues[0].issueNumber).toBe(5)
    expect(result.current.issues[1].issueNumber).toBe(1)
  })
})
