import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within, waitFor } from '@testing-library/react'
import { BACKGROUND_WORKERS } from '../../constants'
import { deriveStageStatus } from '../../hooks/useStageStatus'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

// Import SystemPanel after mock is set up
const { SystemPanel } = await import('../SystemPanel')

function defaultMockContext(overrides = {}) {
  const pipelineIssues = overrides.pipelineIssues || {}
  const workers = overrides.workers || {}
  const backgroundWorkers = overrides.backgroundWorkers || []
  return {
    pipelinePollerLastRun: null,
    orchestratorStatus: 'idle',
    stageStatus: deriveStageStatus(pipelineIssues, workers, backgroundWorkers, {}),
    events: [],
    metrics: null,
    metricsHistory: null,
    githubMetrics: null,
    ...overrides,
  }
}

beforeEach(() => {
  mockUseHydraFlow.mockReturnValue(defaultMockContext())
})

const mockBgWorkers = [
  { name: 'triage', status: 'ok', enabled: true, last_run: null, details: {} },
  { name: 'plan', status: 'ok', enabled: true, last_run: null, details: {} },
  { name: 'implement', status: 'ok', enabled: true, last_run: null, details: {} },
  { name: 'review', status: 'ok', enabled: true, last_run: null, details: {} },
  { name: 'memory_sync', status: 'ok', enabled: true, last_run: new Date().toISOString(), details: { item_count: 12, digest_chars: 2400 } },
  { name: 'retrospective', status: 'error', enabled: true, last_run: '2026-02-20T10:28:00Z', details: { last_issue: 42 } },
  { name: 'metrics', status: 'ok', enabled: true, last_run: '2026-02-20T10:25:00Z', details: {} },
  { name: 'review_insights', status: 'disabled', enabled: false, last_run: null, details: {} },
]

