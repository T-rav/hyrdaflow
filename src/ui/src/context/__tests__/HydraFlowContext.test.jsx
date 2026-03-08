import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
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
  lastSeenId: -1,
  phase: 'idle',
  orchestratorStatus: 'idle',
  creditsPausedUntil: null,
  workers: {},
  prs: [],
  reviews: [],
  sessionPrsCount: 0,
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
  epics: [],
  epicReleasing: null,
  githubMetrics: null,
  metricsHistory: null,
  pipelineIssues: { ...emptyPipeline },
  pipelineStats: null,
  pipelinePollerLastRun: null,
  sessions: [],
  currentSessionId: null,
  selectedSessionId: null,
  selectedRepoSlug: null,
  supervisedRepos: [],
  runtimes: [],
  issueHistory: null,
  harnessInsights: null,
  reviewInsights: null,
  retrospectives: null,
  troubleshooting: null,
  memories: null,
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
      githubMetrics: { open_by_label: {}, total_closed: 5, total_merged: 3 },
    }
    const next = reducer(state, {
      type: 'orchestrator_status',
      data: { status: 'idle' },
      timestamp: new Date().toISOString(),
    })
    expect(next.githubMetrics).toEqual({ open_by_label: {}, total_closed: 5, total_merged: 3 })
  })

  it('phase_change clears session state but not githubMetrics on new run', () => {
    const state = {
      ...initialState,
      phase: 'idle',
      githubMetrics: { open_by_label: { 'hydraflow-plan': 2 }, total_closed: 1, total_merged: 1 },
    }
    const next = reducer(state, {
      type: 'phase_change',
      data: { phase: 'plan' },
      timestamp: new Date().toISOString(),
    })
    expect(next.githubMetrics).toEqual({ open_by_label: { 'hydraflow-plan': 2 }, total_closed: 1, total_merged: 1 })
  })
})

describe('SET_CENTRALIZED_DATA reducer', () => {
  it('merges whitelisted fields into state', () => {
    const data = {
      issueHistory: { items: [{ issue_number: 1 }], totals: {} },
      harnessInsights: { total_failures: 5 },
      reviewInsights: { total_reviews: 3 },
    }
    const next = reducer(initialState, { type: 'SET_CENTRALIZED_DATA', data })
    expect(next.issueHistory).toEqual(data.issueHistory)
    expect(next.harnessInsights).toEqual(data.harnessInsights)
    expect(next.reviewInsights).toEqual(data.reviewInsights)
    expect(next.retrospectives).toBeNull()
    expect(next.troubleshooting).toBeNull()
    expect(next.memories).toBeNull()
  })

  it('preserves previous values for fields not in update', () => {
    const prev = {
      ...initialState,
      issueHistory: { items: [{ issue_number: 1 }], totals: {} },
      memories: { total_items: 10, items: [] },
    }
    const next = reducer(prev, {
      type: 'SET_CENTRALIZED_DATA',
      data: { harnessInsights: { total_failures: 2 } },
    })
    expect(next.issueHistory).toEqual(prev.issueHistory)
    expect(next.memories).toEqual(prev.memories)
    expect(next.harnessInsights).toEqual({ total_failures: 2 })
  })

  it('ignores unknown fields in data payload', () => {
    const next = reducer(initialState, {
      type: 'SET_CENTRALIZED_DATA',
      data: { connected: false, phase: 'done', issueHistory: { items: [] } },
    })
    expect(next.connected).toBe(false) // from initialState, not overwritten
    expect(next.phase).toBe('idle') // from initialState, not overwritten
    expect(next.issueHistory).toEqual({ items: [] })
  })
})

