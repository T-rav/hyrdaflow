import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import { PIPELINE_LOOPS } from '../../constants'
import { deriveStageStatus } from '../../hooks/useStageStatus'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { PipelineControlPanel } = await import('../PipelineControlPanel')

/**
 * Build a pipelineStats object from worker-cap values.
 * Mirrors the shape the backend sends: { stages: { triage: { worker_cap }, ... } }
 */
function buildPipelineStats(caps = {}) {
  const stages = {}
  if (caps.triage != null) stages.triage = { worker_cap: caps.triage }
  if (caps.plan != null) stages.plan = { worker_cap: caps.plan }
  if (caps.implement != null) stages.implement = { worker_cap: caps.implement }
  if (caps.review != null) stages.review = { worker_cap: caps.review }
  return { stages }
}

const DEFAULT_CAPS = { triage: 1, plan: 2, implement: 3, review: 2 }

function defaultMockContext(overrides = {}) {
  const pipelineIssues = overrides.pipelineIssues || {}
  const workers = overrides.workers || {}
  const backgroundWorkers = overrides.backgroundWorkers || []
  const hasPipelineStatsOverride = Object.prototype.hasOwnProperty.call(overrides, 'pipelineStats')
  const pipelineStats = hasPipelineStatsOverride
    ? overrides.pipelineStats
    : buildPipelineStats(DEFAULT_CAPS)
  return {
    workers,
    hitlItems: [],
    pipelineStats,
    stageStatus: deriveStageStatus(pipelineIssues, workers, backgroundWorkers, pipelineStats),
    refreshControlStatus: overrides.refreshControlStatus || vi.fn().mockResolvedValue(true),
    ...overrides,
  }
}