describe('SystemPanel', () => {
  describe('Sub-tabs', () => {
    it('includes Metrics sub-tab when viewing system panel', () => {
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      expect(screen.getByText('Metrics')).toBeInTheDocument()
    })

    it('renders MetricsPanel content when Metrics sub-tab selected', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        metrics: {
          lifetime: { issues_completed: 2, prs_merged: 1 },
        },
      }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      fireEvent.click(screen.getByText('Metrics'))
      expect(screen.getByText('Lifetime')).toBeInTheDocument()
    })

    it('mounts MetricsPanel as the direct scroll container (empty state)', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext())
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      fireEvent.click(screen.getByText('Metrics'))
      const subTabContent = screen.getByTestId('system-subtab-content')
      const metricsPanel = screen.getByTestId('metrics-panel-root')
      expect(metricsPanel.parentElement).toBe(subTabContent)
      expect(metricsPanel.style.overflowY).toBe('auto')
    })

    it('mounts MetricsPanel as the direct scroll container (populated state)', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        githubMetrics: { total_closed: 10, total_merged: 8, open_by_label: {} },
      }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      fireEvent.click(screen.getByText('Metrics'))
      const subTabContent = screen.getByTestId('system-subtab-content')
      const metricsPanel = screen.getByTestId('metrics-panel-root')
      expect(metricsPanel.parentElement).toBe(subTabContent)
      expect(metricsPanel.style.overflowY).toBe('auto')
    })
  })

  describe('Background Workers', () => {
    it('renders all background worker cards (including system workers)', () => {
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      for (const def of BACKGROUND_WORKERS) {
        expect(screen.getByText(def.label)).toBeInTheDocument()
      }
    })

    it('shows correct status dot color for ok workers when orchestrator running', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running' }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      const dot = screen.getByTestId('dot-memory_sync')
      expect(dot.style.background).toBe('var(--green)')
    })

    it('shows correct status dot color for error workers when orchestrator running', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running' }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      const dot = screen.getByTestId('dot-retrospective')
      expect(dot.style.background).toBe('var(--red)')
    })

    it('shows "idle" (yellow) for enabled non-system workers and "stopped" (red) for system workers when orchestrator not running', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      const nonSystem = BACKGROUND_WORKERS.filter(w => !w.system)
      const systemWorkers = BACKGROUND_WORKERS.filter(w => w.system)
      const idleTexts = screen.getAllByText('idle')
      expect(idleTexts.length).toBe(nonSystem.length)
      for (const def of nonSystem) {
        const dot = screen.getByTestId(`dot-${def.key}`)
        expect(dot.style.background).toBe('var(--yellow)')
      }
      const stoppedTexts = screen.getAllByText('stopped')
      expect(stoppedTexts.length).toBe(systemWorkers.length)
      for (const def of systemWorkers) {
        const dot = screen.getByTestId(`dot-${def.key}`)
        expect(dot.style.background).toBe('var(--red)')
      }
    })

    it('shows ok/error status when orchestrator is running', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        pipelinePollerLastRun: '2026-02-20T10:00:00Z',
        orchestratorStatus: 'running',
      }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      const okDot = screen.getByTestId('dot-memory_sync')
      expect(okDot.style.background).toBe('var(--green)')
      const errDot = screen.getByTestId('dot-retrospective')
      expect(errDot.style.background).toBe('var(--red)')
      const offDot = screen.getByTestId('dot-review_insights')
      expect(offDot.style.background).toBe('var(--red)')
    })

    it('shows last run time when available', () => {
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      expect(screen.getAllByText(/Last run:/).length).toBeGreaterThanOrEqual(BACKGROUND_WORKERS.length)
    })

    it('shows "never" for workers that have not run', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      const neverTexts = screen.getAllByText(/never/)
      expect(neverTexts.length).toBeGreaterThanOrEqual(BACKGROUND_WORKERS.length)
    })

    it('renders worker descriptions', () => {
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      for (const def of BACKGROUND_WORKERS) {
        expect(screen.getByTestId(`desc-${def.key}`)).toHaveTextContent(def.description)
      }
    })

    it('shows detail key-value pairs', () => {
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      expect(screen.getByText('item count')).toBeInTheDocument()
      expect(screen.getByText('12')).toBeInTheDocument()
      expect(screen.getByText('digest chars')).toBeInTheDocument()
      expect(screen.getByText('2400')).toBeInTheDocument()
    })

    it('shows inference/pruning details from worker payloads', () => {
      const workers = mockBgWorkers.map(worker => (
        worker.name === 'memory_sync'
          ? {
              ...worker,
              details: {
                inference_calls: 4,
                total_tokens: 1300,
                pruned_chars_total: 2000,
                saved_tokens_est: 500,
                unpruned_tokens_est: 1800,
              },
            }
          : worker
      ))
      render(<SystemPanel backgroundWorkers={workers} />)
      expect(screen.getByText('inference calls')).toBeInTheDocument()
      expect(screen.getByText('total tokens')).toBeInTheDocument()
      expect(screen.getByText('pruned chars total')).toBeInTheDocument()
      expect(screen.getByText('saved tokens est')).toBeInTheDocument()
      expect(screen.getByText('unpruned tokens est')).toBeInTheDocument()
    })

    it('shows System section heading that groups system workers', () => {
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      expect(screen.getByText('System')).toBeInTheDocument()
    })

    it('shows system worker status as colored pill (green for ok) when orchestrator running', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running' }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      const okPill = screen.getByTestId('status-pill-memory_sync')
      expect(okPill).toHaveTextContent('ok')
      expect(okPill.style.color).toBe('var(--green)')
      expect(okPill.style.background).toBe('var(--green-subtle)')
      const metricsPill = screen.getByTestId('status-pill-metrics')
      expect(metricsPill).toHaveTextContent('ok')
      expect(metricsPill.style.color).toBe('var(--green)')
    })

    it('shows red pill for stopped system workers', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      const pollerPill = screen.getByTestId('status-pill-pipeline_poller')
      expect(pollerPill).toHaveTextContent('stopped')
      expect(pollerPill.style.color).toBe('var(--red)')
      expect(pollerPill.style.background).toBe('var(--red-subtle)')
    })
  })

  describe('Error Display', () => {
    it('shows error details with red styling when status is error', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running' }))
      const errorWorkers = [
        { name: 'retrospective', status: 'error', enabled: true, last_run: '2026-02-20T10:28:00Z', details: { error: 'Connection timeout', retries: 3 } },
      ]
      render(<SystemPanel backgroundWorkers={errorWorkers} />)
      expect(screen.getByText('Connection timeout')).toBeInTheDocument()
      expect(screen.getAllByText('3').length).toBeGreaterThanOrEqual(1)
    })

    it('shows error key in details section', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running' }))
      const errorWorkers = [
        { name: 'retrospective', status: 'error', enabled: true, last_run: null, details: { error: 'API rate limited' } },
      ]
      render(<SystemPanel backgroundWorkers={errorWorkers} />)
      expect(screen.getByText('API rate limited')).toBeInTheDocument()
      const errorTexts = screen.getAllByText('error')
      expect(errorTexts.length).toBeGreaterThanOrEqual(2)
    })
  })

    describe('Background Worker Toggles', () => {
    it('shows toggle buttons for non-system workers only when onToggleBgWorker provided', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running', backgroundWorkers: mockBgWorkers }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} onToggleBgWorker={() => {}} />)
      const onButtons = screen.getAllByText('On')
      // Only non-system background workers that are enabled (no pipeline loops here)
      const nonSystemEnabled = BACKGROUND_WORKERS.filter(def => {
        if (def.system) return false
        const state = mockBgWorkers.find(w => w.name === def.key)
        return state?.enabled !== false
      }).length
      expect(onButtons.length).toBe(nonSystemEnabled)
    })

    it('system workers do not show toggle buttons', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running', backgroundWorkers: mockBgWorkers }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} onToggleBgWorker={() => {}} />)
      expect(screen.getByText('Pipeline Poller')).toBeInTheDocument()
      expect(screen.getByText('Memory Manager')).toBeInTheDocument()
      expect(screen.getByText('Metrics Munger')).toBeInTheDocument()
      // Count On/Off buttons — should be non-system bg workers + memory auto-approve (process toggles are on Processes tab)
      const allToggleButtons = [...screen.getAllByText('On'), ...screen.getAllByText('Off')]
      const nonSystemBgCount = BACKGROUND_WORKERS.filter(w => !w.system).length
      expect(allToggleButtons.length).toBe(nonSystemBgCount + 1)
    })

    it('does not show toggle buttons when onToggleBgWorker is not provided', () => {
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      // No worker toggle On buttons, but memory auto-approve shows Off (process toggles on Processes tab)
      expect(screen.queryByText('On')).not.toBeInTheDocument()
      const offButtons = screen.getAllByText('Off')
      expect(offButtons.length).toBe(1) // memory auto-approve only
    })

    it('shows Off button for disabled workers when orchestrator running', () => {
      const onToggle = vi.fn()
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running', backgroundWorkers: mockBgWorkers }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} onToggleBgWorker={onToggle} />)
      const offButtons = screen.getAllByText('Off')
      expect(offButtons.length).toBeGreaterThanOrEqual(1)
    })

    it('clicking Off toggles to enabled', () => {
      const onToggle = vi.fn()
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running', backgroundWorkers: mockBgWorkers }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} onToggleBgWorker={onToggle} />)
      const reviewInsightsCard = screen.getByTestId('worker-card-review_insights')
      fireEvent.click(within(reviewInsightsCard).getByText('Off'))
      expect(onToggle).toHaveBeenCalledWith('review_insights', true)
    })

    it('non-system workers show On when orchestrator running and no state reported', () => {
      const onToggle = vi.fn()
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running' }))
      render(<SystemPanel backgroundWorkers={[]} onToggleBgWorker={onToggle} />)
      const onButtons = screen.getAllByText('On')
      const nonSystemCount = BACKGROUND_WORKERS.filter(w => !w.system).length
      // Only non-system background workers (no pipeline loops)
      expect(onButtons.length).toBe(nonSystemCount)
    })

    it('non-system workers show On (default enabled) when orchestrator not running and no state', () => {
      const onToggle = vi.fn()
      render(<SystemPanel backgroundWorkers={[]} onToggleBgWorker={onToggle} />)
      const onButtons = screen.getAllByText('On')
      const nonSystemCount = BACKGROUND_WORKERS.filter(w => !w.system).length
      // Only non-system background workers (no pipeline loops)
      expect(onButtons.length).toBe(nonSystemCount)
    })

    it('non-system workers show Off when explicitly disabled and orchestrator not running', () => {
      const onToggle = vi.fn()
      const disabledWorkers = [
        { name: 'retrospective', status: 'ok', enabled: false, last_run: null, details: {} },
        { name: 'review_insights', status: 'ok', enabled: false, last_run: null, details: {} },
      ]
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ backgroundWorkers: disabledWorkers }))
      render(<SystemPanel backgroundWorkers={disabledWorkers} onToggleBgWorker={onToggle} />)
      const offButtons = screen.getAllByText('Off')
      // 2 disabled workers + 1 memory auto-approve (process toggles on Processes tab)
      expect(offButtons.length).toBe(3)
    })
  })

  describe('Memory Auto-Approve toggle location', () => {
    it('renders the auto-approve toggle inside the Memory Manager card', () => {
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      // Assert: toggle is contained within the memory_sync worker card
      const memoryCard = screen.getByTestId('worker-card-memory_sync')
      expect(within(memoryCard).getByTestId('memory-auto-approve-toggle')).toBeInTheDocument()
    })

    it('does not render the auto-approve toggle outside the Memory Manager card', () => {
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      const toggle = screen.getByTestId('memory-auto-approve-toggle')
      const memoryCard = screen.getByTestId('worker-card-memory_sync')
      // Toggle must be inside the memory_sync card, not in any other card
      expect(memoryCard).toContainElement(toggle)
      const otherCards = BACKGROUND_WORKERS
        .filter(w => w.key !== 'memory_sync')
        .map(w => screen.queryByTestId(`worker-card-${w.key}`))
        .filter(Boolean)
      for (const card of otherCards) {
        expect(card).not.toContainElement(toggle)
      }
    })
  })

  describe('Pipeline Poller status', () => {
    it('shows green dot and ok when orchestrator is running and poller has run', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        pipelinePollerLastRun: '2026-02-20T10:00:00Z',
        orchestratorStatus: 'running',
      }))
      render(<SystemPanel backgroundWorkers={[]} />)
      const dot = screen.getByTestId('dot-pipeline_poller')
      expect(dot.style.background).toBe('var(--green)')
    })

    it('shows red stopped when orchestrator is not running even if poller has lastRun', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        pipelinePollerLastRun: '2026-02-20T10:00:00Z',
        orchestratorStatus: 'idle',
      }))
      render(<SystemPanel backgroundWorkers={[]} />)
      const dot = screen.getByTestId('dot-pipeline_poller')
      expect(dot.style.background).toBe('var(--red)')
    })

    it('shows red stopped when pipeline poller has not run', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      const dot = screen.getByTestId('dot-pipeline_poller')
      expect(dot.style.background).toBe('var(--red)')
    })

    it('does not show pipeline stage counts as details when orchestrator running (log stream only)', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        pipelinePollerLastRun: '2026-02-20T10:00:00Z',
        orchestratorStatus: 'running',
        pipelineIssues: {
          triage: [{ number: 1 }],
          plan: [{ number: 2 }, { number: 3 }],
          implement: [],
          review: [{ number: 4 }],
          hitl: [{ number: 5 }],
        },
      }))
      render(<SystemPanel backgroundWorkers={[]} />)
      // Pipeline poller card should NOT show stage keys as detail labels
      expect(screen.queryByText('triage')).not.toBeInTheDocument()
      expect(screen.queryByText('total')).not.toBeInTheDocument()
    })
  })

  describe('Sub-tab Navigation', () => {
    it('shows Workers, Pipeline, Metrics, Processes, Insights, and Livestream sub-tab labels', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      expect(screen.getByText('Workers')).toBeInTheDocument()
      expect(screen.getByText('Pipeline')).toBeInTheDocument()
      expect(screen.getByText('Metrics')).toBeInTheDocument()
      expect(screen.getByText('Processes')).toBeInTheDocument()
      expect(screen.getByText('Insights')).toBeInTheDocument()
      expect(screen.getByText('Livestream')).toBeInTheDocument()
      expect(screen.queryByText('Event Log')).not.toBeInTheDocument()
    })

    it('Workers sub-tab is active by default showing background worker content', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      expect(screen.getByText('Background Workers')).toBeInTheDocument()
    })

    it('clicking Livestream sub-tab shows event stream', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      fireEvent.click(screen.getByText('Livestream'))
      expect(screen.getByText('Waiting for events...')).toBeInTheDocument()
      expect(screen.queryByText('Background Workers')).not.toBeInTheDocument()
    })

    it('clicking Workers sub-tab returns to worker content', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      fireEvent.click(screen.getByText('Livestream'))
      expect(screen.queryByText('Background Workers')).not.toBeInTheDocument()
      fireEvent.click(screen.getByText('Workers'))
      expect(screen.getByText('Background Workers')).toBeInTheDocument()
    })

    it('active sub-tab has accent color styling', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      const workersTab = screen.getByText('Workers')
      expect(workersTab.style.color).toBe('var(--accent)')
      expect(workersTab.style.borderLeftColor).toBe('var(--accent)')
      const livestreamTab = screen.getByText('Livestream')
      expect(livestreamTab.style.color).toBe('var(--text-muted)')
      expect(livestreamTab.style.borderLeftColor).toBe('transparent')
    })

    it('sub-tab styles swap when clicking Livestream', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      fireEvent.click(screen.getByText('Livestream'))
      expect(screen.getByText('Livestream').style.color).toBe('var(--accent)')
      expect(screen.getByText('Livestream').style.borderLeftColor).toBe('var(--accent)')
      expect(screen.getByText('Workers').style.color).toBe('var(--text-muted)')
      expect(screen.getByText('Workers').style.borderLeftColor).toBe('transparent')
    })

    it('clicking Processes sub-tab applies accent styling', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      fireEvent.click(screen.getByText('Processes'))
      expect(screen.getByText('Processes').style.color).toBe('var(--accent)')
      expect(screen.getByText('Processes').style.borderLeftColor).toBe('var(--accent)')
      expect(screen.getByText('Workers').style.color).toBe('var(--text-muted)')
    })

    it('clicking Pipeline sub-tab shows pipeline controls', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      fireEvent.click(screen.getByText('Pipeline'))
      expect(screen.getByText('Pipeline Controls')).toBeInTheDocument()
      expect(screen.queryByText('Background Workers')).not.toBeInTheDocument()
    })

    it('clicking Workers sub-tab after Pipeline returns to worker content', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      fireEvent.click(screen.getByText('Pipeline'))
      expect(screen.queryByText('Background Workers')).not.toBeInTheDocument()
      fireEvent.click(screen.getByText('Workers'))
      expect(screen.getByText('Background Workers')).toBeInTheDocument()
    })

    it('clicking Insights sub-tab shows InsightsPanel content', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      fireEvent.click(screen.getByText('Insights'))
      expect(screen.getByText('Failure Patterns')).toBeInTheDocument()
      expect(screen.queryByText('Background Workers')).not.toBeInTheDocument()
    })

    it('renders event data in Livestream sub-tab', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        events: [
          { timestamp: new Date().toISOString(), type: 'worker_update', data: { issue: 1, status: 'running' } },
        ],
      }))
      render(<SystemPanel backgroundWorkers={[]} />)
      fireEvent.click(screen.getByText('Livestream'))
      expect(screen.getByText('[implement]')).toBeInTheDocument()
    })

  })

  describe('Processes sub-tab', () => {
    it('clicking Processes sub-tab shows process toggles', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      fireEvent.click(screen.getByText('Processes'))
      expect(screen.getByText('Process Toggles')).toBeInTheDocument()
      expect(screen.getByTestId('auto-process-epics-toggle')).toBeInTheDocument()
      expect(screen.getByTestId('auto-process-bugs-toggle')).toBeInTheDocument()
    })

    it('Processes sub-tab hides Workers content', () => {
      render(<SystemPanel backgroundWorkers={[]} />)
      fireEvent.click(screen.getByText('Processes'))
      expect(screen.queryByText('Background Workers')).not.toBeInTheDocument()
    })

    it('process toggles do not appear on Workers tab', () => {
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      expect(screen.queryByTestId('auto-process-epics-toggle')).not.toBeInTheDocument()
      expect(screen.queryByTestId('auto-process-bugs-toggle')).not.toBeInTheDocument()
    })

    it('clicking Workers after Processes returns to worker content without process toggles', () => {
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      fireEvent.click(screen.getByText('Processes'))
      expect(screen.getByTestId('auto-process-epics-toggle')).toBeInTheDocument()
      fireEvent.click(screen.getByText('Workers'))
      expect(screen.getByText('Background Workers')).toBeInTheDocument()
      expect(screen.queryByTestId('auto-process-epics-toggle')).not.toBeInTheDocument()
    })

    it('process toggles reflect config values when enabled', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        config: { auto_process_epics: true, auto_process_bug_reports: false },
      }))
      render(<SystemPanel backgroundWorkers={[]} />)
      fireEvent.click(screen.getByText('Processes'))
      const epicsToggle = screen.getByTestId('auto-process-epics-toggle')
      const bugsToggle = screen.getByTestId('auto-process-bugs-toggle')
      expect(epicsToggle).toHaveTextContent('On')
      expect(bugsToggle).toHaveTextContent('Off')
    })

    it('clicking a process toggle calls PATCH /api/control/config with correct payload', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true })
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        config: { auto_process_epics: false, auto_process_bug_reports: false },
      }))
      render(<SystemPanel backgroundWorkers={[]} />)
      fireEvent.click(screen.getByText('Processes'))
      fireEvent.click(screen.getByTestId('auto-process-epics-toggle'))
      expect(fetchSpy).toHaveBeenCalledWith('/api/control/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_process_epics: true, persist: true }),
      })
      fetchSpy.mockRestore()
    })

    it('rolls back toggle optimistic update when PATCH returns non-ok', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: false })
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        config: { auto_process_epics: false, auto_process_bug_reports: false },
      }))
      render(<SystemPanel backgroundWorkers={[]} />)
      fireEvent.click(screen.getByText('Processes'))
      const epicsToggle = screen.getByTestId('auto-process-epics-toggle')
      fireEvent.click(epicsToggle)
      expect(epicsToggle).toHaveTextContent('On') // optimistic update applied immediately
      await waitFor(() => expect(epicsToggle).toHaveTextContent('Off')) // rolled back after failed PATCH
      fetchSpy.mockRestore()
    })

    it('clicking bug reports toggle calls PATCH /api/control/config with correct payload', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true })
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        config: { auto_process_epics: false, auto_process_bug_reports: false },
      }))
      render(<SystemPanel backgroundWorkers={[]} />)
      fireEvent.click(screen.getByText('Processes'))
      fireEvent.click(screen.getByTestId('auto-process-bugs-toggle'))
      expect(fetchSpy).toHaveBeenCalledWith('/api/control/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_process_bug_reports: true, persist: true }),
      })
      fetchSpy.mockRestore()
    })

    it('rolls back bug reports toggle optimistic update when fetch throws', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network error'))
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        config: { auto_process_epics: false, auto_process_bug_reports: false },
      }))
      render(<SystemPanel backgroundWorkers={[]} />)
      fireEvent.click(screen.getByText('Processes'))
      const bugsToggle = screen.getByTestId('auto-process-bugs-toggle')
      fireEvent.click(bugsToggle)
      expect(bugsToggle).toHaveTextContent('On') // optimistic update applied immediately
      await waitFor(() => expect(bugsToggle).toHaveTextContent('Off')) // rolled back after network error
      fetchSpy.mockRestore()
    })
  })

  describe('Worker Log Stream integration', () => {
    it('renders log stream when background_worker_status events exist for a worker', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        orchestratorStatus: 'running',
        events: [
          { timestamp: '2026-02-20T10:00:01Z', type: 'background_worker_status', data: { worker: 'memory_sync', status: 'ok', details: { items: 5 } } },
          { timestamp: '2026-02-20T10:00:00Z', type: 'background_worker_status', data: { worker: 'memory_sync', status: 'ok', details: { items: 3 } } },
        ],
      }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      expect(screen.getByTestId('worker-log-stream')).toBeInTheDocument()
    })

    it('does not render log stream when no matching events exist', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        orchestratorStatus: 'running',
        events: [
          { timestamp: '2026-02-20T10:00:00Z', type: 'worker_update', data: { issue: 1, status: 'running' } },
        ],
      }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      expect(screen.queryByTestId('worker-log-stream')).not.toBeInTheDocument()
    })

    it('does not render log stream when events array is empty', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        orchestratorStatus: 'running',
        events: [],
      }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      expect(screen.queryByTestId('worker-log-stream')).not.toBeInTheDocument()
    })

    it('renders formatted event lines with status and details separated by middle dot', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        orchestratorStatus: 'running',
        events: [
          { timestamp: '2026-02-20T10:00:00Z', type: 'background_worker_status', data: { worker: 'memory_sync', status: 'ok', details: { items: 5 } } },
        ],
      }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      const stream = screen.getByTestId('worker-log-stream')
      // Formatted line includes status and details joined by middle dot (·)
      expect(stream.textContent).toContain('ok · items: 5')
    })

    it('filters events by worker key so each card only shows its own events', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        orchestratorStatus: 'running',
        events: [
          { timestamp: '2026-02-20T10:00:02Z', type: 'background_worker_status', data: { worker: 'memory_sync', status: 'ok', details: { items: 5 } } },
          { timestamp: '2026-02-20T10:00:01Z', type: 'background_worker_status', data: { worker: 'metrics', status: 'ok', details: { cpu: 42 } } },
          { timestamp: '2026-02-20T10:00:00Z', type: 'background_worker_status', data: { worker: 'memory_sync', status: 'ok', details: { items: 3 } } },
        ],
      }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      const memorySyncCard = screen.getByTestId('worker-card-memory_sync')
      const memorySyncStream = within(memorySyncCard).getByTestId('worker-log-stream')
      // memory_sync card should contain its own events but not metrics events
      expect(memorySyncStream.textContent).toContain('items: 5')
      expect(memorySyncStream.textContent).toContain('items: 3')
      expect(memorySyncStream.textContent).not.toContain('cpu: 42')
    })

    it('Pipeline Poller shows log stream but no stats/details', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        orchestratorStatus: 'running',
        pipelinePollerLastRun: '2026-02-20T10:00:00Z',
        pipelineIssues: {
          triage: [{ number: 1 }],
          plan: [{ number: 2 }, { number: 3 }],
          implement: [],
          review: [{ number: 4 }],
          hitl: [{ number: 5 }],
        },
        events: [
          { timestamp: '2026-02-20T10:30:00Z', type: 'background_worker_status', data: { worker: 'pipeline_poller', status: 'ok', details: { polled: 5 } } },
        ],
      }))
      render(<SystemPanel backgroundWorkers={[]} />)
      const pollerCard = screen.getByTestId('worker-card-pipeline_poller')
      // Log stream should render inside pipeline_poller card
      expect(within(pollerCard).getByTestId('worker-log-stream')).toBeInTheDocument()
      // Pipeline stage counts should NOT render as detail rows
      expect(screen.queryByText('triage')).not.toBeInTheDocument()
      expect(screen.queryByText('total')).not.toBeInTheDocument()
    })

    it('shows both error details and log stream when error worker has events', () => {
      // Tests the detailsErrorCompact vs detailsError branching: when recentEvents.length > 0,
      // compact style must be used so the log stream below it is not visually clipped.
      const events = [
        { timestamp: '2026-02-20T10:30:00Z', type: 'background_worker_status', data: { worker: 'retrospective', status: 'error', details: { err: 'timeout' } } },
      ]
      const errorWorkers = [
        { name: 'retrospective', status: 'error', enabled: true, last_run: null, details: { error: 'Connection timeout' } },
      ]
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running', events }))
      render(<SystemPanel backgroundWorkers={errorWorkers} />)
      // Error details section must still render
      expect(screen.getByText('Connection timeout')).toBeInTheDocument()
      // Log stream must also render alongside error details (not suppressed)
      const retroCard = screen.getByTestId('worker-card-retrospective')
      expect(within(retroCard).getByTestId('worker-log-stream')).toBeInTheDocument()
    })
  })
})

