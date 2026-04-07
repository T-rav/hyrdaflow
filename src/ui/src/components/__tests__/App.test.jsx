import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, cleanup, within, waitFor, act } from '@testing-library/react'
import { tabActiveStyle, tabInactiveStyle, hitlBadgeStyle } from '../../App'

const { mockState } = vi.hoisted(() => {
  const emptyStage = { issueCount: 0, activeCount: 0, queuedCount: 0, workerCount: 0, enabled: true, sessionCount: 0 }
  return {
    mockState: {
      workers: {
        1: { status: 'running', title: 'Test issue', branch: 'test-1', worker: 0, role: 'implementer', transcript: ['line 1'] },
      },
      prs: [],
      events: [],
      connected: true,
      orchestratorStatus: 'running',
      sessionPrsCount: 0,
      config: {},
      phase: 'implement',
      lifetimeStats: null,
      hitlItems: [],
      humanInputRequests: {},
      submitHumanInput: () => {},
      refreshHitl: () => {},
      backgroundWorkers: [],
      metrics: null,
      githubMetrics: null,
      metricsHistory: null,
      intents: [],
      epics: [],
      submitIntent: () => {},
      startOrchestrator: () => {},
      stopOrchestrator: () => {},
      toggleBgWorker: () => {},
      systemAlert: null,
      dismissSystemAlert: vi.fn(),
      refreshCreditStatus: vi.fn().mockResolvedValue({ ok: true, status: 'resuming' }),
      sessions: [],
      currentSessionId: null,
      selectedSessionId: null,
      selectedSession: null,
      selectSession: () => {},
      issueHistory: null,
      harnessInsights: null,
      reviewInsights: null,
      retrospectives: null,
      troubleshooting: null,
      memories: null,
      trackedReports: [],
      updateTrackedReport: () => {},
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [],
        review: [],
        hitl: [],
      },
      pipelinePollerLastRun: null,
      stageStatus: {
        triage: { ...emptyStage },
        plan: { ...emptyStage },
        implement: { ...emptyStage, workerCount: 1 },
        review: { ...emptyStage },
        merged: { ...emptyStage },
        workload: { total: 1, active: 1, done: 0, failed: 0 },
      },
    },
  }
})

vi.mock('../../context/HydraFlowContext', () => ({
  HydraFlowProvider: ({ children }) => children,
  useHydraFlow: () => mockState,
}))

beforeEach(() => {
  global.fetch = vi.fn(() => Promise.resolve({ ok: true, json: async () => [] }))
  mockState.hitlItems = []
  mockState.prs = []
  mockState.events = []
  mockState.epics = []
  mockState.metrics = null
  mockState.config = {}
  mockState.orchestratorStatus = 'running'
  mockState.systemAlert = null
  mockState.refreshCreditStatus = vi.fn().mockResolvedValue({ ok: true, status: 'resuming' })
  mockState.dismissSystemAlert = vi.fn()
  cleanup()
})

describe('HITL badge rendering', () => {
  it('shows no badge when hitlItems is empty', async () => {
    const { default: App } = await import('../../App')
    render(<App />)

    const hitlTab = screen.getByText('HITL')
    expect(hitlTab.querySelector('span')).toBeNull()
  })

  it('shows badge with count when hitlItems has entries', async () => {
    mockState.hitlItems = [
      { issue: 1, title: 'Bug A', pr: 10, branch: 'fix-a', issueUrl: '#', prUrl: '#' },
      { issue: 2, title: 'Bug B', pr: 11, branch: 'fix-b', issueUrl: '#', prUrl: '#' },
      { issue: 3, title: 'Bug C', pr: 12, branch: 'fix-c', issueUrl: '#', prUrl: '#' },
    ]
    const { default: App } = await import('../../App')
    render(<App />)

    expect(screen.getByText('3')).toBeInTheDocument()
  })
})

describe('Layout min-width', () => {
  it('root layout has minWidth to prevent overlap at narrow viewports', async () => {
    const { default: App } = await import('../../App')
    const { container } = render(<App />)
    const layout = container.firstChild
    expect(layout.style.minWidth).toBe('1080px')
  })
})

describe('App pre-computed tab styles', () => {
  it('tabInactiveStyle has base tab properties', () => {
    expect(tabInactiveStyle).toMatchObject({
      padding: '10px 20px',
      fontSize: 12,
      fontWeight: 600,
      color: 'var(--text-muted)',
      cursor: 'pointer',
      borderBottom: '2px solid transparent',
    })
  })

  it('tabActiveStyle includes both tab and tabActive properties', () => {
    expect(tabActiveStyle).toMatchObject({
      padding: '10px 20px',
      fontSize: 12,
      fontWeight: 600,
      color: 'var(--accent)',
      cursor: 'pointer',
      borderBottom: '2px solid var(--accent)',
    })
  })

  it('tabActiveStyle overrides color from tabActive', () => {
    expect(tabActiveStyle.color).toBe('var(--accent)')
  })

  it('style objects are referentially stable', () => {
    expect(tabActiveStyle).toBe(tabActiveStyle)
    expect(tabInactiveStyle).toBe(tabInactiveStyle)
    expect(hitlBadgeStyle).toBe(hitlBadgeStyle)
  })

  describe('hitlBadgeStyle', () => {
    it('has red background and white text', () => {
      expect(hitlBadgeStyle).toMatchObject({
        background: 'var(--red)',
        color: 'var(--white)',
      })
    })

    it('has pill-shaped badge properties', () => {
      expect(hitlBadgeStyle).toMatchObject({
        fontSize: 10,
        fontWeight: 700,
        borderRadius: 10,
        padding: '1px 6px',
        marginLeft: 6,
      })
    })
  })
})