beforeEach(() => {
  mockUseHydraFlow.mockReturnValue(defaultMockContext())
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const mockPipelineWorkers = {
  'triage-5': { status: 'evaluating', worker: 1, role: 'triage', title: 'Triage Issue #5', branch: '', transcript: ['Evaluating issue...', 'Checking labels'], pr: null },
  'plan-7': { status: 'planning', worker: 2, role: 'planner', title: 'Plan Issue #7', branch: '', transcript: ['Reading codebase...'], pr: null },
  10: { status: 'running', worker: 3, role: 'implementer', title: 'Issue #10', branch: 'agent/issue-10', transcript: ['Writing code...', 'Running tests...', 'All tests pass'], pr: null },
  'review-20': { status: 'reviewing', worker: 4, role: 'reviewer', title: 'PR #20 (Issue #3)', branch: '', transcript: [], pr: 20 },
}

describe('PipelineControlPanel', () => {
  describe('Pipeline Loop Toggles', () => {
    it('renders all 4 pipeline loop chips', () => {
      render(<PipelineControlPanel onToggleBgWorker={() => {}} />)
      for (const loop of PIPELINE_LOOPS) {
        expect(screen.getByText(loop.label)).toBeInTheDocument()
      }
    })

    it('shows max worker count when no active workers', () => {
      render(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-triage')).toHaveTextContent('1')
      expect(screen.getByTestId('loop-count-plan')).toHaveTextContent('2')
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('3')
      expect(screen.getByTestId('loop-count-review')).toHaveTextContent('2')
    })

    it('shows max worker counts per stage with config', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: mockPipelineWorkers }))
      render(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-triage')).toHaveTextContent('1')
      expect(screen.getByTestId('loop-count-plan')).toHaveTextContent('2')
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('3')
      expect(screen.getByTestId('loop-count-review')).toHaveTextContent('2')
    })

    it('shows triage max from config worker cap', () => {
      const singleTriageWorker = {
        'triage-5': { status: 'evaluating', worker: 1, role: 'triage', title: 'Triage #5', branch: '', transcript: [], pr: null },
      }
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: singleTriageWorker }))
      render(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-triage')).toHaveTextContent('1')
    })

    it('shows "workers" label for all stages when config is available', () => {
      render(<PipelineControlPanel />)
      const workerLabels = screen.getAllByText('workers')
      expect(workerLabels.length).toBe(PIPELINE_LOOPS.length)
    })

    it('shows loop count in stage color when loop is enabled and workers are active', () => {
      const singleImplementer = {
        10: { status: 'running', worker: 1, role: 'implementer', title: 'Issue #10', branch: '', transcript: [], pr: null },
      }
      const stats = buildPipelineStats({ triage: 1, plan: 2, implement: 3, review: 2 })
      stats.stages.implement.worker_count = 1
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: singleImplementer, pipelineStats: stats }))
      render(<PipelineControlPanel />)
      const implementCount = screen.getByTestId('loop-count-implement')
      expect(implementCount.style.color).toBe('var(--accent)')
    })

    it('shows loop count in muted color when enabled but no active workers', () => {
      render(<PipelineControlPanel />)
      const implementCount = screen.getByTestId('loop-count-implement')
      expect(implementCount.style.color).toBe('var(--text-muted)')
    })

    it('shows loop count in muted color when loop is disabled even if workers are active', () => {
      const singleImplementer = {
        10: { status: 'running', worker: 1, role: 'implementer', title: 'Issue #10', branch: '', transcript: [], pr: null },
      }
      const disabledBgWorkers = [
        { name: 'implement', status: 'ok', enabled: false, last_run: null, details: {} },
      ]
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: singleImplementer, backgroundWorkers: disabledBgWorkers }))
      render(<PipelineControlPanel />)
      const implementCount = screen.getByTestId('loop-count-implement')
      expect(implementCount.style.color).toBe('var(--text-muted)')
    })

    it('calls onToggleBgWorker with pipeline loop key when toggled', () => {
      const onToggle = vi.fn()
      render(<PipelineControlPanel onToggleBgWorker={onToggle} />)
      const allOnButtons = screen.getAllByText('On')
      fireEvent.click(allOnButtons[0]) // First pipeline loop = triage
      expect(onToggle).toHaveBeenCalledWith('triage', false)
    })

    it('shows On/Off toggle state correctly', () => {
      const disabledBgWorkers = [
        { name: 'triage', status: 'ok', enabled: false, last_run: null, details: {} },
      ]
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ backgroundWorkers: disabledBgWorkers }))
      render(<PipelineControlPanel onToggleBgWorker={() => {}} />)
      expect(screen.getByText('Off')).toBeInTheDocument()
      const onButtons = screen.getAllByText('On')
      expect(onButtons.length).toBe(3) // 3 enabled loops
    })

    it('shows dimmed dot color when loop is disabled', () => {
      const disabledBgWorkers = [
        { name: 'triage', status: 'ok', enabled: false, last_run: null, details: {} },
      ]
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ backgroundWorkers: disabledBgWorkers }))
      render(<PipelineControlPanel />)
      const triageLabel = screen.getByText('Triage')
      expect(triageLabel.style.color).toBe('var(--text-muted)')
    })

    it('falls back to zero counts when pipelineStats is null', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: mockPipelineWorkers, pipelineStats: null }))
      render(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-triage')).toHaveTextContent('0')
      expect(screen.getByTestId('loop-count-plan')).toHaveTextContent('0')
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('0')
      expect(screen.getByTestId('loop-count-review')).toHaveTextContent('0')
    })

    it('updates display when pipelineStats worker caps change', () => {
      const { rerender } = render(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('3')
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ pipelineStats: buildPipelineStats({ triage: 1, plan: 2, implement: 5, review: 2 }) }))
      rerender(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('5')
    })

    it('uses zero worker caps when pipelineStats worker caps are zero', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ pipelineStats: buildPipelineStats({ triage: 0, plan: 0, implement: 0, review: 0 }) }))
      render(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-triage')).toHaveTextContent('0')
      expect(screen.getByTestId('loop-count-plan')).toHaveTextContent('0')
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('0')
      expect(screen.getByTestId('loop-count-review')).toHaveTextContent('0')
    })

    it('falls back to zero counts when pipelineStats has no stages', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: mockPipelineWorkers, pipelineStats: { stages: {} } }))
      render(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-triage')).toHaveTextContent('0')
      expect(screen.getByTestId('loop-count-plan')).toHaveTextContent('0')
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('0')
      expect(screen.getByTestId('loop-count-review')).toHaveTextContent('0')
    })
  })

  describe('Worker Count Controls', () => {
    it('renders increment and decrement buttons for each stage when config is available', () => {
      render(<PipelineControlPanel />)
      for (const loop of PIPELINE_LOOPS) {
        expect(screen.getByTestId(`dec-${loop.key}`)).toBeInTheDocument()
        expect(screen.getByTestId(`inc-${loop.key}`)).toBeInTheDocument()
      }
    })

    it('does not render increment/decrement buttons when pipelineStats is null', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ pipelineStats: null }))
      render(<PipelineControlPanel />)
      for (const loop of PIPELINE_LOOPS) {
        expect(screen.queryByTestId(`dec-${loop.key}`)).not.toBeInTheDocument()
        expect(screen.queryByTestId(`inc-${loop.key}`)).not.toBeInTheDocument()
      }
    })

    it('does not render increment/decrement buttons when pipelineStats has no stages', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ pipelineStats: { stages: {} } }))
      render(<PipelineControlPanel />)
      for (const loop of PIPELINE_LOOPS) {
        expect(screen.queryByTestId(`dec-${loop.key}`)).not.toBeInTheDocument()
        expect(screen.queryByTestId(`inc-${loop.key}`)).not.toBeInTheDocument()
      }
    })

    it('disables decrement button when count is at minimum (1)', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        pipelineStats: buildPipelineStats({ triage: 1, plan: 1, implement: 1, review: 1 }),
      }))
      render(<PipelineControlPanel />)
      for (const loop of PIPELINE_LOOPS) {
        expect(screen.getByTestId(`dec-${loop.key}`)).toBeDisabled()
      }
    })

    it('disables increment button when count is at maximum (10)', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        pipelineStats: buildPipelineStats({ triage: 10, plan: 10, implement: 10, review: 10 }),
      }))
      render(<PipelineControlPanel />)
      for (const loop of PIPELINE_LOOPS) {
        expect(screen.getByTestId(`inc-${loop.key}`)).toBeDisabled()
      }
    })

    it('enables both buttons when count is between min and max', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        pipelineStats: buildPipelineStats({ triage: 5, plan: 5, implement: 5, review: 5 }),
      }))
      render(<PipelineControlPanel />)
      for (const loop of PIPELINE_LOOPS) {
        expect(screen.getByTestId(`dec-${loop.key}`)).not.toBeDisabled()
        expect(screen.getByTestId(`inc-${loop.key}`)).not.toBeDisabled()
      }
    })

    it('calls PATCH /api/control/config with persist:true on increment', async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true })
      vi.stubGlobal('fetch', fetchMock)
      render(<PipelineControlPanel />)

      await act(async () => {
        fireEvent.click(screen.getByTestId('inc-implement'))
      })

      expect(fetchMock).toHaveBeenCalledWith('/api/control/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_workers: 4, persist: true }),
      })
    })

    it('calls PATCH /api/control/config with persist:true on decrement', async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true })
      vi.stubGlobal('fetch', fetchMock)
      render(<PipelineControlPanel />)

      await act(async () => {
        fireEvent.click(screen.getByTestId('dec-implement'))
      })

      expect(fetchMock).toHaveBeenCalledWith('/api/control/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_workers: 2, persist: true }),
      })
    })

    it('optimistically updates displayed count on increment click', async () => {
      let resolvePromise
      const fetchMock = vi.fn().mockImplementation(() => new Promise((resolve) => { resolvePromise = resolve }))
      vi.stubGlobal('fetch', fetchMock)
      render(<PipelineControlPanel />)

      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('3')

      await act(async () => {
        fireEvent.click(screen.getByTestId('inc-implement'))
      })

      // Optimistic update: count should show 4 immediately
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('4')

      // Resolve the fetch
      await act(async () => { resolvePromise({ ok: true }) })
    })

    it('rolls back optimistic update on API failure', async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 500 })
      vi.stubGlobal('fetch', fetchMock)
      render(<PipelineControlPanel />)

      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('3')

      await act(async () => {
        fireEvent.click(screen.getByTestId('inc-implement'))
      })

      // After API failure, should roll back to original server value
      await waitFor(() => {
        expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('3')
      })
    })

    it('rolls back optimistic update on network error', async () => {
      const fetchMock = vi.fn().mockRejectedValue(new Error('Network error'))
      vi.stubGlobal('fetch', fetchMock)
      render(<PipelineControlPanel />)

      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('3')

      await act(async () => {
        fireEvent.click(screen.getByTestId('inc-implement'))
      })

      await waitFor(() => {
        expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('3')
      })
    })

    it('preserves optimistic override for other stages when one stage cap changes from server', async () => {
      const fetchMock = vi.fn().mockImplementation(() => new Promise(() => {}))
      vi.stubGlobal('fetch', fetchMock)
      const { rerender } = render(<PipelineControlPanel />)

      // Optimistically increment implement from 3 → 4
      await act(async () => {
        fireEvent.click(screen.getByTestId('inc-implement'))
      })
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('4')

      // Server pushes an update that only changes triage (1 → 2), implement stays at 3
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        pipelineStats: buildPipelineStats({ triage: 2, plan: 2, implement: 3, review: 2 }),
      }))
      rerender(<PipelineControlPanel />)

      // Implement optimistic override (4) should be preserved since server still says 3
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('4')
      // Triage should reflect new server value
      expect(screen.getByTestId('loop-count-triage')).toHaveTextContent('2')
    })

    it('clears optimistic override when server confirms the new value', async () => {
      const fetchMock = vi.fn().mockImplementation(() => new Promise(() => {}))
      vi.stubGlobal('fetch', fetchMock)
      const { rerender } = render(<PipelineControlPanel />)

      // Optimistically increment implement from 3 → 4
      await act(async () => {
        fireEvent.click(screen.getByTestId('inc-implement'))
      })
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('4')

      // Server confirms: implement is now 4
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        pipelineStats: buildPipelineStats({ triage: 1, plan: 2, implement: 4, review: 2 }),
      }))
      rerender(<PipelineControlPanel />)

      // Should show server-confirmed value of 4
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('4')
    })

    it('calls refreshControlStatus after successful PATCH', async () => {
      const refreshControlStatus = vi.fn().mockResolvedValue(true)
      const fetchMock = vi.fn().mockResolvedValue({ ok: true })
      vi.stubGlobal('fetch', fetchMock)
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ refreshControlStatus }))
      render(<PipelineControlPanel />)

      await act(async () => {
        fireEvent.click(screen.getByTestId('inc-implement'))
      })

      expect(refreshControlStatus).toHaveBeenCalledTimes(1)
    })

    it('does not call refreshControlStatus on PATCH failure', async () => {
      const refreshControlStatus = vi.fn().mockResolvedValue(true)
      const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 500 })
      vi.stubGlobal('fetch', fetchMock)
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ refreshControlStatus }))
      render(<PipelineControlPanel />)

      await act(async () => {
        fireEvent.click(screen.getByTestId('inc-implement'))
      })

      expect(refreshControlStatus).not.toHaveBeenCalled()
    })

    it('does not call refreshControlStatus on network error', async () => {
      const refreshControlStatus = vi.fn().mockResolvedValue(true)
      const fetchMock = vi.fn().mockRejectedValue(new Error('Network error'))
      vi.stubGlobal('fetch', fetchMock)
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ refreshControlStatus }))
      render(<PipelineControlPanel />)

      await act(async () => {
        fireEvent.click(screen.getByTestId('inc-implement'))
      })

      expect(refreshControlStatus).not.toHaveBeenCalled()
    })

    it('config update persists across component remount', async () => {
      const refreshControlStatus = vi.fn().mockResolvedValue(true)
      const fetchMock = vi.fn().mockResolvedValue({ ok: true })
      vi.stubGlobal('fetch', fetchMock)
      // Initial config: max_workers=3
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ refreshControlStatus }))
      const { unmount } = render(<PipelineControlPanel />)

      await act(async () => {
        fireEvent.click(screen.getByTestId('inc-implement'))
      })

      // Simulate refreshControlStatus updating pipelineStats to implement worker_cap=4
      const updatedStats = buildPipelineStats({ triage: 1, plan: 2, implement: 4, review: 2 })
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ pipelineStats: updatedStats, refreshControlStatus }))

      // Unmount and remount
      unmount()
      render(<PipelineControlPanel />)

      // After remount, the value should reflect the server-confirmed config (4)
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('4')
    })

    it('uses correct configKey for each stage', async () => {
      const fetchMock = vi.fn().mockResolvedValue({ ok: true })
      vi.stubGlobal('fetch', fetchMock)
      render(<PipelineControlPanel />)

      await act(async () => { fireEvent.click(screen.getByTestId('inc-triage')) })
      expect(fetchMock).toHaveBeenCalledWith('/api/control/config', expect.objectContaining({
        body: JSON.stringify({ max_triagers: 2, persist: true }),
      }))

      fetchMock.mockClear()
      await act(async () => { fireEvent.click(screen.getByTestId('inc-plan')) })
      expect(fetchMock).toHaveBeenCalledWith('/api/control/config', expect.objectContaining({
        body: JSON.stringify({ max_planners: 3, persist: true }),
      }))

      fetchMock.mockClear()
      await act(async () => { fireEvent.click(screen.getByTestId('inc-review')) })
      expect(fetchMock).toHaveBeenCalledWith('/api/control/config', expect.objectContaining({
        body: JSON.stringify({ max_reviewers: 3, persist: true }),
      }))
    })

    it('applies disabled style to decrement button at min', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        pipelineStats: buildPipelineStats({ triage: 1, plan: 2, implement: 3, review: 2 }),
      }))
      render(<PipelineControlPanel />)
      const decBtn = screen.getByTestId('dec-triage')
      expect(decBtn).toBeDisabled()
      expect(decBtn.style.cursor).toBe('default')
    })

    it('applies disabled style to increment button at max', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        pipelineStats: buildPipelineStats({ triage: 10, plan: 2, implement: 3, review: 2 }),
      }))
      render(<PipelineControlPanel />)
      const incBtn = screen.getByTestId('inc-triage')
      expect(incBtn).toBeDisabled()
      expect(incBtn.style.cursor).toBe('default')
    })

    it('has aria-labels for accessibility', () => {
      render(<PipelineControlPanel />)
      for (const loop of PIPELINE_LOOPS) {
        expect(screen.getByLabelText(`Decrease ${loop.label} workers`)).toBeInTheDocument()
        expect(screen.getByLabelText(`Increase ${loop.label} workers`)).toBeInTheDocument()
      }
    })
  })

  describe('Pipeline Worker Cards', () => {
    it('shows "No active pipeline workers" when no workers', () => {
      render(<PipelineControlPanel />)
      expect(screen.getByText('No active pipeline workers')).toBeInTheDocument()
    })

    it('renders active worker cards with issue #, role badge, status', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: mockPipelineWorkers }))
      render(<PipelineControlPanel />)
      expect(screen.getByText('#5')).toBeInTheDocument()
      expect(screen.getByText('#7')).toBeInTheDocument()
      expect(screen.getByText('#10')).toBeInTheDocument()
      expect(screen.getByText('#20')).toBeInTheDocument()
      expect(screen.getByText('triage')).toBeInTheDocument()
      expect(screen.getByText('planner')).toBeInTheDocument()
      expect(screen.getByText('implementer')).toBeInTheDocument()
      expect(screen.getByText('reviewer')).toBeInTheDocument()
    })

    it('filters out queued workers', () => {
      const workers = {
        99: { status: 'queued', worker: 1, role: 'implementer', title: 'Issue #99', branch: '', transcript: [], pr: null },
      }
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers }))
      render(<PipelineControlPanel />)
      expect(screen.getByText('No active pipeline workers')).toBeInTheDocument()
    })

    it('filters out done and failed workers', () => {
      const workers = {
        50: { status: 'done', worker: 1, role: 'implementer', title: 'Issue #50', branch: '', transcript: [], pr: null },
        51: { status: 'failed', worker: 2, role: 'reviewer', title: 'Issue #51', branch: '', transcript: [], pr: null },
      }
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers }))
      render(<PipelineControlPanel />)
      expect(screen.getByText('No active pipeline workers')).toBeInTheDocument()
      expect(screen.queryByText('#50')).not.toBeInTheDocument()
      expect(screen.queryByText('#51')).not.toBeInTheDocument()
    })

    it('shows worker title', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: mockPipelineWorkers }))
      render(<PipelineControlPanel />)
      expect(screen.getByText('Issue #10')).toBeInTheDocument()
      expect(screen.getByText('Triage Issue #5')).toBeInTheDocument()
    })

    it('shows transcript lines inline without click', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: mockPipelineWorkers }))
      render(<PipelineControlPanel />)
      // Lines should be visible immediately — no toggle click needed
      expect(screen.getByText('Writing code...')).toBeInTheDocument()
      expect(screen.getByText('Running tests...')).toBeInTheDocument()
      expect(screen.getByText('All tests pass')).toBeInTheDocument()
    })

    it('does not show toggle when transcript has 10 or fewer lines', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: mockPipelineWorkers }))
      render(<PipelineControlPanel />)
      // 3 lines — no toggle needed
      expect(screen.queryByText(/Show all/)).not.toBeInTheDocument()
    })

    it('does not show transcript section when transcript is empty', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: mockPipelineWorkers }))
      render(<PipelineControlPanel />)
      // Worker 'review-20' has empty transcript — verify no transcript lines leak
      const card = screen.getByTestId('pipeline-worker-card-review-20')
      expect(card.querySelector('[style*="border-top"]')).toBeNull()
    })

    it('shows "Show all (N)" toggle when transcript has more than 10 lines', () => {
      const manyLines = Array.from({ length: 20 }, (_, i) => `Line ${i + 1}`)
      const workers = {
        42: { status: 'running', worker: 1, role: 'implementer', title: 'Issue #42', branch: '', transcript: manyLines, pr: null },
      }
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers }))
      render(<PipelineControlPanel />)
      expect(screen.getByText('Show all (20)')).toBeInTheDocument()
      // Only last 10 lines visible by default
      expect(screen.queryByText('Line 1')).not.toBeInTheDocument()
      expect(screen.queryByText('Line 10')).not.toBeInTheDocument()
      expect(screen.getByText('Line 11')).toBeInTheDocument()
      expect(screen.getByText('Line 20')).toBeInTheDocument()
    })

    it('applies maxHeight and scroll on expanded transcript', () => {
      const manyLines = Array.from({ length: 20 }, (_, i) => `Line ${i + 1}`)
      const workers = {
        42: { status: 'running', worker: 1, role: 'implementer', title: 'Issue #42', branch: '', transcript: manyLines, pr: null },
      }
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers }))
      render(<PipelineControlPanel collapsed={false} onToggleCollapse={() => {}} />)
      const toggle = screen.getByText('Show all (20)')
      fireEvent.click(toggle)
      // The transcript lines wrapper should have maxHeight and overflowY when expanded
      const firstLine = screen.getByText('Line 1')
      const linesContainer = firstLine.parentElement
      expect(linesContainer.style.maxHeight).toBe('200px')
      expect(linesContainer.style.overflowY).toBe('auto')
    })

    it('does not apply scroll styles on collapsed transcript', () => {
      const workers = {
        42: { status: 'running', worker: 1, role: 'implementer', title: 'Issue #42', branch: '', transcript: ['Line 1', 'Line 2', 'Line 3', 'Line 4', 'Line 5'], pr: null },
      }
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers }))
      render(<PipelineControlPanel collapsed={false} onToggleCollapse={() => {}} />)
      // All 5 lines visible inline (within 10-line limit), no scroll styles
      const line = screen.getByText('Line 3')
      const linesContainer = line.parentElement
      expect(linesContainer.style.maxHeight).toBe('')
      expect(linesContainer.style.overflowY).toBe('')
    })

    it('collapses transcript back after expanding', () => {
      const manyLines = Array.from({ length: 15 }, (_, i) => `Line ${i + 1}`)
      const workers = {
        42: { status: 'running', worker: 1, role: 'implementer', title: 'Issue #42', branch: '', transcript: manyLines, pr: null },
      }
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers }))
      render(<PipelineControlPanel collapsed={false} onToggleCollapse={() => {}} />)
      // Expand
      fireEvent.click(screen.getByText('Show all (15)'))
      expect(screen.getByText('Line 1')).toBeInTheDocument()
      // Collapse
      fireEvent.click(screen.getByText('Collapse'))
      // Should be back to last 10 lines
      expect(screen.queryByText('Line 1')).not.toBeInTheDocument()
      expect(screen.queryByText('Line 5')).not.toBeInTheDocument()
      expect(screen.getByText('Line 6')).toBeInTheDocument()
      expect(screen.getByText('Line 15')).toBeInTheDocument()
    })

    it('shows last 10 lines inline by default when transcript has more than 10 lines', () => {
      const manyLines = Array.from({ length: 15 }, (_, i) => `Line ${i + 1}`)
      const workers = {
        42: { status: 'running', worker: 1, role: 'implementer', title: 'Issue #42', branch: '', transcript: manyLines, pr: null },
      }
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers }))
      render(<PipelineControlPanel />)
      // First 5 lines should not be visible
      for (let i = 1; i <= 5; i++) {
        expect(screen.queryByText(`Line ${i}`)).not.toBeInTheDocument()
      }
      // Last 10 lines should be visible
      for (let i = 6; i <= 15; i++) {
        expect(screen.getByText(`Line ${i}`)).toBeInTheDocument()
      }
    })

    it('card has overflow hidden to contain content', () => {
      const workers = {
        42: { status: 'running', worker: 1, role: 'implementer', title: 'Issue #42', branch: '', transcript: ['Test line'], pr: null },
      }
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers }))
      render(<PipelineControlPanel collapsed={false} onToggleCollapse={() => {}} />)
      const cardEl = screen.getByTestId('pipeline-worker-card-42')
      expect(cardEl.style.overflow).toBe('hidden')
      expect(cardEl.style.minWidth).toBe('0px')
    })
  })

  describe('Status Badges', () => {
    it('shows "N HITL issues" badge when HITL items exist', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        hitlItems: [
          { issue_number: 1, title: 'Issue 1' },
          { issue_number: 2, title: 'Issue 2' },
          { issue_number: 3, title: 'Issue 3' },
        ],
      }))
      render(<PipelineControlPanel />)
      expect(screen.getByText('3 HITL issues')).toBeInTheDocument()
    })

    it('shows singular "issue" for count of 1', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        hitlItems: [{ issue_number: 1, title: 'Issue 1' }],
      }))
      render(<PipelineControlPanel />)
      expect(screen.getByText('1 HITL issue')).toBeInTheDocument()
    })

    it('does not show HITL badge when hitlItems is empty', () => {
      render(<PipelineControlPanel />)
      expect(screen.queryByText(/HITL/)).not.toBeInTheDocument()
    })

    it('shows HITL badge even when workers are present', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        workers: mockPipelineWorkers,
        hitlItems: [{ issue_number: 1, title: 'Issue 1' }, { issue_number: 2, title: 'Issue 2' }],
      }))
      render(<PipelineControlPanel />)
      expect(screen.getByText('2 HITL issues')).toBeInTheDocument()
    })
  })

  describe('Rendering', () => {
    it('renders panel with all controls and heading', () => {
      render(<PipelineControlPanel />)
      expect(screen.getByText('Pipeline Controls')).toBeInTheDocument()
      expect(screen.getByText('No active pipeline workers')).toBeInTheDocument()
      for (const loop of PIPELINE_LOOPS) {
        expect(screen.getByText(loop.label)).toBeInTheDocument()
      }
    })
  })
})