describe('formatInterval', () => {
  let formatInterval
  beforeEach(async () => {
    const mod = await import('../SystemPanel')
    formatInterval = mod.formatInterval
  })

  it('returns null for null input', () => {
    expect(formatInterval(null)).toBeNull()
  })

  it('returns null for undefined input', () => {
    expect(formatInterval(undefined)).toBeNull()
  })

  it('formats seconds under 60', () => {
    expect(formatInterval(30)).toBe('every 30s')
  })

  it('formats minutes under 60', () => {
    expect(formatInterval(300)).toBe('every 5m')
    expect(formatInterval(1800)).toBe('every 30m')
  })

  it('formats exact hours', () => {
    expect(formatInterval(3600)).toBe('every 1h')
    expect(formatInterval(7200)).toBe('every 2h')
  })

  it('formats hours with remaining minutes', () => {
    expect(formatInterval(5400)).toBe('every 1h 30m')
  })
})

describe('formatNextRun', () => {
  let formatNextRun
  beforeEach(async () => {
    const mod = await import('../SystemPanel')
    formatNextRun = mod.formatNextRun
  })

  it('returns null when lastRun is null', () => {
    expect(formatNextRun(null, 3600)).toBeNull()
  })

  it('returns null when intervalSeconds is null', () => {
    expect(formatNextRun('2026-02-20T10:00:00Z', null)).toBeNull()
  })

  it('returns "now" when next run is overdue', () => {
    const pastTime = new Date(Date.now() - 10000).toISOString()
    expect(formatNextRun(pastTime, 1)).toBe('now')
  })

  it('returns time remaining for future next run', () => {
    const recentTime = new Date(Date.now() - 1000).toISOString()
    const result = formatNextRun(recentTime, 7200)
    expect(result).toMatch(/^in \d+/)
  })
})