describe('System and Metrics tabs', () => {
  it('renders System tab and hides Metrics tab in main nav', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    expect(screen.getByText('System')).toBeInTheDocument()
    expect(screen.queryByText('Metrics')).not.toBeInTheDocument()
  })

  it('clicking System tab shows SystemPanel content', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    fireEvent.click(screen.getByText('System'))
    expect(screen.getByText('Repo Health')).toBeInTheDocument()
  })

  it('metrics still accessible from System tab sub-navigation', async () => {
    mockState.metrics = {
      lifetime: { issues_completed: 5, prs_merged: 3, issues_created: 1 },
      rates: {},
    }
    const { default: App } = await import('../../App')
    render(<App />)
    fireEvent.click(screen.getByText('System'))
    fireEvent.click(screen.getByText('Metrics'))
    expect(screen.getByText('Lifetime')).toBeInTheDocument()
  })
})

describe('Config warning banner', () => {
  it('shows warning for likely repo typo configuration', async () => {
    mockState.config = {
      repo: 'T-rav/hyrda',
      find_label: ['hydra-find'],
      planner_label: ['hydra-plan'],
      ready_label: ['hydra-ready'],
      review_label: ['hydra-review'],
      hitl_label: ['hydra-hitl'],
    }
    const { default: App } = await import('../../App')
    render(<App />)
    expect(screen.getByTestId('config-warning-banner')).toBeInTheDocument()
    expect(screen.getByText(/This looks like a typo and can prevent issue pickup/)).toBeInTheDocument()
  })

  it('does not warn when labels use one consistent family', async () => {
    mockState.config = {
      repo: 'T-rav/hydraflow',
      find_label: ['hydraflow-find'],
      planner_label: ['hydraflow-plan'],
      ready_label: ['hydraflow-ready'],
      review_label: ['hydraflow-review'],
      hitl_label: ['hydraflow-hitl'],
    }
    const { default: App } = await import('../../App')
    render(<App />)
    expect(screen.queryByTestId('config-warning-banner')).toBeNull()
  })
})

describe('Main tab bar', () => {
  it('has exactly 4 main tabs', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    const tabLabels = ['Work Stream', 'HITL', 'Outcomes', 'Diagnostics', 'System']
    const tabContainer = screen.getByTestId('main-tabs')
    expect(tabContainer.childElementCount).toBe(tabLabels.length)
    for (const label of tabLabels) {
      expect(within(tabContainer).getByText(label)).toBeInTheDocument()
    }
  })

  it('does not render Transcript in the main tab bar', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    expect(screen.queryByText('Transcript')).not.toBeInTheDocument()
  })

  it('does not include Livestream in the main tab bar', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    // Livestream is now a sub-tab inside System, not a top-level tab
    expect(screen.queryByText('Livestream')).not.toBeInTheDocument()
  })

  it('Work Stream tab is rendered first (tab order)', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    const tabContainer = screen.getByTestId('main-tabs')
    expect(tabContainer.firstElementChild.textContent).toBe('Work Stream')
  })

  it('Work Stream is the default tab', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    const workStreamTab = screen.getByText('Work Stream')
    expect(workStreamTab.style.color).toBe('var(--accent)')
  })
})

describe('Header renders main Start/Stop controls', () => {
  it('renders Start when orchestrator is idle', async () => {
    mockState.orchestratorStatus = 'idle'
    const { default: App } = await import('../../App')
    render(<App />)
    expect(screen.getByText('Start')).toBeInTheDocument()
    mockState.orchestratorStatus = 'running'
  })

  it('renders Stop when orchestrator is running', async () => {
    mockState.orchestratorStatus = 'running'
    const { default: App } = await import('../../App')
    render(<App />)
    expect(screen.getByText('Stop')).toBeInTheDocument()
  })
})


