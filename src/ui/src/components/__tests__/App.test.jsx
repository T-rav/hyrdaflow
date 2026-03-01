import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react'
import { tabActiveStyle, tabInactiveStyle, hitlBadgeStyle, epicsBadgeStyle } from '../../App'

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
      mergedCount: 0,
      sessionTriaged: 0,
      sessionPlanned: 0,
      sessionImplemented: 0,
      sessionReviewed: 0,
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
      toggleBgWorker: () => {},
      systemAlert: null,
      sessions: [],
      currentSessionId: null,
      selectedSessionId: null,
      selectedSession: null,
      selectSession: () => {},
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
  mockState.resetSession = undefined
  mockState.metrics = null
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
    expect(screen.getByText('Background Workers')).toBeInTheDocument()
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

describe('Main tab bar', () => {
  it('has exactly 6 main tabs', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    const tabLabels = ['Delivery Queue', 'Work Stream', 'HITL', 'Epics', 'Outcomes', 'System']
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

  it('Delivery Queue tab is rendered first (tab order)', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    const tabContainer = screen.getByTestId('main-tabs')
    expect(tabContainer.firstElementChild.textContent).toBe('Delivery Queue')
  })

  it('Delivery Queue is the default tab', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    const deliveryQueueTab = screen.getByText('Delivery Queue')
    expect(deliveryQueueTab.style.color).toBe('var(--accent)')
  })
})

describe('Start button dispatches session reset', () => {
  it('calls resetSession when Start is clicked', async () => {
    const resetMock = vi.fn()
    mockState.resetSession = resetMock
    mockState.orchestratorStatus = 'idle'
    const { default: App } = await import('../../App')
    render(<App />)

    fireEvent.click(screen.getByText('Start'))
    expect(resetMock).toHaveBeenCalledTimes(1)

    // Restore
    mockState.orchestratorStatus = 'running'
  })
})

describe('EventLog panel', () => {
  it('renders EventLog panel with data-testid', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    expect(screen.getByTestId('event-log-panel')).toBeInTheDocument()
  })

  it('EventLog panel is visible on all main tabs', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    const tabs = ['Delivery Queue', 'Work Stream', 'HITL', 'Epics', 'Outcomes', 'System']
    for (const tabLabel of tabs) {
      fireEvent.click(screen.getByRole('tab', { name: tabLabel }))
      expect(screen.getByTestId('event-log-panel')).toBeVisible()
    }
  })

  it('EventLog panel has fixed 320px width', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    const wrapper = screen.getByTestId('event-log-wrapper')
    expect(wrapper.style.width).toBe('320px')
    expect(wrapper.style.flexShrink).toBe('0')
  })

  it('shows empty state when no events', async () => {
    mockState.events = []
    const { default: App } = await import('../../App')
    render(<App />)
    expect(screen.getByText('Waiting for events...')).toBeInTheDocument()
  })

  it('renders events passed from context', async () => {
    mockState.events = [
      { type: 'error', timestamp: new Date().toISOString(), data: { message: 'test error' } },
    ]
    const { default: App } = await import('../../App')
    render(<App />)
    const panel = screen.getByTestId('event-log-panel')
    expect(within(panel).getByText('test error')).toBeInTheDocument()
    expect(within(panel).getByText('[system]')).toBeInTheDocument()
  })
})

describe('Epics tab and badge', () => {
  it('clicking Epics tab shows EpicDashboard', async () => {
    const { default: App } = await import('../../App')
    render(<App />)
    fireEvent.click(screen.getByRole('tab', { name: 'Epics' }))
    expect(screen.getByTestId('epic-dashboard')).toBeInTheDocument()
  })

  it('shows epic badge when active epics exist', async () => {
    mockState.epics = [
      { epic_number: 1, title: 'E1', status: 'active', total_children: 2, merged_children: 0, children: [] },
      { epic_number: 2, title: 'E2', status: 'active', total_children: 1, merged_children: 0, children: [] },
    ]
    const { default: App } = await import('../../App')
    render(<App />)
    const epicsTab = screen.getByRole('tab', { name: /Epics/ })
    const badge = epicsTab.querySelector('span')
    expect(badge).not.toBeNull()
    expect(badge.textContent).toBe('2')
  })

  it('shows no epic badge when no active epics', async () => {
    mockState.epics = [
      { epic_number: 1, title: 'E1', status: 'released', total_children: 1, merged_children: 1, children: [] },
    ]
    const { default: App } = await import('../../App')
    render(<App />)
    const epicsTab = screen.getByRole('tab', { name: 'Epics' })
    expect(epicsTab.querySelector('span')).toBeNull()
  })

  it('epicsBadgeStyle has purple background and white text', () => {
    expect(epicsBadgeStyle).toMatchObject({
      background: 'var(--purple)',
      color: 'var(--white)',
    })
  })

  it('epicsBadgeStyle has pill-shaped properties', () => {
    expect(epicsBadgeStyle).toMatchObject({
      fontSize: 10,
      fontWeight: 700,
      borderRadius: 10,
      padding: '1px 6px',
      marginLeft: 6,
    })
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