describe('BackgroundWorkerCard schedule display', () => {
  let SystemPanel
  beforeEach(async () => {
    const mod = await import('../SystemPanel')
    SystemPanel = mod.SystemPanel
  })

  it('shows schedule when interval_seconds is present', () => {
    const bgWorkers = [
      { name: 'memory_sync', status: 'ok', enabled: true, last_run: '2026-02-20T10:00:00Z', interval_seconds: 3600, details: {} },
    ]
    render(<SystemPanel backgroundWorkers={bgWorkers} />)
    expect(screen.getByTestId('schedule-memory_sync')).toBeInTheDocument()
    expect(screen.getByTestId('schedule-memory_sync').textContent).toMatch(/Runs every 1h/)
  })

  it('does not show schedule when interval_seconds is null', () => {
    const bgWorkers = [
      { name: 'retrospective', status: 'ok', enabled: true, last_run: null, details: {} },
    ]
    render(<SystemPanel backgroundWorkers={bgWorkers} />)
    expect(screen.queryByTestId('schedule-retrospective')).not.toBeInTheDocument()
  })

  it('shows edit link for editable workers', () => {
    const bgWorkers = [
      { name: 'memory_sync', status: 'ok', enabled: true, last_run: null, interval_seconds: 3600, details: {} },
    ]
    render(<SystemPanel backgroundWorkers={bgWorkers} onUpdateInterval={() => {}} />)
    expect(screen.getByTestId('edit-interval-memory_sync')).toBeInTheDocument()
  })

  it('shows interval editor when edit is clicked', () => {
    const bgWorkers = [
      { name: 'memory_sync', status: 'ok', enabled: true, last_run: null, interval_seconds: 3600, details: {} },
    ]
    render(<SystemPanel backgroundWorkers={bgWorkers} onUpdateInterval={() => {}} />)
    fireEvent.click(screen.getByTestId('edit-interval-memory_sync'))
    expect(screen.getByTestId('interval-editor-memory_sync')).toBeInTheDocument()
    expect(screen.getByTestId('preset-1h')).toBeInTheDocument()
    expect(screen.getByTestId('preset-2h')).toBeInTheDocument()
  })

  it('calls onUpdateInterval when preset is clicked', () => {
    const onUpdate = vi.fn()
    const bgWorkers = [
      { name: 'memory_sync', status: 'ok', enabled: true, last_run: null, interval_seconds: 3600, details: {} },
    ]
    render(<SystemPanel backgroundWorkers={bgWorkers} onUpdateInterval={onUpdate} />)
    fireEvent.click(screen.getByTestId('edit-interval-memory_sync'))
    fireEvent.click(screen.getByTestId('preset-2h'))
    expect(onUpdate).toHaveBeenCalledWith('memory_sync', 7200)
  })

  it('shows schedule for pipeline_poller from SYSTEM_WORKER_INTERVALS fallback', () => {
    mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running' }))
    render(<SystemPanel backgroundWorkers={[]} />)
    expect(screen.getByTestId('schedule-pipeline_poller')).toBeInTheDocument()
    expect(screen.getByTestId('schedule-pipeline_poller').textContent).toMatch(/Runs every 5s/)
  })

  it('shows schedule for pr_unsticker from backend interval_seconds', () => {
    mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running' }))
    const bgWorkers = [
      { name: 'pr_unsticker', status: 'ok', enabled: true, last_run: '2026-02-20T10:00:00Z', interval_seconds: 3600, details: {} },
    ]
    render(<SystemPanel backgroundWorkers={bgWorkers} />)
    expect(screen.getByTestId('schedule-pr_unsticker')).toBeInTheDocument()
    expect(screen.getByTestId('schedule-pr_unsticker').textContent).toMatch(/Runs every 1h/)
  })

  it('shows schedule for pr_unsticker from fallback when no state reported', () => {
    mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running' }))
    render(<SystemPanel backgroundWorkers={[]} />)
    expect(screen.getByTestId('schedule-pr_unsticker')).toBeInTheDocument()
    expect(screen.getByTestId('schedule-pr_unsticker').textContent).toMatch(/Runs every 1h/)
  })

  it('shows "Next in" for pipeline_poller when lastRun is available', () => {
    const recentTime = new Date(Date.now() - 1000).toISOString()
    mockUseHydraFlow.mockReturnValue(defaultMockContext({
      orchestratorStatus: 'running',
      pipelinePollerLastRun: recentTime,
    }))
    render(<SystemPanel backgroundWorkers={[]} />)
    const scheduleRow = screen.getByTestId('schedule-pipeline_poller')
    expect(scheduleRow.textContent).toMatch(/Next/)
  })

  it('shows schedule for memory_sync from fallback when no backend state', () => {
    mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running' }))
    render(<SystemPanel backgroundWorkers={[]} />)
    expect(screen.getByTestId('schedule-memory_sync')).toBeInTheDocument()
    expect(screen.getByTestId('schedule-memory_sync').textContent).toMatch(/Runs every 1h/)
  })

  it('shows edit link for pr_unsticker when onUpdateInterval provided', () => {
    const bgWorkers = [
      { name: 'pr_unsticker', status: 'ok', enabled: true, last_run: null, interval_seconds: 3600, details: {} },
    ]
    render(<SystemPanel backgroundWorkers={bgWorkers} onUpdateInterval={() => {}} />)
    expect(screen.getByTestId('edit-interval-pr_unsticker')).toBeInTheDocument()
  })

  it('shows interval editor for pr_unsticker when edit clicked', () => {
    const bgWorkers = [
      { name: 'pr_unsticker', status: 'ok', enabled: true, last_run: null, interval_seconds: 3600, details: {} },
    ]
    render(<SystemPanel backgroundWorkers={bgWorkers} onUpdateInterval={() => {}} />)
    fireEvent.click(screen.getByTestId('edit-interval-pr_unsticker'))
    expect(screen.getByTestId('interval-editor-pr_unsticker')).toBeInTheDocument()
    expect(screen.getByTestId('preset-1h')).toBeInTheDocument()
    expect(screen.getByTestId('preset-2h')).toBeInTheDocument()
  })

  it('calls onUpdateInterval with pr_unsticker when preset clicked', () => {
    const onUpdate = vi.fn()
    const bgWorkers = [
      { name: 'pr_unsticker', status: 'ok', enabled: true, last_run: null, interval_seconds: 3600, details: {} },
    ]
    render(<SystemPanel backgroundWorkers={bgWorkers} onUpdateInterval={onUpdate} />)
    fireEvent.click(screen.getByTestId('edit-interval-pr_unsticker'))
    fireEvent.click(screen.getByTestId('preset-2h'))
    expect(onUpdate).toHaveBeenCalledWith('pr_unsticker', 7200)
  })

  it('shows edit link for pipeline_poller when onUpdateInterval provided', () => {
    mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running' }))
    const bgWorkers = [
      { name: 'pipeline_poller', status: 'ok', enabled: true, last_run: null, interval_seconds: 5, details: {} },
    ]
    render(<SystemPanel backgroundWorkers={bgWorkers} onUpdateInterval={() => {}} />)
    expect(screen.getByTestId('edit-interval-pipeline_poller')).toBeInTheDocument()
  })

  it('shows interval editor for pipeline_poller when edit clicked', () => {
    mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running' }))
    const bgWorkers = [
      { name: 'pipeline_poller', status: 'ok', enabled: true, last_run: null, interval_seconds: 5, details: {} },
    ]
    render(<SystemPanel backgroundWorkers={bgWorkers} onUpdateInterval={() => {}} />)
    fireEvent.click(screen.getByTestId('edit-interval-pipeline_poller'))
    expect(screen.getByTestId('interval-editor-pipeline_poller')).toBeInTheDocument()
    expect(screen.getByTestId('preset-5s')).toBeInTheDocument()
    expect(screen.getByTestId('preset-10s')).toBeInTheDocument()
    expect(screen.getByTestId('preset-15s')).toBeInTheDocument()
    expect(screen.queryByTestId('preset-30m')).not.toBeInTheDocument()
    expect(screen.queryByTestId('preset-1h')).not.toBeInTheDocument()
    expect(screen.queryByTestId('preset-2h')).not.toBeInTheDocument()
    expect(screen.queryByTestId('preset-4h')).not.toBeInTheDocument()
  })

  it('calls onUpdateInterval with pipeline_poller when preset clicked', () => {
    mockUseHydraFlow.mockReturnValue(defaultMockContext({ orchestratorStatus: 'running' }))
    const onUpdate = vi.fn()
    const bgWorkers = [
      { name: 'pipeline_poller', status: 'ok', enabled: true, last_run: null, interval_seconds: 5, details: {} },
    ]
    render(<SystemPanel backgroundWorkers={bgWorkers} onUpdateInterval={onUpdate} />)
    fireEvent.click(screen.getByTestId('edit-interval-pipeline_poller'))
    fireEvent.click(screen.getByTestId('preset-10s'))
    expect(onUpdate).toHaveBeenCalledWith('pipeline_poller', 10)
  })
})