describe('SystemAlertBanner', () => {
  it('renders alert message without resume time when resume_at is absent', async () => {
    mockState.systemAlert = { message: 'Something happened.', source: 'plan' }
    const { default: App } = await import('../../App')
    render(<App />)
    expect(screen.getByText(/Something happened\./)).toBeInTheDocument()
    expect(screen.queryByText(/Resumes at/)).toBeNull()
    mockState.systemAlert = null
  })

  it('appends local resume time when resume_at is present', async () => {
    // Use a time later today so formatResumeAt shows time-only format
    const now = new Date()
    now.setHours(23, 59, 0, 0)
    mockState.systemAlert = {
      message: 'Credit limit reached. Pausing all loops.',
      source: 'plan',
      resume_at: now.toISOString(),
    }
    const { default: App } = await import('../../App')
    render(<App />)
    expect(screen.getByText(/Resumes at/)).toBeInTheDocument()
    mockState.systemAlert = null
  })

  it('shows date when resume_at is a different day', async () => {
    // Use a date far in the future to guarantee it's not today
    mockState.systemAlert = {
      message: 'Credit limit reached.',
      source: 'plan',
      resume_at: '2099-06-15T10:00:00+00:00',
    }
    const { default: App } = await import('../../App')
    render(<App />)
    expect(screen.getByText(/Resumes at/)).toBeInTheDocument()
    // Should include month abbreviation for cross-day display
    expect(screen.getByText(/Jun/)).toBeInTheDocument()
    mockState.systemAlert = null
  })

  it('handles invalid resume_at gracefully', async () => {
    mockState.systemAlert = {
      message: 'Credit limit reached.',
      source: 'plan',
      resume_at: 'not-a-date',
    }
    const { default: App } = await import('../../App')
    render(<App />)
    expect(screen.getByText(/Credit limit reached\./)).toBeInTheDocument()
    expect(screen.queryByText(/Resumes at/)).toBeNull()
    mockState.systemAlert = null
  })
})

describe('SystemAlertBanner refresh button', () => {
  it('shows Refresh button for credit limit alerts', async () => {
    mockState.systemAlert = {
      message: 'Credit limit reached. Pausing all loops.',
      source: 'implement',
      resume_at: '2099-06-15T10:00:00+00:00',
    }
    const { default: App } = await import('../../App')
    render(<App />)
    expect(screen.getByText('Refresh')).toBeInTheDocument()
    mockState.systemAlert = null
  })

  it('does not show Refresh button for non-credit alerts', async () => {
    mockState.systemAlert = {
      message: 'Auth failed. Check your API key.',
      source: 'plan',
    }
    const { default: App } = await import('../../App')
    render(<App />)
    expect(screen.queryByText('Refresh')).toBeNull()
    mockState.systemAlert = null
  })

  it('shows Checking... while refresh is in progress', async () => {
    let resolveRefresh
    mockState.refreshCreditStatus = vi.fn(() => new Promise(r => { resolveRefresh = r }))
    mockState.systemAlert = {
      message: 'Credit limit reached. Pausing all loops.',
      source: 'plan',
    }
    const { default: App } = await import('../../App')
    render(<App />)
    await act(async () => {
      fireEvent.click(screen.getByText('Refresh'))
    })
    expect(screen.getByText('Checking...')).toBeInTheDocument()
    await act(async () => {
      resolveRefresh({ ok: true, status: 'resuming' })
    })
    mockState.systemAlert = null
  })

  it('shows "Credits still exhausted" when refresh returns still_exhausted', async () => {
    mockState.refreshCreditStatus = vi.fn().mockResolvedValue({ ok: true, status: 'still_exhausted' })
    mockState.systemAlert = {
      message: 'Credit limit reached. Pausing all loops.',
      source: 'plan',
    }
    const { default: App } = await import('../../App')
    render(<App />)
    await act(async () => {
      fireEvent.click(screen.getByText('Refresh'))
    })
    await waitFor(() => {
      expect(screen.getByText('Credits still exhausted')).toBeInTheDocument()
    })
    mockState.systemAlert = null
  })

  it('shows "Refresh failed" when refreshCreditStatus returns an error', async () => {
    mockState.refreshCreditStatus = vi.fn().mockResolvedValue({ ok: false, status: 'error' })
    mockState.systemAlert = {
      message: 'Credit limit reached. Pausing all loops.',
      source: 'plan',
    }
    const { default: App } = await import('../../App')
    render(<App />)
    await act(async () => {
      fireEvent.click(screen.getByText('Refresh'))
    })
    await waitFor(() => {
      expect(screen.getByText('Refresh failed')).toBeInTheDocument()
    })
    mockState.systemAlert = null
  })

  it('calls refreshCreditStatus when Refresh is clicked', async () => {
    const mockRefresh = vi.fn().mockResolvedValue({ ok: true, status: 'resuming' })
    mockState.refreshCreditStatus = mockRefresh
    mockState.systemAlert = {
      message: 'Credit limit reached. Pausing all loops.',
      source: 'plan',
    }
    const { default: App } = await import('../../App')
    render(<App />)
    await act(async () => {
      fireEvent.click(screen.getByText('Refresh'))
    })
    expect(mockRefresh).toHaveBeenCalledTimes(1)
    mockState.systemAlert = null
  })
})

describe('Pipeline sub-tab under System', () => {
  it('Pipeline is accessible as a sub-tab under System', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    fireEvent.click(screen.getByText('System'))
    // Pipeline sub-tab should be visible
    expect(screen.getByText('Pipeline')).toBeInTheDocument()
  })

  it('clicking Pipeline sub-tab shows pipeline controls', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    fireEvent.click(screen.getByText('System'))
    fireEvent.click(screen.getByText('Pipeline'))
    expect(screen.getByText('Pipeline Controls')).toBeInTheDocument()
  })
})
