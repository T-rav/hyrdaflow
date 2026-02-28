import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { reducer } from '../HydraFlowContext'

const emptyPipeline = {
  triage: [],
  plan: [],
  implement: [],
  review: [],
  hitl: [],
  merged: [],
}

const initialState = {
  connected: false,
  phase: 'idle',
  orchestratorStatus: 'idle',
  workers: {},
  prs: [],
  reviews: [],
  mergedCount: 0,
  sessionPrsCount: 0,
  sessionTriaged: 0,
  sessionPlanned: 0,
  sessionImplemented: 0,
  sessionReviewed: 0,
  lifetimeStats: null,
  queueStats: null,
  config: null,
  events: [],
  hitlItems: [],
  hitlEscalation: null,
  humanInputRequests: {},
  backgroundWorkers: [],
  metrics: null,
  systemAlert: null,
  intents: [],
  githubMetrics: null,
  pipelineIssues: { ...emptyPipeline },
  pipelinePollerLastRun: null,
  sessions: [],
  currentSessionId: null,
  selectedSessionId: null,
  supervisedRepos: [],
}

const originalFetch = global.fetch

beforeEach(() => {
  vi.spyOn(global, 'fetch').mockImplementation((input) => {
    if (typeof input === 'string' && input.includes('/api/repos')) {
      return Promise.resolve({
        ok: true,
        json: async () => ({ repos: [] }),
      })
    }
    return Promise.resolve({
      ok: true,
      json: async () => ({}),
    })
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  global.fetch = originalFetch
})

describe('HydraFlowContext reducer', () => {
  it('SET_REPOS replaces supervised repo list', () => {
    const repos = [{ slug: 'demo', path: '/tmp/demo' }]
    const next = reducer(initialState, { type: 'SET_REPOS', data: { repos } })
    expect(next.supervisedRepos).toEqual(repos)
  })

  it('GITHUB_METRICS action sets githubMetrics state', () => {
    const data = {
      open_by_label: { 'hydraflow-plan': 3, 'hydraflow-ready': 1 },
      total_closed: 10,
      total_merged: 8,
    }
    const next = reducer(initialState, { type: 'GITHUB_METRICS', data })
    expect(next.githubMetrics).toEqual(data)
  })

  it('GITHUB_METRICS replaces existing data', () => {
    const state = {
      ...initialState,
      githubMetrics: { open_by_label: {}, total_closed: 0, total_merged: 0 },
    }
    const data = {
      open_by_label: { 'hydraflow-plan': 5 },
      total_closed: 15,
      total_merged: 12,
    }
    const next = reducer(state, { type: 'GITHUB_METRICS', data })
    expect(next.githubMetrics).toEqual(data)
  })

  it('orchestrator_status clears session state but not githubMetrics', () => {
    const state = {
      ...initialState,
      orchestratorStatus: 'running',
      sessionTriaged: 3,
      sessionPlanned: 2,
      githubMetrics: { open_by_label: {}, total_closed: 5, total_merged: 3 },
    }
    const next = reducer(state, {
      type: 'orchestrator_status',
      data: { status: 'idle' },
      timestamp: new Date().toISOString(),
    })
    expect(next.sessionTriaged).toBe(0)
    expect(next.sessionPlanned).toBe(0)
    expect(next.githubMetrics).toEqual({ open_by_label: {}, total_closed: 5, total_merged: 3 })
  })

  it('phase_change clears session state but not githubMetrics on new run', () => {
    const state = {
      ...initialState,
      phase: 'idle',
      sessionTriaged: 3,
      githubMetrics: { open_by_label: { 'hydraflow-plan': 2 }, total_closed: 1, total_merged: 1 },
    }
    const next = reducer(state, {
      type: 'phase_change',
      data: { phase: 'plan' },
      timestamp: new Date().toISOString(),
    })
    expect(next.sessionTriaged).toBe(0)
    expect(next.githubMetrics).toEqual({ open_by_label: { 'hydraflow-plan': 2 }, total_closed: 1, total_merged: 1 })
  })
})

describe('PIPELINE_SNAPSHOT reducer', () => {
  it('additively upserts provided stages with server data', () => {
    const state = {
      ...initialState,
      pipelineIssues: {
        ...emptyPipeline,
        triage: [{ issue_number: 1, title: 'Old title', url: '/old', status: 'active' }],
      },
    }
    const data = {
      triage: [
        { issue_number: 1, title: 'Bug', url: '', status: 'queued' },
        { issue_number: 9, title: 'New', url: '', status: 'queued' },
      ],
      plan: [],
      implement: [{ issue_number: 2, title: 'Feature', url: '', status: 'active' }],
      review: [],
      hitl: [],
    }
    const next = reducer(state, { type: 'PIPELINE_SNAPSHOT', data })
    expect(next.pipelineIssues.triage).toHaveLength(2)
    expect(next.pipelineIssues.triage.find(i => i.issue_number === 1)?.title).toBe('Bug')
    expect(next.pipelineIssues.triage.find(i => i.issue_number === 9)).toBeTruthy()
    expect(next.pipelineIssues.implement).toHaveLength(1)
    expect(next.pipelineIssues.implement[0].status).toBe('active')
  })

  it('preserves missing stages from existing state', () => {
    const state = {
      ...initialState,
      pipelineIssues: {
        ...emptyPipeline,
        plan: [{ issue_number: 77, title: 'Carry', url: '', status: 'queued' }],
        implement: [{ issue_number: 88, title: 'Keep', url: '', status: 'active' }],
      },
    }
    const data = { triage: [{ issue_number: 3, title: 'X', url: '', status: 'queued' }] }
    const next = reducer(state, { type: 'PIPELINE_SNAPSHOT', data })
    expect(next.pipelineIssues.triage).toHaveLength(1)
    expect(next.pipelineIssues.plan).toHaveLength(1)
    expect(next.pipelineIssues.plan[0].issue_number).toBe(77)
    expect(next.pipelineIssues.implement).toHaveLength(1)
    expect(next.pipelineIssues.implement[0].issue_number).toBe(88)
    expect(next.pipelineIssues.review).toEqual([])
    expect(next.pipelineIssues.hitl).toEqual([])
  })

  it('does not clear existing queues on empty snapshots', () => {
    const state = {
      ...initialState,
      pipelineIssues: {
        ...emptyPipeline,
        triage: [{ issue_number: 10, title: 'Queued', url: '', status: 'queued' }],
        implement: [{ issue_number: 11, title: 'Active', url: '', status: 'active' }],
      },
    }
    const next = reducer(state, {
      type: 'PIPELINE_SNAPSHOT',
      data: { triage: [], plan: [], implement: [], review: [], hitl: [] },
    })
    expect(next.pipelineIssues.triage).toHaveLength(1)
    expect(next.pipelineIssues.implement).toHaveLength(1)
  })
})

describe('WS_PIPELINE_UPDATE reducer', () => {
  it('moves issue between stages on stage transition', () => {
    const state = {
      ...initialState,
      pipelineIssues: {
        ...emptyPipeline,
        triage: [{ issue_number: 5, title: 'Test', url: '', status: 'active' }],
      },
    }
    const next = reducer(state, {
      type: 'WS_PIPELINE_UPDATE',
      data: { issueNumber: 5, fromStage: 'triage', toStage: 'plan', status: 'queued' },
    })
    expect(next.pipelineIssues.triage).toHaveLength(0)
    expect(next.pipelineIssues.plan).toHaveLength(1)
    expect(next.pipelineIssues.plan[0].issue_number).toBe(5)
    expect(next.pipelineIssues.plan[0].status).toBe('queued')
  })

  it('updates status without moving when no fromStage', () => {
    const state = {
      ...initialState,
      pipelineIssues: {
        ...emptyPipeline,
        implement: [{ issue_number: 7, title: 'Impl', url: '', status: 'queued' }],
      },
    }
    const next = reducer(state, {
      type: 'WS_PIPELINE_UPDATE',
      data: { issueNumber: 7, fromStage: null, toStage: null, status: 'active' },
    })
    expect(next.pipelineIssues.implement).toHaveLength(1)
    expect(next.pipelineIssues.implement[0].status).toBe('active')
  })

  it('does not add unknown issues (no-op for missing issue)', () => {
    const next = reducer(initialState, {
      type: 'WS_PIPELINE_UPDATE',
      data: { issueNumber: 999, fromStage: 'triage', toStage: 'plan', status: 'queued' },
    })
    // Issue 999 not found in triage, should not appear in plan
    expect(next.pipelineIssues.plan).toHaveLength(0)
    expect(next.pipelineIssues.triage).toHaveLength(0)
  })

  it('moves issue from review to merged on merge event', () => {
    const state = {
      ...initialState,
      pipelineIssues: {
        ...emptyPipeline,
        review: [{ issue_number: 10, title: 'PR Fix', url: '', status: 'done' }],
      },
    }
    const next = reducer(state, {
      type: 'WS_PIPELINE_UPDATE',
      data: { issueNumber: 10, fromStage: 'review', toStage: 'merged', status: 'done' },
    })
    expect(next.pipelineIssues.review).toHaveLength(0)
    expect(next.pipelineIssues.merged).toHaveLength(1)
    expect(next.pipelineIssues.merged[0].issue_number).toBe(10)
    expect(next.pipelineIssues.merged[0].status).toBe('done')
  })

  it('adds to merged even if issue was already removed from review', () => {
    // Item may have been removed by review_update done before merge_update arrives
    const state = {
      ...initialState,
      pipelineIssues: {
        ...emptyPipeline,
        review: [], // already removed
      },
    }
    const next = reducer(state, {
      type: 'WS_PIPELINE_UPDATE',
      data: { issueNumber: 10, fromStage: 'review', toStage: 'merged', status: 'done' },
    })
    expect(next.pipelineIssues.merged).toHaveLength(1)
    expect(next.pipelineIssues.merged[0].issue_number).toBe(10)
  })

  it('does not duplicate issue in merged stage', () => {
    const state = {
      ...initialState,
      pipelineIssues: {
        ...emptyPipeline,
        merged: [{ issue_number: 10, title: '', url: '', status: 'done' }],
      },
    }
    const next = reducer(state, {
      type: 'WS_PIPELINE_UPDATE',
      data: { issueNumber: 10, fromStage: 'review', toStage: 'merged', status: 'done' },
    })
    expect(next.pipelineIssues.merged).toHaveLength(1)
  })
})

describe('Merged state persistence', () => {
  it('PIPELINE_SNAPSHOT preserves session merged items', () => {
    const state = {
      ...initialState,
      pipelineIssues: {
        ...emptyPipeline,
        merged: [
          { issue_number: 10, title: 'Merged PR', url: '', status: 'done' },
          { issue_number: 11, title: 'Another Merged', url: '', status: 'done' },
        ],
      },
    }
    // Server data never includes merged
    const serverData = {
      triage: [{ issue_number: 20, title: 'New', url: '', status: 'queued' }],
    }
    const next = reducer(state, { type: 'PIPELINE_SNAPSHOT', data: serverData })
    // Merged items from session should survive
    expect(next.pipelineIssues.merged).toHaveLength(2)
    expect(next.pipelineIssues.merged[0].issue_number).toBe(10)
    // Server data should be applied
    expect(next.pipelineIssues.triage).toHaveLength(1)
  })

  it('EXISTING_PRS preserves merged PRs from session', () => {
    const state = {
      ...initialState,
      prs: [
        { pr: 100, issue: 10, merged: true, title: 'Merged PR' },
        { pr: 101, issue: 11, merged: false, title: 'Open PR' },
      ],
    }
    // Server returns only open PRs (merged PR 100 is gone)
    const openPrs = [
      { pr: 102, issue: 12, merged: false, title: 'New Open PR' },
    ]
    const next = reducer(state, { type: 'EXISTING_PRS', data: openPrs })
    // Should have the new open PR plus the preserved merged PR
    expect(next.prs).toHaveLength(2)
    expect(next.prs.find(p => p.pr === 100)?.merged).toBe(true)
    expect(next.prs.find(p => p.pr === 102)).toBeDefined()
    // Non-merged PR 101 should be gone (replaced by server data)
    expect(next.prs.find(p => p.pr === 101)).toBeUndefined()
  })

  it('EXISTING_PRS does not duplicate if merged PR reappears in server data', () => {
    const state = {
      ...initialState,
      prs: [
        { pr: 100, issue: 10, merged: true, title: 'Merged PR' },
      ],
    }
    // Server returns the same PR as open (unlikely but possible)
    const openPrs = [
      { pr: 100, issue: 10, merged: false, title: 'Merged PR' },
    ]
    const next = reducer(state, { type: 'EXISTING_PRS', data: openPrs })
    // Server version should win — only 1 entry
    expect(next.prs).toHaveLength(1)
    expect(next.prs[0].pr).toBe(100)
  })
})

describe('TOGGLE_BG_WORKER reducer', () => {
  it('updates enabled flag on existing worker', () => {
    const state = {
      ...initialState,
      backgroundWorkers: [
        { name: 'triage', status: 'ok', enabled: true, last_run: null, details: {} },
      ],
    }
    const next = reducer(state, { type: 'TOGGLE_BG_WORKER', data: { name: 'triage', enabled: false } })
    expect(next.backgroundWorkers[0].enabled).toBe(false)
    expect(next.backgroundWorkers[0].status).toBe('ok')
  })

  it('creates stub entry for unknown worker', () => {
    const next = reducer(initialState, { type: 'TOGGLE_BG_WORKER', data: { name: 'plan', enabled: false } })
    expect(next.backgroundWorkers).toHaveLength(1)
    expect(next.backgroundWorkers[0].name).toBe('plan')
    expect(next.backgroundWorkers[0].enabled).toBe(false)
  })
})

describe('BACKGROUND_WORKERS preserves local overrides', () => {
  it('keeps local enabled flag when backend sends different value', () => {
    const state = {
      ...initialState,
      backgroundWorkers: [
        { name: 'triage', status: 'ok', enabled: false, last_run: null, details: {} },
      ],
    }
    const backendData = [
      { name: 'triage', status: 'ok', enabled: true, last_run: null, details: {} },
    ]
    const next = reducer(state, { type: 'BACKGROUND_WORKERS', data: backendData })
    // Local override (false) should win over backend (true)
    expect(next.backgroundWorkers[0].enabled).toBe(false)
  })
})

describe('HydraFlowProvider', () => {
  it('renders children', async () => {
    // Dynamic import to avoid WebSocket connection in test
    const { HydraFlowProvider } = await import('../HydraFlowContext')

    // We can't fully test the provider without mocking WebSocket,
    // but we can verify it renders children
    // Note: The provider will attempt to connect but the test env has no server
    render(
      <HydraFlowProvider>
        <div>Test Child</div>
      </HydraFlowProvider>
    )
    expect(screen.getByText('Test Child')).toBeInTheDocument()
  })
})

describe('background_worker_status action', () => {
  it('preserves interval_seconds from prior state on heartbeat', () => {
    const state = {
      ...initialState,
      backgroundWorkers: [
        { name: 'memory_sync', status: 'ok', enabled: true, last_run: '2026-01-01T00:00:00Z', interval_seconds: 3600, details: {} },
      ],
    }
    const result = reducer(state, {
      type: 'background_worker_status',
      data: { worker: 'memory_sync', status: 'ok', last_run: '2026-01-01T01:00:00Z', details: {} },
      timestamp: '2026-01-01T01:00:00Z',
    })
    const worker = result.backgroundWorkers.find(w => w.name === 'memory_sync')
    // interval_seconds not in heartbeat payload — should be preserved from prev
    expect(worker.interval_seconds).toBe(3600)
  })

  it('uses interval_seconds from event data when provided', () => {
    const state = {
      ...initialState,
      backgroundWorkers: [
        { name: 'metrics', status: 'ok', enabled: true, last_run: null, interval_seconds: 7200, details: {} },
      ],
    }
    const result = reducer(state, {
      type: 'background_worker_status',
      data: { worker: 'metrics', status: 'ok', last_run: '2026-01-01T01:00:00Z', details: {}, interval_seconds: 1800 },
      timestamp: '2026-01-01T01:00:00Z',
    })
    const worker = result.backgroundWorkers.find(w => w.name === 'metrics')
    expect(worker.interval_seconds).toBe(1800)
  })

  it('defaults interval_seconds to null for new worker with no prior state', () => {
    const result = reducer(initialState, {
      type: 'background_worker_status',
      data: { worker: 'memory_sync', status: 'ok', last_run: '2026-01-01T01:00:00Z', details: {} },
      timestamp: '2026-01-01T01:00:00Z',
    })
    const worker = result.backgroundWorkers.find(w => w.name === 'memory_sync')
    expect(worker.interval_seconds).toBeNull()
  })
})

describe('UPDATE_BG_WORKER_INTERVAL action', () => {
  it('updates interval_seconds for existing worker', () => {
    const state = {
      ...initialState,
      backgroundWorkers: [
        { name: 'memory_sync', status: 'ok', enabled: true, last_run: null, interval_seconds: 3600, details: {} },
      ],
    }
    const result = reducer(state, {
      type: 'UPDATE_BG_WORKER_INTERVAL',
      data: { name: 'memory_sync', interval_seconds: 7200 },
    })
    const worker = result.backgroundWorkers.find(w => w.name === 'memory_sync')
    expect(worker.interval_seconds).toBe(7200)
  })

  it('creates stub entry for unknown worker', () => {
    const state = { ...initialState, backgroundWorkers: [] }
    const result = reducer(state, {
      type: 'UPDATE_BG_WORKER_INTERVAL',
      data: { name: 'metrics', interval_seconds: 1800 },
    })
    expect(result.backgroundWorkers).toHaveLength(1)
    expect(result.backgroundWorkers[0].name).toBe('metrics')
    expect(result.backgroundWorkers[0].interval_seconds).toBe(1800)
  })
})

describe('session_start reducer', () => {
  it('adds new session and sets currentSessionId', () => {
    const result = reducer(initialState, {
      type: 'session_start',
      data: { session_id: 'test-repo-20260222T120000', repo: 'test/repo' },
      timestamp: '2026-02-22T12:00:00Z',
    })
    expect(result.sessions).toHaveLength(1)
    expect(result.sessions[0].id).toBe('test-repo-20260222T120000')
    expect(result.sessions[0].repo).toBe('test/repo')
    expect(result.sessions[0].status).toBe('active')
    expect(result.currentSessionId).toBe('test-repo-20260222T120000')
  })

  it('prepends new session to existing list', () => {
    const state = {
      ...initialState,
      sessions: [{ id: 'old-session', repo: 'test/repo', status: 'completed', started_at: '2026-02-21T12:00:00Z' }],
    }
    const result = reducer(state, {
      type: 'session_start',
      data: { session_id: 'new-session', repo: 'test/repo' },
      timestamp: '2026-02-22T12:00:00Z',
    })
    expect(result.sessions).toHaveLength(2)
    expect(result.sessions[0].id).toBe('new-session')
    expect(result.sessions[1].id).toBe('old-session')
  })

  it('deduplicates when session_start fires for an existing session id', () => {
    const state = {
      ...initialState,
      sessions: [
        { id: 'sess-1', repo: 'test/repo', status: 'active', started_at: '2026-02-22T12:00:00Z' },
        { id: 'old-session', repo: 'test/repo', status: 'completed', started_at: '2026-02-21T12:00:00Z' },
      ],
      currentSessionId: 'sess-1',
    }
    const result = reducer(state, {
      type: 'session_start',
      data: { session_id: 'sess-1', repo: 'test/repo' },
      timestamp: '2026-02-22T12:00:01Z',
    })
    expect(result.sessions).toHaveLength(2)
    expect(result.sessions[0].id).toBe('sess-1')
    expect(result.sessions[1].id).toBe('old-session')
  })
})

describe('session_end reducer', () => {
  it('marks session as completed and clears currentSessionId', () => {
    const state = {
      ...initialState,
      sessions: [{ id: 'sess-1', repo: 'test/repo', status: 'active', started_at: '2026-02-22T12:00:00Z', ended_at: null }],
      currentSessionId: 'sess-1',
    }
    const result = reducer(state, {
      type: 'session_end',
      data: { session_id: 'sess-1' },
      timestamp: '2026-02-22T13:00:00Z',
    })
    expect(result.sessions[0].status).toBe('completed')
    expect(result.sessions[0].ended_at).toBe('2026-02-22T13:00:00Z')
    expect(result.currentSessionId).toBeNull()
  })

  it('propagates issue counts from session_end event to session state', () => {
    const state = {
      ...initialState,
      sessions: [{
        id: 'sess-1',
        repo: 'test/repo',
        status: 'active',
        started_at: '2026-02-22T12:00:00Z',
        ended_at: null,
        issues_processed: [],
        issues_succeeded: 0,
        issues_failed: 0,
      }],
      currentSessionId: 'sess-1',
    }
    const result = reducer(state, {
      type: 'session_end',
      data: {
        session_id: 'sess-1',
        issues_processed: [10, 11, 12],
        issues_succeeded: 2,
        issues_failed: 1,
      },
      timestamp: '2026-02-22T13:00:00Z',
    })
    expect(result.sessions[0].issues_processed).toEqual([10, 11, 12])
    expect(result.sessions[0].issues_succeeded).toBe(2)
    expect(result.sessions[0].issues_failed).toBe(1)
  })
})

describe('SESSIONS reducer', () => {
  it('replaces sessions list from API fetch', () => {
    const sessions = [
      { id: 's1', repo: 'a/b', status: 'completed' },
      { id: 's2', repo: 'a/b', status: 'active' },
    ]
    const result = reducer(initialState, { type: 'SESSIONS', data: sessions })
    expect(result.sessions).toHaveLength(2)
    expect(result.sessions[0].id).toBe('s1')
  })

  it('handles null data gracefully', () => {
    const result = reducer(initialState, { type: 'SESSIONS', data: null })
    expect(result.sessions).toEqual([])
  })

  it('preserves active WS session not yet in HTTP response', () => {
    const state = {
      ...initialState,
      sessions: [
        { id: 'ws-session', repo: 'test/repo', status: 'active', started_at: '2026-02-22T12:00:00Z' },
      ],
    }
    const fetched = [
      { id: 'old-session', repo: 'test/repo', status: 'completed', started_at: '2026-02-21T12:00:00Z' },
    ]
    const result = reducer(state, { type: 'SESSIONS', data: fetched })
    expect(result.sessions).toHaveLength(2)
    expect(result.sessions[0].id).toBe('ws-session')
    expect(result.sessions[1].id).toBe('old-session')
  })

  it('does not duplicate active session already in HTTP response', () => {
    const state = {
      ...initialState,
      sessions: [
        { id: 's1', repo: 'test/repo', status: 'active', started_at: '2026-02-22T12:00:00Z' },
      ],
    }
    const fetched = [
      { id: 's1', repo: 'test/repo', status: 'active', started_at: '2026-02-22T12:00:00Z' },
      { id: 's0', repo: 'test/repo', status: 'completed', started_at: '2026-02-21T12:00:00Z' },
    ]
    const result = reducer(state, { type: 'SESSIONS', data: fetched })
    expect(result.sessions).toHaveLength(2)
    expect(result.sessions.filter(s => s.id === 's1')).toHaveLength(1)
  })
})

describe('SELECT_SESSION reducer', () => {
  it('sets selectedSessionId', () => {
    const result = reducer(initialState, {
      type: 'SELECT_SESSION',
      data: { sessionId: 'sess-123' },
    })
    expect(result.selectedSessionId).toBe('sess-123')
  })

  it('clears selectedSessionId when null', () => {
    const state = { ...initialState, selectedSessionId: 'sess-123' }
    const result = reducer(state, {
      type: 'SELECT_SESSION',
      data: { sessionId: null },
    })
    expect(result.selectedSessionId).toBeNull()
  })

  it('does not reset sessions or currentSessionId', () => {
    const state = {
      ...initialState,
      sessions: [{ id: 's1', repo: 'a/b' }],
      currentSessionId: 's1',
    }
    const result = reducer(state, {
      type: 'SELECT_SESSION',
      data: { sessionId: 's1' },
    })
    expect(result.sessions).toHaveLength(1)
    expect(result.currentSessionId).toBe('s1')
  })
})

describe('hitl_escalation reducer', () => {
  it('marks review worker as escalated when pr is present (automated escalation)', () => {
    const state = {
      ...initialState,
      workers: {
        'review-99': { status: 'active', role: 'reviewer', transcript: [] },
      },
    }
    const next = reducer(state, {
      type: 'hitl_escalation',
      data: { pr: 99, issue: 42, cause: 'CI failed', origin: 'hydraflow-review' },
      timestamp: new Date().toISOString(),
    })
    expect(next.workers['review-99'].status).toBe('escalated')
    expect(next.hitlEscalation).toEqual({ pr: 99, issue: 42, cause: 'CI failed', origin: 'hydraflow-review' })
  })

  it('marks issue worker as escalated when pr is absent (manual request-changes)', () => {
    const state = {
      ...initialState,
      workers: {
        42: { status: 'active', role: 'implementer', transcript: [] },
      },
    }
    const next = reducer(state, {
      type: 'hitl_escalation',
      data: { issue: 42, cause: 'Needs rework', origin: 'hydraflow-review' },
      timestamp: new Date().toISOString(),
    })
    expect(next.workers[42].status).toBe('escalated')
    expect(next.hitlEscalation).toEqual({ issue: 42, cause: 'Needs rework', origin: 'hydraflow-review' })
  })

  it('leaves workers unchanged when no matching worker found', () => {
    const state = {
      ...initialState,
      workers: {
        7: { status: 'active', role: 'implementer', transcript: [] },
      },
    }
    const next = reducer(state, {
      type: 'hitl_escalation',
      data: { issue: 99, cause: 'Escalated', origin: 'hydraflow-review' },
      timestamp: new Date().toISOString(),
    })
    expect(next.workers[7].status).toBe('active')
    expect(next.workers[99]).toBeUndefined()

  })
})

describe('orchestrator_status reducer — session reset for other clients', () => {
  it('clears session state when status is running and reset flag is true', () => {
    const dirtyState = {
      ...initialState,
      orchestratorStatus: 'idle',
      workers: { 42: { status: 'done', role: 'implementer', transcript: [] } },
      prs: [{ pr: 100, issue: 42, merged: true }],
      reviews: [{ pr: 100, verdict: 'approve' }],
      mergedCount: 2,
      sessionPrsCount: 3,
      sessionTriaged: 1,
      sessionPlanned: 2,
      sessionImplemented: 1,
      sessionReviewed: 1,
      hitlItems: [{ issue: 42, title: 'Bug' }],
      hitlEscalation: { pr: 99, issue: 42, cause: 'CI failed' },
      humanInputRequests: { 42: { question: 'Continue?' } },
      lastSeenId: 50,
      intents: [{ text: 'Fix bug', issueNumber: 42, status: 'created' }],
    }

    const next = reducer(dirtyState, {
      type: 'orchestrator_status',
      data: { status: 'running', reset: true },
      timestamp: '2026-01-01T00:00:00Z',
    })

    expect(next.orchestratorStatus).toBe('running')
    expect(next.workers).toEqual({})
    expect(next.prs).toEqual([])
    expect(next.reviews).toEqual([])
    expect(next.mergedCount).toBe(0)
    expect(next.sessionPrsCount).toBe(0)
    expect(next.sessionTriaged).toBe(0)
    expect(next.sessionPlanned).toBe(0)
    expect(next.sessionImplemented).toBe(0)
    expect(next.sessionReviewed).toBe(0)
    expect(next.hitlItems).toEqual([])
    expect(next.hitlEscalation).toBeNull()
    expect(next.humanInputRequests).toEqual({})
    expect(next.lastSeenId).toBe(-1)
    expect(next.intents).toEqual([])
  })

  it('does NOT reset session state when running without reset flag (reconnect case)', () => {
    const dirtyState = {
      ...initialState,
      orchestratorStatus: 'running',
      workers: { 42: { status: 'running', role: 'implementer', transcript: [] } },
      mergedCount: 2,
    }

    const next = reducer(dirtyState, {
      type: 'orchestrator_status',
      data: { status: 'running' },
      timestamp: '2026-01-01T00:00:00Z',
    })

    // State preserved — this is a reconnect to an already-running orchestrator
    expect(next.workers).toEqual(dirtyState.workers)
    expect(next.mergedCount).toBe(2)
  })
})

describe('SESSION_RESET reducer', () => {
  it('clears all session-scoped state fields', () => {
    const dirtyState = {
      ...initialState,
      workers: {
        42: { status: 'running', role: 'implementer', transcript: ['line1'] },
        'plan-7': { status: 'done', role: 'planner', transcript: [] },
      },
      prs: [{ pr: 100, issue: 42, merged: true }, { pr: 101, issue: 43, merged: false }],
      reviews: [{ pr: 100, verdict: 'approve' }],
      mergedCount: 3,
      sessionPrsCount: 5,
      sessionTriaged: 2,
      sessionPlanned: 4,
      sessionImplemented: 3,
      sessionReviewed: 1,
      hitlItems: [{ issue: 42, title: 'Bug' }],
      hitlEscalation: { pr: 99, issue: 42, cause: 'CI failed' },
      humanInputRequests: { 42: { question: 'Continue?', timestamp: '2026-01-01' } },
      lastSeenId: 50,
      pipelineIssues: {
        triage: [{ issue_number: 1, title: 'A', url: '', status: 'queued' }],
        plan: [],
        implement: [{ issue_number: 2, title: 'B', url: '', status: 'active' }],
        review: [],
        hitl: [],
        merged: [{ issue_number: 3, title: 'C', url: '', status: 'done' }],
      },
      intents: [{ text: 'Fix bug', issueNumber: 42, status: 'created' }],
    }

    const next = reducer(dirtyState, { type: 'SESSION_RESET' })

    expect(next.workers).toEqual({})
    expect(next.prs).toEqual([])
    expect(next.reviews).toEqual([])
    expect(next.mergedCount).toBe(0)
    expect(next.sessionPrsCount).toBe(0)
    expect(next.sessionTriaged).toBe(0)
    expect(next.sessionPlanned).toBe(0)
    expect(next.sessionImplemented).toBe(0)
    expect(next.sessionReviewed).toBe(0)
    expect(next.hitlItems).toEqual([])
    expect(next.hitlEscalation).toBeNull()
    expect(next.humanInputRequests).toEqual({})
    expect(next.lastSeenId).toBe(-1)
    expect(next.pipelineIssues).toEqual({
      triage: [],
      plan: [],
      implement: [],
      review: [],
      hitl: [],
      merged: [],
    })
    expect(next.intents).toEqual([])
  })

  it('preserves non-session state', () => {
    const state = {
      ...initialState,
      connected: true,
      orchestratorStatus: 'running',
      lifetimeStats: { issues_completed: 10, prs_merged: 5 },
      config: { repo: 'test/repo' },
      events: [{ type: 'phase_change', timestamp: '2026-01-01' }],
      backgroundWorkers: [{ name: 'triage', status: 'ok', enabled: true }],
      metrics: { lifetime: { issues_completed: 10 } },
      githubMetrics: { open_by_label: {}, total_closed: 5, total_merged: 3 },
      metricsHistory: [{ timestamp: '2026-01-01', value: 1 }],
      // Dirty session state
      workers: { 42: { status: 'done' } },
      mergedCount: 5,
    }

    const next = reducer(state, { type: 'SESSION_RESET' })

    // Non-session fields preserved
    expect(next.connected).toBe(true)
    expect(next.orchestratorStatus).toBe('running')
    expect(next.lifetimeStats).toEqual({ issues_completed: 10, prs_merged: 5 })
    expect(next.config).toEqual({ repo: 'test/repo' })
    expect(next.events).toHaveLength(1)
    expect(next.backgroundWorkers).toHaveLength(1)
    expect(next.metrics).toEqual({ lifetime: { issues_completed: 10 } })
    expect(next.githubMetrics).toEqual({ open_by_label: {}, total_closed: 5, total_merged: 3 })
    expect(next.metricsHistory).toHaveLength(1)

    // Session fields cleared
    expect(next.workers).toEqual({})
    expect(next.mergedCount).toBe(0)
  })
})