describe('PIPELINE_SNAPSHOT reducer', () => {
  it('reconciles stage membership with server snapshot data', () => {
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

  it('removes issues absent from the server snapshot (ghost card fix)', () => {
    // When the server sends an empty array for a stage, issues that were locally
    // tracked in that stage must be removed — they have moved elsewhere.
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
    expect(next.pipelineIssues.triage).toHaveLength(0)
    expect(next.pipelineIssues.implement).toHaveLength(0)
  })

  it('removes issue from old stage when snapshot shows it has moved (cross-stage ghost card)', () => {
    // Regression for #1515: issue #100 was in implement, backend transitioned
    // it to review. Next snapshot delivers { implement: [], review: [#100] }.
    // The issue must appear ONLY in review, not in both stages.
    const state = {
      ...initialState,
      pipelineIssues: {
        ...emptyPipeline,
        implement: [{ issue_number: 100, title: 'Fix bug', url: '', status: 'active' }],
      },
    }
    const next = reducer(state, {
      type: 'PIPELINE_SNAPSHOT',
      data: {
        triage: [],
        plan: [],
        implement: [],
        review: [{ issue_number: 100, title: 'Fix bug', url: '', status: 'queued' }],
        hitl: [],
      },
    })
    expect(next.pipelineIssues.implement).toHaveLength(0)
    expect(next.pipelineIssues.review).toHaveLength(1)
    expect(next.pipelineIssues.review[0].issue_number).toBe(100)
  })

  it('snapshot status overrides local WS status for issues that remain in their stage', () => {
    // Snapshot is authoritative: a subsequent poll snapshot's status value
    // overrides any locally-applied WS-derived status update.
    const state = {
      ...initialState,
      pipelineIssues: {
        ...emptyPipeline,
        implement: [{ issue_number: 55, title: 'Impl', url: '', status: 'active' }],
      },
    }
    const next = reducer(state, {
      type: 'PIPELINE_SNAPSHOT',
      data: {
        implement: [{ issue_number: 55, title: 'Impl', url: '', status: 'queued' }],
      },
    })
    // Incoming status wins (snapshot is newer / more authoritative than local WS update)
    expect(next.pipelineIssues.implement[0].status).toBe('queued')
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

describe('startRuntime compatibility flow', () => {
  afterEach(() => {
    delete window.__HYDRAFLOW_SEED_STATE__
  })

  it('falls back to /api/repos when runtime registry start is unavailable', async () => {
    window.__HYDRAFLOW_SEED_STATE__ = { connected: true, phase: 'idle' }
    vi.resetModules()

    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((input, init) => {
      const url = typeof input === 'string' ? input : String(input)
      if (url === '/api/runtimes/demo/start') {
        return Promise.resolve({
          ok: false,
          status: 501,
          json: async () => ({ error: 'No runtime registry configured' }),
        })
      }
      if (url === '/api/repos' && init?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ok' }),
        })
      }
      if (url === '/api/repos') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ repos: [] }),
        })
      }
      if (url === '/api/runtimes') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ runtimes: [] }),
        })
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      })
    })

    const { HydraFlowProvider, useHydraFlow } = await import('../HydraFlowContext')
    let capturedState = null
    function StateCapture() {
      capturedState = useHydraFlow()
      return <div>ready</div>
    }

    await act(async () => {
      render(
        <HydraFlowProvider>
          <StateCapture />
        </HydraFlowProvider>
      )
    })

    await act(async () => {
      await capturedState.startRuntime('demo')
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/runtimes/demo/start', { method: 'POST' })
    expect(fetchSpy).toHaveBeenCalledWith('/api/repos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug: 'demo' }),
    })
    expect(fetchSpy).toHaveBeenCalledWith('/api/repos')
    expect(fetchSpy).toHaveBeenCalledWith('/api/runtimes')
  })

  it('falls back to /api/repos when runtime start returns 422 validation error', async () => {
    window.__HYDRAFLOW_SEED_STATE__ = { connected: true, phase: 'idle' }
    vi.resetModules()

    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((input, init) => {
      const url = typeof input === 'string' ? input : String(input)
      if (url === '/api/runtimes/demo/start') {
        return Promise.resolve({
          ok: false,
          status: 422,
          json: async () => ({ detail: [{ msg: 'Field required' }] }),
        })
      }
      if (url === '/api/repos' && init?.method === 'POST') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ok' }),
        })
      }
      if (url === '/api/repos') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ repos: [] }),
        })
      }
      if (url === '/api/runtimes') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ runtimes: [] }),
        })
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      })
    })

    const { HydraFlowProvider, useHydraFlow } = await import('../HydraFlowContext')
    let capturedState = null
    function StateCapture() {
      capturedState = useHydraFlow()
      return <div>ready</div>
    }

    await act(async () => {
      render(
        <HydraFlowProvider>
          <StateCapture />
        </HydraFlowProvider>
      )
    })

    await act(async () => {
      await capturedState.startRuntime('demo')
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/runtimes/demo/start', { method: 'POST' })
    expect(fetchSpy).toHaveBeenCalledWith('/api/repos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug: 'demo' }),
    })
  })
  it('falls back to /api/repos/add by path when POST /api/repos is not supported', async () => {
    window.__HYDRAFLOW_SEED_STATE__ = { connected: true, phase: 'idle' }
    vi.resetModules()

    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((input, init) => {
      const url = typeof input === 'string' ? input : String(input)
      if (url === '/api/runtimes/demo/start') {
        return Promise.resolve({
          ok: false,
          status: 405,
          json: async () => ({ error: 'Method Not Allowed' }),
        })
      }
      if (url === '/api/repos' && init?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          status: 405,
          json: async () => ({ error: 'Method Not Allowed' }),
        })
      }
      if (url === '/api/repos' && !init?.method) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ repos: [{ slug: 'demo', path: '/tmp/demo' }] }),
        })
      }
      if (url === '/api/repos/add') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ok', slug: 'demo' }),
        })
      }
      if (url === '/api/runtimes') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ runtimes: [] }),
        })
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      })
    })

    const { HydraFlowProvider, useHydraFlow } = await import('../HydraFlowContext')
    let capturedState = null
    function StateCapture() {
      capturedState = useHydraFlow()
      return <div>ready</div>
    }

    await act(async () => {
      render(
        <HydraFlowProvider>
          <StateCapture />
        </HydraFlowProvider>
      )
    })

    await act(async () => {
      await capturedState.startRuntime('demo')
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/runtimes/demo/start', { method: 'POST' })
    expect(fetchSpy).toHaveBeenCalledWith('/api/repos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug: 'demo' }),
    })
    expect(fetchSpy).toHaveBeenCalledWith('/api/repos')
    expect(fetchSpy).toHaveBeenCalledWith('/api/repos/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: '/tmp/demo' }),
    })
  })

  it('uses provided repo path for /api/repos/add fallback without listing repos', async () => {
    window.__HYDRAFLOW_SEED_STATE__ = { connected: true, phase: 'idle' }
    vi.resetModules()

    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((input, init) => {
      const url = typeof input === 'string' ? input : String(input)
      if (url === '/api/runtimes/demo/start') {
        return Promise.resolve({
          ok: false,
          status: 405,
          json: async () => ({ error: 'Method Not Allowed' }),
        })
      }
      if (url === '/api/repos' && init?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          status: 405,
          json: async () => ({ error: 'Method Not Allowed' }),
        })
      }
      if (url === '/api/repos/add') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ok', slug: 'demo' }),
        })
      }
      if (url === '/api/repos') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ repos: [] }),
        })
      }
      if (url === '/api/runtimes') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ runtimes: [] }),
        })
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      })
    })

    const { HydraFlowProvider, useHydraFlow } = await import('../HydraFlowContext')
    let capturedState = null
    function StateCapture() {
      capturedState = useHydraFlow()
      return <div>ready</div>
    }

    await act(async () => {
      render(
        <HydraFlowProvider>
          <StateCapture />
        </HydraFlowProvider>
      )
    })

    await act(async () => {
      await capturedState.startRuntime('demo', '/tmp/from-sidebar')
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/repos/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: '/tmp/from-sidebar' }),
    })
    const firstAddIndex = fetchSpy.mock.calls.findIndex(
      (args) => args[0] === '/api/repos/add',
    )
    const firstListIndex = fetchSpy.mock.calls.findIndex(
      (args) => args[0] === '/api/repos' && args.length === 1,
    )
    expect(firstAddIndex).toBeGreaterThan(-1)
    if (firstListIndex !== -1) {
      expect(firstAddIndex).toBeLessThan(firstListIndex)
    }
  })

  it('retries POST /api/repos with wrapped req payload when backend returns 422', async () => {
    window.__HYDRAFLOW_SEED_STATE__ = { connected: true, phase: 'idle' }
    vi.resetModules()

    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((input, init) => {
      const url = typeof input === 'string' ? input : String(input)
      if (url === '/api/runtimes/demo/start') {
        return Promise.resolve({
          ok: false,
          status: 405,
          json: async () => ({ error: 'Method Not Allowed' }),
        })
      }
      if (url === '/api/repos' && init?.method === 'POST' && init?.body === JSON.stringify({ slug: 'demo' })) {
        return Promise.resolve({
          ok: false,
          status: 422,
          json: async () => ({ detail: 'invalid body' }),
        })
      }
      if (url === '/api/repos' && init?.method === 'POST' && init?.body === JSON.stringify({ req: { slug: 'demo' } })) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ok' }),
        })
      }
      if (url === '/api/repos') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ repos: [] }),
        })
      }
      if (url === '/api/runtimes') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ runtimes: [] }),
        })
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      })
    })

    const { HydraFlowProvider, useHydraFlow } = await import('../HydraFlowContext')
    let capturedState = null
    function StateCapture() {
      capturedState = useHydraFlow()
      return <div>ready</div>
    }

    await act(async () => {
      render(
        <HydraFlowProvider>
          <StateCapture />
        </HydraFlowProvider>
      )
    })

    await act(async () => {
      await capturedState.startRuntime('demo')
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/repos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug: 'demo' }),
    })
    expect(fetchSpy).toHaveBeenCalledWith('/api/repos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ req: { slug: 'demo' } }),
    })
  })

  it('falls back to /api/repos/add when /api/repos variants fail with 422/500', async () => {
    window.__HYDRAFLOW_SEED_STATE__ = { connected: true, phase: 'idle' }
    vi.resetModules()

    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((input, init) => {
      const url = typeof input === 'string' ? input : String(input)
      if (url === '/api/runtimes/demo/start') {
        return Promise.resolve({
          ok: false,
          status: 405,
          json: async () => ({ error: 'Method Not Allowed' }),
        })
      }
      if (url === '/api/repos' && init?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          status: 422,
          json: async () => ({ detail: [{ msg: 'Field required' }] }),
        })
      }
      if (url.startsWith('/api/repos?')) {
        return Promise.resolve({
          ok: false,
          status: 500,
          json: async () => ({ error: 'Internal Server Error' }),
        })
      }
      if (url === '/api/repos/add') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ok', slug: 'demo' }),
        })
      }
      if (url === '/api/repos') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ repos: [] }),
        })
      }
      if (url === '/api/runtimes') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ runtimes: [] }),
        })
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      })
    })

    const { HydraFlowProvider, useHydraFlow } = await import('../HydraFlowContext')
    let capturedState = null
    function StateCapture() {
      capturedState = useHydraFlow()
      return <div>ready</div>
    }

    await act(async () => {
      render(
        <HydraFlowProvider>
          <StateCapture />
        </HydraFlowProvider>
      )
    })

    await act(async () => {
      await capturedState.startRuntime('demo', '/tmp/from-sidebar')
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/repos/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: '/tmp/from-sidebar' }),
    })
  })

  it('retries POST /api/repos/add with wrapped req payload on 422', async () => {
    window.__HYDRAFLOW_SEED_STATE__ = { connected: true, phase: 'idle' }
    vi.resetModules()

    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((input, init) => {
      const url = typeof input === 'string' ? input : String(input)
      if (url === '/api/runtimes/demo/start') {
        return Promise.resolve({
          ok: false,
          status: 405,
          json: async () => ({ error: 'Method Not Allowed' }),
        })
      }
      if (url === '/api/repos' && init?.method === 'POST') {
        return Promise.resolve({
          ok: false,
          status: 405,
          json: async () => ({ error: 'Method Not Allowed' }),
        })
      }
      if (url === '/api/repos/add' && init?.body === JSON.stringify({ path: '/tmp/from-sidebar' })) {
        return Promise.resolve({
          ok: false,
          status: 422,
          json: async () => ({ detail: 'invalid body' }),
        })
      }
      if (url === '/api/repos/add' && init?.body === JSON.stringify({ req: { path: '/tmp/from-sidebar' } })) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'ok', slug: 'demo' }),
        })
      }
      if (url === '/api/repos') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ repos: [] }),
        })
      }
      if (url === '/api/runtimes') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ runtimes: [] }),
        })
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      })
    })

    const { HydraFlowProvider, useHydraFlow } = await import('../HydraFlowContext')
    let capturedState = null
    function StateCapture() {
      capturedState = useHydraFlow()
      return <div>ready</div>
    }

    await act(async () => {
      render(
        <HydraFlowProvider>
          <StateCapture />
        </HydraFlowProvider>
      )
    })

    await act(async () => {
      await capturedState.startRuntime('demo', '/tmp/from-sidebar')
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/repos/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: '/tmp/from-sidebar' }),
    })
    expect(fetchSpy).toHaveBeenCalledWith('/api/repos/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ req: { path: '/tmp/from-sidebar' } }),
    })
  })
})

