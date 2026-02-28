import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { PIPELINE_LOOPS } from '../../constants'
import { deriveStageStatus } from '../../hooks/useStageStatus'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { PipelineControlPanel } = await import('../PipelineControlPanel')

function defaultMockContext(overrides = {}) {
  const pipelineIssues = overrides.pipelineIssues || {}
  const workers = overrides.workers || {}
  const backgroundWorkers = overrides.backgroundWorkers || []
  const hasConfigOverride = Object.prototype.hasOwnProperty.call(overrides, 'config')
  const config = hasConfigOverride
    ? overrides.config
    : { max_triagers: 1, max_planners: 2, max_workers: 3, max_reviewers: 2 }
  return {
    workers,
    hitlItems: [],
    config,
    stageStatus: deriveStageStatus(pipelineIssues, workers, backgroundWorkers, {}, config),
    ...overrides,
  }
}

beforeEach(() => {
  mockUseHydraFlow.mockReturnValue(defaultMockContext())
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

    it('shows worker count of 0 when no active workers', () => {
      render(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-triage')).toHaveTextContent('0/1')
      expect(screen.getByTestId('loop-count-plan')).toHaveTextContent('0/2')
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('0/3')
      expect(screen.getByTestId('loop-count-review')).toHaveTextContent('0/2')
    })

    it('shows worker counts per stage in active/max format', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: mockPipelineWorkers }))
      render(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-triage')).toHaveTextContent('1/1')
      expect(screen.getByTestId('loop-count-plan')).toHaveTextContent('1/2')
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('1/3')
      expect(screen.getByTestId('loop-count-review')).toHaveTextContent('1/2')
    })

    it('shows triage in active/max format using stage worker cap', () => {
      const singleTriageWorker = {
        'triage-5': { status: 'evaluating', worker: 1, role: 'triage', title: 'Triage #5', branch: '', transcript: [], pr: null },
      }
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: singleTriageWorker }))
      render(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-triage')).toHaveTextContent('1/1')
    })

    it('shows "workers" plural for non-triage stages even when active count is 1', () => {
      const singleImplementer = {
        10: { status: 'running', worker: 1, role: 'implementer', title: 'Issue #10', branch: '', transcript: [], pr: null },
      }
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: singleImplementer }))
      render(<PipelineControlPanel />)
      const implementCount = screen.getByTestId('loop-count-implement')
      expect(implementCount).toHaveTextContent('1/3')
      // Label is plural when showing ratio, even with activeCount=1
      const implementChip = implementCount.closest('[style]')
      expect(implementChip).not.toBeNull()
      expect(screen.queryByText('worker')).not.toBeInTheDocument()
    })

    it('shows "workers" plural when count is not 1', () => {
      render(<PipelineControlPanel />)
      const workerLabels = screen.getAllByText('workers')
      expect(workerLabels.length).toBe(PIPELINE_LOOPS.length)
    })

    it('shows loop count in stage color when loop is enabled and workers are active', () => {
      const singleImplementer = {
        10: { status: 'running', worker: 1, role: 'implementer', title: 'Issue #10', branch: '', transcript: [], pr: null },
      }
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: singleImplementer }))
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

    it('shows active/max count for triage from shared worker caps', () => {
      const triageWorker = {
        'triage-5': { status: 'evaluating', worker: 1, role: 'triage', title: 'Triage #5', branch: '', transcript: [], pr: null },
      }
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: triageWorker }))
      render(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-triage')).toHaveTextContent('1/1')
    })

    it('falls back to active-only counts when config is null', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: mockPipelineWorkers, config: null }))
      render(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-triage')).toHaveTextContent('1')
      expect(screen.getByTestId('loop-count-plan')).toHaveTextContent('1')
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('1')
      expect(screen.getByTestId('loop-count-review')).toHaveTextContent('1')
      expect(screen.getByTestId('loop-count-triage').textContent).not.toContain('/')
      expect(screen.getByTestId('loop-count-plan').textContent).not.toContain('/')
      expect(screen.getByTestId('loop-count-implement').textContent).not.toContain('/')
      expect(screen.getByTestId('loop-count-review').textContent).not.toContain('/')
    })

    it('updates display when config max values change', () => {
      const { rerender } = render(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('0/3')
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ config: { max_triagers: 1, max_planners: 2, max_workers: 5, max_reviewers: 2 } }))
      rerender(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('0/5')
    })

    it('uses zero worker caps when config max values are zero', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ config: { max_triagers: 0, max_planners: 0, max_workers: 0, max_reviewers: 0 } }))
      render(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-triage')).toHaveTextContent('0/0')
      expect(screen.getByTestId('loop-count-plan')).toHaveTextContent('0/0')
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('0/0')
      expect(screen.getByTestId('loop-count-review')).toHaveTextContent('0/0')
    })

    it('falls back to active-only counts when config is missing keys', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: mockPipelineWorkers, config: {} }))
      render(<PipelineControlPanel />)
      expect(screen.getByTestId('loop-count-triage')).toHaveTextContent('1')
      expect(screen.getByTestId('loop-count-plan')).toHaveTextContent('1')
      expect(screen.getByTestId('loop-count-implement')).toHaveTextContent('1')
      expect(screen.getByTestId('loop-count-review')).toHaveTextContent('1')
      expect(screen.getByTestId('loop-count-triage').textContent).not.toContain('/')
      expect(screen.getByTestId('loop-count-plan').textContent).not.toContain('/')
      expect(screen.getByTestId('loop-count-implement').textContent).not.toContain('/')
      expect(screen.getByTestId('loop-count-review').textContent).not.toContain('/')
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
    it('shows "N active" badge when workers present', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({ workers: mockPipelineWorkers }))
      render(<PipelineControlPanel />)
      expect(screen.getByText('4 active')).toBeInTheDocument()
    })

    it('does not show active badge when no active workers', () => {
      render(<PipelineControlPanel />)
      expect(screen.queryByText(/\d+ active/)).not.toBeInTheDocument()
    })

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

    it('shows both active and HITL badges together', () => {
      mockUseHydraFlow.mockReturnValue(defaultMockContext({
        workers: mockPipelineWorkers,
        hitlItems: [{ issue_number: 1, title: 'Issue 1' }, { issue_number: 2, title: 'Issue 2' }],
      }))
      render(<PipelineControlPanel />)
      expect(screen.getByText('4 active')).toBeInTheDocument()
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
