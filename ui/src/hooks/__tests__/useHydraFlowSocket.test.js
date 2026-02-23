import { describe, it, expect } from 'vitest'
import { reducer, initialState } from '../useHydraFlowSocket'
import { MAX_EVENTS } from '../../constants'

describe('useHydraFlowSocket reducer', () => {
  it('initial state includes hitlItems and humanInputRequests', () => {
    expect(initialState.hitlItems).toEqual([])
    expect(initialState.humanInputRequests).toEqual({})
  })

  it('HITL_ITEMS action sets hitlItems', () => {
    const items = [
      { issue: 10, title: 'Bug', issueUrl: '', pr: 20, prUrl: '', branch: 'b1' },
    ]
    const next = reducer(initialState, { type: 'HITL_ITEMS', data: items })
    expect(next.hitlItems).toEqual(items)
  })

  it('HITL_ITEMS action replaces existing hitlItems', () => {
    const state = { ...initialState, hitlItems: [{ issue: 1 }] }
    const newItems = [{ issue: 2 }, { issue: 3 }]
    const next = reducer(state, { type: 'HITL_ITEMS', data: newItems })
    expect(next.hitlItems).toEqual(newItems)
  })

  it('HUMAN_INPUT_REQUESTS action sets humanInputRequests', () => {
    const requests = { '42': 'What approach?', '43': 'Please clarify' }
    const next = reducer(initialState, { type: 'HUMAN_INPUT_REQUESTS', data: requests })
    expect(next.humanInputRequests).toEqual(requests)
  })

  it('HUMAN_INPUT_SUBMITTED action removes entry from humanInputRequests', () => {
    const state = {
      ...initialState,
      humanInputRequests: { '42': 'What approach?', '43': 'Please clarify' },
    }
    const next = reducer(state, {
      type: 'HUMAN_INPUT_SUBMITTED',
      data: { issueNumber: '42' },
    })
    expect(next.humanInputRequests).toEqual({ '43': 'Please clarify' })
  })

  it('HUMAN_INPUT_SUBMITTED does not fail for missing key', () => {
    const state = {
      ...initialState,
      humanInputRequests: { '42': 'What approach?' },
    }
    const next = reducer(state, {
      type: 'HUMAN_INPUT_SUBMITTED',
      data: { issueNumber: '99' },
    })
    expect(next.humanInputRequests).toEqual({ '42': 'What approach?' })
  })

  it('phase_change resets hitlItems on new run', () => {
    const state = {
      ...initialState,
      phase: 'idle',
      hitlItems: [{ issue: 1 }],
    }
    const next = reducer(state, {
      type: 'phase_change',
      data: { phase: 'plan' },
      timestamp: new Date().toISOString(),
    })
    expect(next.hitlItems).toEqual([])
    expect(next.phase).toBe('plan')
  })

  it('phase_change does not reset hitlItems on non-new-run transitions', () => {
    const state = {
      ...initialState,
      phase: 'plan',
      hitlItems: [{ issue: 1 }],
    }
    const next = reducer(state, {
      type: 'phase_change',
      data: { phase: 'implement' },
      timestamp: new Date().toISOString(),
    })
    expect(next.hitlItems).toEqual([{ issue: 1 }])
    expect(next.phase).toBe('implement')
  })

  it('hitl_update event is added to events log', () => {
    const next = reducer(initialState, {
      type: 'hitl_update',
      data: { issue: 42, action: 'escalated' },
      timestamp: '2024-01-01T00:00:00Z',
    })
    expect(next.events).toHaveLength(1)
    expect(next.events[0].type).toBe('hitl_update')
    expect(next.events[0].data.issue).toBe(42)
  })

  describe('session counter tracking', () => {
    it('worker_update increments sessionImplemented when status transitions to done', () => {
      const state = {
        ...initialState,
        workers: { 10: { status: 'running', worker: 1, role: 'implementer', title: 'Issue #10', branch: '', transcript: [], pr: null } },
      }
      const next = reducer(state, {
        type: 'worker_update',
        data: { issue: 10, status: 'done', worker: 1, role: 'implementer' },
      })
      expect(next.sessionImplemented).toBe(1)
    })

    it('worker_update does not double-count if already done', () => {
      const state = {
        ...initialState,
        sessionImplemented: 1,
        workers: { 10: { status: 'done', worker: 1, role: 'implementer', title: 'Issue #10', branch: '', transcript: [], pr: null } },
      }
      const next = reducer(state, {
        type: 'worker_update',
        data: { issue: 10, status: 'done', worker: 1, role: 'implementer' },
      })
      expect(next.sessionImplemented).toBe(1)
    })

    it('worker_update does not increment sessionImplemented for non-done status', () => {
      const next = reducer(initialState, {
        type: 'worker_update',
        data: { issue: 10, status: 'running', worker: 1, role: 'implementer' },
      })
      expect(next.sessionImplemented).toBe(0)
    })

    it('triage_update increments sessionTriaged when status is done', () => {
      const next = reducer(initialState, {
        type: 'triage_update',
        data: { issue: 5, status: 'done', worker: 1 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.sessionTriaged).toBe(1)
    })

    it('triage_update does not double-count if already done', () => {
      const state = {
        ...initialState,
        sessionTriaged: 1,
        workers: { 'triage-5': { status: 'done', worker: 1, role: 'triage', title: 'Triage Issue #5', branch: '', transcript: [], pr: null } },
      }
      const next = reducer(state, {
        type: 'triage_update',
        data: { issue: 5, status: 'done', worker: 1 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.sessionTriaged).toBe(1)
    })

    it('triage_update does not increment sessionTriaged for non-done status', () => {
      const next = reducer(initialState, {
        type: 'triage_update',
        data: { issue: 5, status: 'evaluating', worker: 1 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.sessionTriaged).toBe(0)
    })

    it('triage_update passes through evaluating status instead of normalizing to running', () => {
      const next = reducer(initialState, {
        type: 'triage_update',
        data: { issue: 5, status: 'evaluating', worker: 1 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.workers['triage-5'].status).toBe('evaluating')
    })

    it('triage_update passes through failed status', () => {
      const next = reducer(initialState, {
        type: 'triage_update',
        data: { issue: 5, status: 'failed', worker: 1 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.workers['triage-5'].status).toBe('failed')
    })

    it('planner_update increments sessionPlanned when status is done', () => {
      const next = reducer(initialState, {
        type: 'planner_update',
        data: { issue: 7, status: 'done', worker: 2 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.sessionPlanned).toBe(1)
    })

    it('planner_update does not double-count if already done', () => {
      const state = {
        ...initialState,
        sessionPlanned: 1,
        workers: { 'plan-7': { status: 'done', worker: 2, role: 'planner', title: 'Plan Issue #7', branch: '', transcript: [], pr: null } },
      }
      const next = reducer(state, {
        type: 'planner_update',
        data: { issue: 7, status: 'done', worker: 2 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.sessionPlanned).toBe(1)
    })

    it('planner_update does not increment sessionPlanned for failed status', () => {
      const next = reducer(initialState, {
        type: 'planner_update',
        data: { issue: 7, status: 'failed', worker: 2 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.sessionPlanned).toBe(0)
    })

    it('planner_update passes through planning status instead of normalizing to running', () => {
      const next = reducer(initialState, {
        type: 'planner_update',
        data: { issue: 7, status: 'planning', worker: 2 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.workers['plan-7'].status).toBe('planning')
    })

    it('planner_update passes through non-terminal statuses as-is', () => {
      const next = reducer(initialState, {
        type: 'planner_update',
        data: { issue: 7, status: 'some_other', worker: 2 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.workers['plan-7'].status).toBe('some_other')
    })

    it('review_update increments sessionReviewed when status is done', () => {
      const next = reducer(initialState, {
        type: 'review_update',
        data: { issue: 3, pr: 20, status: 'done', worker: 3 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.sessionReviewed).toBe(1)
    })

    it('review_update does not double-count if already done', () => {
      const state = {
        ...initialState,
        sessionReviewed: 1,
        workers: { 'review-20': { status: 'done', worker: 3, role: 'reviewer', title: 'PR #20 (Issue #3)', branch: '', transcript: [], pr: 20 } },
      }
      const next = reducer(state, {
        type: 'review_update',
        data: { issue: 3, pr: 20, status: 'done', worker: 3 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.sessionReviewed).toBe(1)
    })

    it('review_update does not increment sessionReviewed for running status', () => {
      const next = reducer(initialState, {
        type: 'review_update',
        data: { issue: 3, pr: 20, status: 'running', worker: 3 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.sessionReviewed).toBe(0)
    })

    it('review_update passes through reviewing status instead of normalizing to running', () => {
      const next = reducer(initialState, {
        type: 'review_update',
        data: { issue: 3, pr: 20, status: 'reviewing', worker: 3 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.workers['review-20'].status).toBe('reviewing')
    })

    it('review_update passes through non-terminal statuses like fixing as-is', () => {
      const next = reducer(initialState, {
        type: 'review_update',
        data: { issue: 3, pr: 20, status: 'fixing', worker: 3 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.workers['review-20'].status).toBe('fixing')
    })

    it('phase_change resets all session counters on new run', () => {
      const state = {
        ...initialState,
        phase: 'idle',
        sessionTriaged: 3,
        sessionPlanned: 5,
        sessionImplemented: 4,
        sessionReviewed: 2,
        mergedCount: 1,
        sessionPrsCount: 4,
      }
      const next = reducer(state, {
        type: 'phase_change',
        data: { phase: 'plan' },
        timestamp: new Date().toISOString(),
      })
      expect(next.sessionTriaged).toBe(0)
      expect(next.sessionPlanned).toBe(0)
      expect(next.sessionImplemented).toBe(0)
      expect(next.sessionReviewed).toBe(0)
      expect(next.mergedCount).toBe(0)
      expect(next.sessionPrsCount).toBe(0)
    })

    it('phase_change does not reset session counters on non-new-run transitions', () => {
      const state = {
        ...initialState,
        phase: 'plan',
        sessionTriaged: 3,
        sessionPlanned: 5,
        sessionImplemented: 4,
        sessionReviewed: 2,
      }
      const next = reducer(state, {
        type: 'phase_change',
        data: { phase: 'implement' },
        timestamp: new Date().toISOString(),
      })
      expect(next.sessionTriaged).toBe(3)
      expect(next.sessionPlanned).toBe(5)
      expect(next.sessionImplemented).toBe(4)
      expect(next.sessionReviewed).toBe(2)
    })

    it('multiple stage completions accumulate independently', () => {
      let state = initialState
      state = reducer(state, {
        type: 'triage_update',
        data: { issue: 1, status: 'done', worker: 1 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      state = reducer(state, {
        type: 'triage_update',
        data: { issue: 2, status: 'done', worker: 1 },
        timestamp: '2024-01-01T00:00:01Z',
      })
      state = reducer(state, {
        type: 'planner_update',
        data: { issue: 1, status: 'done', worker: 2 },
        timestamp: '2024-01-01T00:00:02Z',
      })
      expect(state.sessionTriaged).toBe(2)
      expect(state.sessionPlanned).toBe(1)
      expect(state.sessionImplemented).toBe(0)
      expect(state.sessionReviewed).toBe(0)
    })
  })

  describe('background worker status', () => {
    it('initial state includes backgroundWorkers and metrics', () => {
      expect(initialState.backgroundWorkers).toEqual([])
      expect(initialState.metrics).toBeNull()
    })

    it('background_worker_status event updates backgroundWorkers array', () => {
      const next = reducer(initialState, {
        type: 'background_worker_status',
        data: { worker: 'memory_sync', status: 'ok', last_run: '2026-01-01T00:00:00Z', details: { count: 5 } },
        timestamp: '2026-01-01T00:00:00Z',
      })
      expect(next.backgroundWorkers).toHaveLength(1)
      expect(next.backgroundWorkers[0].name).toBe('memory_sync')
      expect(next.backgroundWorkers[0].status).toBe('ok')
    })

    it('background_worker_status event for existing worker replaces entry', () => {
      const state = {
        ...initialState,
        backgroundWorkers: [{ name: 'memory_sync', status: 'ok', last_run: '2026-01-01T00:00:00Z', details: {} }],
      }
      const next = reducer(state, {
        type: 'background_worker_status',
        data: { worker: 'memory_sync', status: 'error', last_run: '2026-01-01T00:01:00Z', details: {} },
        timestamp: '2026-01-01T00:01:00Z',
      })
      expect(next.backgroundWorkers).toHaveLength(1)
      expect(next.backgroundWorkers[0].status).toBe('error')
    })

    it('BACKGROUND_WORKERS action sets the full array', () => {
      const workers = [
        { name: 'memory_sync', status: 'ok', last_run: null, details: {} },
        { name: 'metrics', status: 'disabled', last_run: null, details: {} },
      ]
      const next = reducer(initialState, { type: 'BACKGROUND_WORKERS', data: workers })
      expect(next.backgroundWorkers).toEqual(workers)
    })

    it('METRICS action sets metrics state', () => {
      const metricsData = { lifetime: { issues_completed: 5, prs_merged: 3 }, rates: { merge_rate: 0.6 } }
      const next = reducer(initialState, { type: 'METRICS', data: metricsData })
      expect(next.metrics).toEqual(metricsData)
    })

    it('phase_change does NOT reset backgroundWorkers on new run', () => {
      const state = {
        ...initialState,
        phase: 'idle',
        backgroundWorkers: [{ name: 'memory_sync', status: 'ok' }],
        metrics: { lifetime: { issues_completed: 1 }, rates: {} },
      }
      const next = reducer(state, {
        type: 'phase_change',
        data: { phase: 'plan' },
        timestamp: new Date().toISOString(),
      })
      expect(next.backgroundWorkers).toEqual([{ name: 'memory_sync', status: 'ok' }])
      expect(next.metrics).toEqual({ lifetime: { issues_completed: 1 }, rates: {} })
    })
  })

  describe('event cap (MAX_EVENTS)', () => {
    it('addEvent caps events at MAX_EVENTS', () => {
      const state = {
        ...initialState,
        events: Array.from({ length: MAX_EVENTS }, (_, i) => ({
          type: 'worker_update',
          timestamp: `2024-01-01T00:00:${String(i).padStart(6, '0')}Z`,
          data: {},
        })),
      }
      const next = reducer(state, {
        type: 'error',
        data: { message: 'overflow' },
        timestamp: '2024-01-02T00:00:00Z',
      })
      expect(next.events).toHaveLength(MAX_EVENTS)
      expect(next.events[0].type).toBe('error')
    })

    it('addEvent does not truncate below MAX_EVENTS', () => {
      const state = { ...initialState, events: [] }
      const next = reducer(state, {
        type: 'error',
        data: { message: 'test' },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.events).toHaveLength(1)
    })
  })

  describe('BACKFILL_EVENTS', () => {
    it('merges new events without duplicating existing', () => {
      const existing = [
        { type: 'batch_start', timestamp: '2024-01-01T00:00:02Z', data: { batch: 2 } },
        { type: 'batch_start', timestamp: '2024-01-01T00:00:01Z', data: { batch: 1 } },
      ]
      const state = { ...initialState, events: existing }
      const backfill = [
        { type: 'batch_start', timestamp: '2024-01-01T00:00:01Z', data: { batch: 1 } },
        { type: 'phase_change', timestamp: '2024-01-01T00:00:00Z', data: { phase: 'plan' } },
      ]
      const next = reducer(state, { type: 'BACKFILL_EVENTS', data: backfill })
      expect(next.events).toHaveLength(3)
      expect(next.events[0].timestamp).toBe('2024-01-01T00:00:02Z')
      expect(next.events[2].timestamp).toBe('2024-01-01T00:00:00Z')
    })

    it('populates empty state', () => {
      const backfill = [
        { type: 'batch_start', timestamp: '2024-01-01T00:00:01Z', data: { batch: 1 } },
      ]
      const next = reducer(initialState, { type: 'BACKFILL_EVENTS', data: backfill })
      expect(next.events).toHaveLength(1)
      expect(next.events[0].type).toBe('batch_start')
    })

    it('with empty data is a no-op', () => {
      const state = {
        ...initialState,
        events: [
          { type: 'batch_start', timestamp: '2024-01-01T00:00:01Z', data: {} },
        ],
      }
      const next = reducer(state, { type: 'BACKFILL_EVENTS', data: [] })
      expect(next.events).toHaveLength(1)
    })

    it('caps combined events at MAX_EVENTS', () => {
      const existing = Array.from({ length: 3000 }, (_, i) => ({
        type: 'worker_update',
        timestamp: `2024-01-01T01:00:${String(i).padStart(6, '0')}Z`,
        data: {},
      }))
      const backfill = Array.from({ length: 3000 }, (_, i) => ({
        type: 'phase_change',
        timestamp: `2024-01-01T00:00:${String(i).padStart(6, '0')}Z`,
        data: {},
      }))
      const state = { ...initialState, events: existing }
      const next = reducer(state, { type: 'BACKFILL_EVENTS', data: backfill })
      expect(next.events).toHaveLength(MAX_EVENTS)
    })

    it('sorts merged events newest-first', () => {
      const existing = [
        { type: 'batch_start', timestamp: '2024-01-01T00:00:03Z', data: {} },
        { type: 'batch_start', timestamp: '2024-01-01T00:00:01Z', data: {} },
      ]
      const backfill = [
        { type: 'phase_change', timestamp: '2024-01-01T00:00:04Z', data: {} },
        { type: 'phase_change', timestamp: '2024-01-01T00:00:02Z', data: {} },
      ]
      const state = { ...initialState, events: existing }
      const next = reducer(state, { type: 'BACKFILL_EVENTS', data: backfill })
      expect(next.events).toHaveLength(4)
      expect(next.events.map(e => e.timestamp)).toEqual([
        '2024-01-01T00:00:04Z',
        '2024-01-01T00:00:03Z',
        '2024-01-01T00:00:02Z',
        '2024-01-01T00:00:01Z',
      ])
    })
  })

  describe('PR deduplication', () => {
    it('EXISTING_PRS replaces state instead of prepending', () => {
      const state = { ...initialState, prs: [{ pr: 1 }, { pr: 2 }] }
      const next = reducer(state, { type: 'EXISTING_PRS', data: [{ pr: 3 }, { pr: 4 }] })
      expect(next.prs).toEqual([{ pr: 3 }, { pr: 4 }])
    })

    it('EXISTING_PRS on reconnect does not duplicate', () => {
      const data = [{ pr: 10 }, { pr: 20 }]
      let state = reducer(initialState, { type: 'EXISTING_PRS', data })
      state = reducer(state, { type: 'EXISTING_PRS', data })
      expect(state.prs).toHaveLength(2)
      expect(state.prs).toEqual(data)
    })

    it('pr_created does not add duplicate PR', () => {
      const state = { ...initialState, prs: [{ pr: 42, issue: 1 }], sessionPrsCount: 1 }
      const next = reducer(state, {
        type: 'pr_created',
        data: { pr: 42, issue: 1 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.prs).toHaveLength(1)
      expect(next.sessionPrsCount).toBe(1)
    })

    it('pr_created adds new PR when not a duplicate', () => {
      const state = { ...initialState, prs: [{ pr: 42 }], sessionPrsCount: 1 }
      const next = reducer(state, {
        type: 'pr_created',
        data: { pr: 43, issue: 2 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(next.prs).toHaveLength(2)
      expect(next.sessionPrsCount).toBe(2)
    })

    it('pr_created deduplicates after EXISTING_PRS backfill', () => {
      let state = reducer(initialState, {
        type: 'EXISTING_PRS',
        data: [{ pr: 10 }, { pr: 20 }],
      })
      state = reducer(state, {
        type: 'pr_created',
        data: { pr: 10, issue: 1 },
        timestamp: '2024-01-01T00:00:00Z',
      })
      expect(state.prs).toHaveLength(2)
      expect(state.sessionPrsCount).toBe(0)
    })

    it('WebSocket reconnect with overlapping data does not inflate count', () => {
      let state = reducer(initialState, {
        type: 'EXISTING_PRS',
        data: [{ pr: 1 }, { pr: 2 }, { pr: 3 }],
      })
      // Simulate a pr_created event during the session
      state = reducer(state, {
        type: 'pr_created',
        data: { pr: 4, issue: 4 },
        timestamp: '2024-01-01T00:00:01Z',
      })
      expect(state.prs).toHaveLength(4)
      // Simulate reconnect — EXISTING_PRS replaces with fresh API data
      state = reducer(state, {
        type: 'EXISTING_PRS',
        data: [{ pr: 1 }, { pr: 2 }, { pr: 3 }, { pr: 4 }],
      })
      expect(state.prs).toHaveLength(4)
    })
  })

  describe('orchestrator_status clears stale session state', () => {
    const staleState = {
      ...initialState,
      orchestratorStatus: 'running',
      workers: {
        1: { status: 'running', worker: 1, role: 'implementer', title: 'Issue #1', branch: '', transcript: [], pr: null },
        'plan-2': { status: 'planning', worker: 2, role: 'planner', title: 'Plan Issue #2', branch: '', transcript: [], pr: null },
      },
      sessionTriaged: 3,
      sessionPlanned: 2,
      sessionImplemented: 5,
      sessionReviewed: 4,
      mergedCount: 1,
      sessionPrsCount: 3,
    }

    it('clears workers and session stats when status transitions to idle', () => {
      const next = reducer(staleState, {
        type: 'orchestrator_status',
        data: { status: 'idle' },
        timestamp: '2024-01-01T00:00:01Z',
      })
      expect(next.orchestratorStatus).toBe('idle')
      expect(next.workers).toEqual({})
      expect(next.sessionTriaged).toBe(0)
      expect(next.sessionPlanned).toBe(0)
      expect(next.sessionImplemented).toBe(0)
      expect(next.sessionReviewed).toBe(0)
      expect(next.mergedCount).toBe(0)
      expect(next.sessionPrsCount).toBe(0)
    })

    it('clears workers and session stats when status transitions to done', () => {
      const next = reducer(staleState, {
        type: 'orchestrator_status',
        data: { status: 'done' },
        timestamp: '2024-01-01T00:00:01Z',
      })
      expect(next.orchestratorStatus).toBe('done')
      expect(next.workers).toEqual({})
      expect(next.sessionImplemented).toBe(0)
    })

    it('preserves workers and session stats when status is running', () => {
      const next = reducer(staleState, {
        type: 'orchestrator_status',
        data: { status: 'running' },
        timestamp: '2024-01-01T00:00:01Z',
      })
      expect(next.orchestratorStatus).toBe('running')
      expect(Object.keys(next.workers)).toHaveLength(2)
      expect(next.sessionImplemented).toBe(5)
    })

    it('clears workers and session stats when status is stopping', () => {
      const next = reducer(staleState, {
        type: 'orchestrator_status',
        data: { status: 'stopping' },
        timestamp: '2024-01-01T00:00:01Z',
      })
      expect(next.orchestratorStatus).toBe('stopping')
      expect(next.workers).toEqual({})
      expect(next.sessionImplemented).toBe(0)
    })
  })

  describe('event deduplication on reconnect', () => {
    it('initialState includes lastSeenId at -1', () => {
      expect(initialState.lastSeenId).toBe(-1)
    })

    it('deduplicates events on reconnect by event ID', () => {
      let state = initialState
      // Dispatch events with ids 1, 2, 3 (use 'error' type which goes through addEvent)
      for (let i = 1; i <= 3; i++) {
        state = reducer(state, {
          type: 'error',
          data: { message: `msg ${i}` },
          timestamp: `2024-01-01T00:00:0${i}Z`,
          id: i,
        })
      }
      expect(state.events).toHaveLength(3)
      expect(state.lastSeenId).toBe(3)

      // Simulate reconnect: replay same events
      for (let i = 1; i <= 3; i++) {
        state = reducer(state, {
          type: 'error',
          data: { message: `msg ${i}` },
          timestamp: `2024-01-01T00:00:0${i}Z`,
          id: i,
        })
      }
      // Should still have exactly 3 events (no duplicates)
      expect(state.events).toHaveLength(3)
    })

    it('skips duplicate transcript_line events', () => {
      // Set up a worker
      let state = reducer(initialState, {
        type: 'worker_update',
        data: { issue: 10, status: 'running', worker: 1, role: 'implementer' },
        id: 1,
      })
      // Add a transcript line
      state = reducer(state, {
        type: 'transcript_line',
        data: { issue: 10, line: 'hello world' },
        timestamp: '2024-01-01T00:00:01Z',
        id: 5,
      })
      expect(state.workers[10].transcript).toHaveLength(1)

      // Replay same transcript_line (duplicate id)
      state = reducer(state, {
        type: 'transcript_line',
        data: { issue: 10, line: 'hello world' },
        timestamp: '2024-01-01T00:00:01Z',
        id: 5,
      })
      // Should still have exactly 1 transcript line
      expect(state.workers[10].transcript).toHaveLength(1)
    })

    it('allows new events after reconnect replays duplicates', () => {
      let state = initialState
      // First connection: events 1-3
      for (let i = 1; i <= 3; i++) {
        state = reducer(state, {
          type: 'error',
          data: { message: `msg ${i}` },
          timestamp: `2024-01-01T00:00:0${i}Z`,
          id: i,
        })
      }
      expect(state.events).toHaveLength(3)

      // Reconnect replay: 1-3 (skipped) + 4-5 (new)
      for (let i = 1; i <= 5; i++) {
        state = reducer(state, {
          type: 'error',
          data: { message: `msg ${i}` },
          timestamp: `2024-01-01T00:00:0${i}Z`,
          id: i,
        })
      }
      expect(state.events).toHaveLength(5)
    })

    it('tracks lastSeenId as highest seen event ID', () => {
      let state = initialState
      state = reducer(state, {
        type: 'error',
        data: { message: 'a' },
        timestamp: '2024-01-01T00:00:01Z',
        id: 10,
      })
      expect(state.lastSeenId).toBe(10)

      state = reducer(state, {
        type: 'error',
        data: { message: 'b' },
        timestamp: '2024-01-01T00:00:02Z',
        id: 20,
      })
      expect(state.lastSeenId).toBe(20)
    })

    it('resets lastSeenId on new run phase_change', () => {
      let state = {
        ...initialState,
        phase: 'idle',
        lastSeenId: 50,
      }
      state = reducer(state, {
        type: 'phase_change',
        data: { phase: 'plan' },
        timestamp: '2024-01-01T00:00:01Z',
        id: 51,
      })
      expect(state.lastSeenId).toBe(-1)
      expect(state.phase).toBe('plan')
    })

    it('accepts events without id field (legacy/internal)', () => {
      let state = initialState
      state = reducer(state, {
        type: 'error',
        data: { message: 'no id' },
        timestamp: '2024-01-01T00:00:01Z',
      })
      expect(state.events).toHaveLength(1)
      // lastSeenId should remain -1 since event had no id
      expect(state.lastSeenId).toBe(-1)

      // Another event without id should also be accepted
      state = reducer(state, {
        type: 'error',
        data: { message: 'also no id' },
        timestamp: '2024-01-01T00:00:02Z',
      })
      expect(state.events).toHaveLength(2)
    })

    it('does not reset lastSeenId on DISCONNECTED', () => {
      let state = { ...initialState, lastSeenId: 42 }
      state = reducer(state, { type: 'DISCONNECTED' })
      expect(state.lastSeenId).toBe(42)
    })
  })
})