describe('start/stop orchestrator with repo selection', () => {
  afterEach(() => {
    delete window.__HYDRAFLOW_SEED_STATE__
  })

  it('startOrchestrator delegates to runtime endpoint when repo selected', async () => {
    window.__HYDRAFLOW_SEED_STATE__ = { connected: true, phase: 'idle', selectedRepoSlug: 'demo' }
    vi.resetModules()

    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((input, init) => {
      const url = typeof input === 'string' ? input : String(input)
      if (url.startsWith('/api/runtimes')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({}),
        })
      }
      if (url === '/api/control/status') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'idle', credits_paused_until: null }),
        })
      }
      if (url === '/api/repos') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ repos: [] }),
        })
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      })
    })

    const { HydraFlowProvider, useHydraFlow } = await import('../HydraFlowContext')
    let captured = null
    function Capture() {
      captured = useHydraFlow()
      return <div>ready</div>
    }

    await act(async () => {
      render(
        <HydraFlowProvider>
          <Capture />
        </HydraFlowProvider>
      )
    })

    fetchSpy.mockClear()
    await captured.startOrchestrator()

    const calledUrls = fetchSpy.mock.calls.map(([url]) => (typeof url === 'string' ? url : String(url)))
    expect(calledUrls).toContain('/api/runtimes/demo/start')
    expect(calledUrls).not.toContain('/api/control/start')
  })

  it('stopOrchestrator delegates to runtime endpoint when repo selected', async () => {
    window.__HYDRAFLOW_SEED_STATE__ = { connected: true, phase: 'idle', selectedRepoSlug: 'demo' }
    vi.resetModules()

    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation((input, init) => {
      const url = typeof input === 'string' ? input : String(input)
      if (url.startsWith('/api/runtimes')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({}),
        })
      }
      if (url === '/api/control/status') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: 'running', credits_paused_until: null }),
        })
      }
      if (url === '/api/repos') {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ repos: [] }),
        })
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({}),
      })
    })

    const { HydraFlowProvider, useHydraFlow } = await import('../HydraFlowContext')
    let captured = null
    function Capture() {
      captured = useHydraFlow()
      return <div>ready</div>
    }

    await act(async () => {
      render(
        <HydraFlowProvider>
          <Capture />
        </HydraFlowProvider>
      )
    })

    fetchSpy.mockClear()
    await captured.stopOrchestrator()

    const calledUrls = fetchSpy.mock.calls.map(([url]) => (typeof url === 'string' ? url : String(url)))
    expect(calledUrls).toContain('/api/runtimes/demo/stop')
    expect(calledUrls).not.toContain('/api/control/stop')
  })
})

describe('seed state injection via __HYDRAFLOW_SEED_STATE__', () => {
  afterEach(() => {
    delete window.__HYDRAFLOW_SEED_STATE__
  })

  it('uses seed state as initial state when window.__HYDRAFLOW_SEED_STATE__ is set', async () => {
    const seedData = {
      connected: true,
      phase: 'implement',
      orchestratorStatus: 'running',
      workers: { 42: { status: 'active', role: 'implementer', title: 'Issue #42', branch: 'agent/issue-42', transcript: [], pr: null } },
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [{ issue_number: 42, title: 'Seed issue', url: '', status: 'active' }],
        review: [],
        hitl: [],
        merged: [],
      },
    }
    window.__HYDRAFLOW_SEED_STATE__ = seedData

    // Fresh import so the module re-evaluates with seed state
    vi.resetModules()
    const { HydraFlowProvider, useHydraFlow } = await import('../HydraFlowContext')

    let capturedState = null
    function StateCapture() {
      capturedState = useHydraFlow()
      return <div>seeded</div>
    }

    await act(async () => {
      render(
        <HydraFlowProvider>
          <StateCapture />
        </HydraFlowProvider>
      )
    })

    expect(screen.getByText('seeded')).toBeInTheDocument()
    expect(capturedState.phase).toBe('implement')
    expect(capturedState.orchestratorStatus).toBe('running')
    expect(capturedState.connected).toBe(true)
  })

  it('does not make network calls when seeded', async () => {
    window.__HYDRAFLOW_SEED_STATE__ = { connected: true, phase: 'idle' }

    vi.resetModules()
    const fetchSpy = vi.spyOn(global, 'fetch')
    const { HydraFlowProvider } = await import('../HydraFlowContext')

    await act(async () => {
      render(
        <HydraFlowProvider>
          <div>no-fetch</div>
        </HydraFlowProvider>
      )
    })

    // With seed state, no API or WebSocket calls should be made
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})

describe('EPIC_READY reducer', () => {
  it('updates epic status to ready', () => {
    const state = {
      ...initialState,
      epics: [
        { epic_number: 100, status: 'active', title: 'Epic A' },
        { epic_number: 200, status: 'active', title: 'Epic B' },
      ],
    }
    const next = reducer(state, { type: 'EPIC_READY', data: { epic_number: 100 } })
    expect(next.epics.find(e => e.epic_number === 100).status).toBe('ready')
    expect(next.epics.find(e => e.epic_number === 200).status).toBe('active')
  })

  it('returns unchanged state when epic_number is missing', () => {
    const state = { ...initialState, epics: [{ epic_number: 100, status: 'active' }] }
    const next = reducer(state, { type: 'EPIC_READY', data: {} })
    expect(next.epics[0].status).toBe('active')
  })
})

describe('EPIC_RELEASING reducer', () => {
  it('sets epicReleasing and updates epic status', () => {
    const state = {
      ...initialState,
      epics: [{ epic_number: 100, status: 'ready', title: 'Epic A' }],
      epicReleasing: null,
    }
    const next = reducer(state, {
      type: 'EPIC_RELEASING',
      data: { epic_number: 100, progress: 2, total: 5 },
    })
    expect(next.epicReleasing).toEqual({ epicNumber: 100, progress: 2, total: 5 })
    expect(next.epics[0].status).toBe('releasing')
  })

  it('returns unchanged state when epic_number is missing', () => {
    const state = { ...initialState, epicReleasing: null }
    const next = reducer(state, { type: 'EPIC_RELEASING', data: {} })
    expect(next.epicReleasing).toBeNull()
  })

  it('clears epicReleasing when data is null (release failure revert)', () => {
    const state = {
      ...initialState,
      epicReleasing: { epicNumber: 100, progress: 0, total: 0 },
    }
    const next = reducer(state, { type: 'EPIC_RELEASING', data: null })
    expect(next.epicReleasing).toBeNull()
  })
})

describe('EPIC_RELEASED reducer', () => {
  it('clears epicReleasing and updates epic status to released', () => {
    const state = {
      ...initialState,
      epics: [{ epic_number: 100, status: 'releasing', title: 'Epic A' }],
      epicReleasing: { epicNumber: 100, progress: 5, total: 5 },
    }
    const next = reducer(state, {
      type: 'EPIC_RELEASED',
      data: { epic_number: 100, version: 'v1.2.0', released_at: '2026-03-01T00:00:00Z' },
    })
    expect(next.epicReleasing).toBeNull()
    expect(next.epics[0].status).toBe('released')
    expect(next.epics[0].version).toBe('v1.2.0')
    expect(next.epics[0].released_at).toBe('2026-03-01T00:00:00Z')
  })

  it('returns unchanged state when epic_number is missing', () => {
    const state = { ...initialState, epicReleasing: { epicNumber: 100, progress: 3, total: 5 } }
    const next = reducer(state, { type: 'EPIC_RELEASED', data: {} })
    expect(next.epicReleasing).toEqual({ epicNumber: 100, progress: 3, total: 5 })
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

describe('SELECT_REPO reducer', () => {
  it('normalizes owner/repo slugs for filtering', () => {
    const result = reducer(initialState, {
      type: 'SELECT_REPO',
      data: { slug: '8thlight/insightmesh' },
    })
    expect(result.selectedRepoSlug).toBe('8thlight-insightmesh')
    expect(result.selectedSessionId).toBeNull()
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
      sessionPrsCount: 3,
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
    expect(next.sessionPrsCount).toBe(0)
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
    }

    const next = reducer(dirtyState, {
      type: 'orchestrator_status',
      data: { status: 'running' },
      timestamp: '2026-01-01T00:00:00Z',
    })

    // State preserved — this is a reconnect to an already-running orchestrator
    expect(next.workers).toEqual(dirtyState.workers)
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
      sessionPrsCount: 5,
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
    expect(next.sessionPrsCount).toBe(0)
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
  })
})
