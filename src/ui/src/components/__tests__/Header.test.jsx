import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { deriveStageStatus } from '../../hooks/useStageStatus'
import { PIPELINE_STAGES } from '../../constants'
import { theme } from '../../theme'
import {
  dotConnected, dotDisconnected,
  startBtnEnabled, startBtnDisabled,
  stageAbbreviations,
  pipelineStageStylesMap,
  pipelineLabelStylesMap,
} from '../Header'

const mockUseHydraFlow = vi.fn()
const html2canvasFn = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))
vi.mock('html2canvas', () => ({
  default: (...args) => html2canvasFn(...args),
}))

const { Header } = await import('../Header')

function mockStageStatus(workers = {}, sessionCounters = {}) {
  return deriveStageStatus({}, workers, [], sessionCounters)
}

function createRootContainer() {
  const existing = document.getElementById('root')
  if (existing) existing.remove()
  const root = document.createElement('div')
  root.id = 'root'
  document.body.appendChild(root)
  return root
}

beforeEach(() => {
  html2canvasFn.mockReset()
  mockUseHydraFlow.mockReturnValue({ stageStatus: mockStageStatus(), config: null, submitReport: vi.fn() })
})

describe('Header pre-computed styles', () => {
  describe('dot variants', () => {
    it('dotConnected has green background', () => {
      expect(dotConnected).toMatchObject({
        width: 8, height: 8, borderRadius: '50%',
        background: 'var(--green)',
      })
    })

    it('dotDisconnected has red background', () => {
      expect(dotDisconnected).toMatchObject({
        width: 8, height: 8, borderRadius: '50%',
        background: 'var(--red)',
      })
    })
  })

  describe('start button variants', () => {
    it('startBtnEnabled has opacity 1 and pointer cursor', () => {
      expect(startBtnEnabled).toMatchObject({ opacity: 1, cursor: 'pointer' })
      expect(startBtnEnabled.background).toBe('var(--btn-green)')
    })

    it('startBtnDisabled has opacity 0.4 and not-allowed cursor', () => {
      expect(startBtnDisabled).toMatchObject({ opacity: 0.4, cursor: 'not-allowed' })
    })
  })

  it('style objects are referentially stable', () => {
    expect(dotConnected).toBe(dotConnected)
    expect(startBtnEnabled).toBe(startBtnEnabled)
  })

  describe('pipelineStageStylesMap', () => {
    it('has an entry for every pipeline stage', () => {
      PIPELINE_STAGES.forEach(stage => {
        expect(pipelineStageStylesMap[stage.key]).toBeDefined()
      })
    })

    it('each entry uses the stage color as borderColor', () => {
      PIPELINE_STAGES.forEach(stage => {
        expect(pipelineStageStylesMap[stage.key].borderColor).toBe(stage.color)
      })
    })

    it('style objects are referentially stable', () => {
      PIPELINE_STAGES.forEach(stage => {
        expect(pipelineStageStylesMap[stage.key]).toBe(pipelineStageStylesMap[stage.key])
      })
    })
  })

  describe('pipelineLabelStylesMap', () => {
    it('has an entry for every pipeline stage', () => {
      PIPELINE_STAGES.forEach(stage => {
        expect(pipelineLabelStylesMap[stage.key]).toBeDefined()
      })
    })

    it('each entry uses the stage color as text color', () => {
      PIPELINE_STAGES.forEach(stage => {
        expect(pipelineLabelStylesMap[stage.key].color).toBe(stage.color)
      })
    })

    it('style objects are referentially stable', () => {
      PIPELINE_STAGES.forEach(stage => {
        expect(pipelineLabelStylesMap[stage.key]).toBe(pipelineLabelStylesMap[stage.key])
      })
    })
  })
})

describe('Header component', () => {
  const defaultProps = {
    connected: true,
    orchestratorStatus: 'idle',
    onStart: () => {},
    onStop: () => {},
  }

  it('renders without errors', () => {
    render(<Header {...defaultProps} />)
    expect(screen.getByText('HYDRAFLOW')).toBeInTheDocument()
  })

  it('renders Start button when idle', () => {
    render(<Header {...defaultProps} />)
    expect(screen.getByText('Start')).toBeInTheDocument()
  })

  it('renders Stop button when running', () => {
    render(<Header {...defaultProps} orchestratorStatus="running" />)
    expect(screen.getByText('Stop')).toBeInTheDocument()
  })

  it('does not render workload counters', () => {
    mockUseHydraFlow.mockReturnValue({
      stageStatus: { ...mockStageStatus(), workload: { active: 3, done: 2, failed: 1, total: 6 } },
      config: null,
    })
    render(<Header {...defaultProps} />)
    expect(screen.queryByText(/\d+\s+active/i)).toBeNull()
    expect(screen.queryByText(/\d+\s+done/i)).toBeNull()
    expect(screen.queryByText(/\d+\s+failed/i)).toBeNull()
    expect(screen.queryByText(/\d+\s+total/i)).toBeNull()
  })

  it('renders Session label', () => {
    render(<Header {...defaultProps} />)
    expect(screen.getByText('Session')).toBeInTheDocument()
  })

  it('renders tagline as two stacked lines', () => {
    render(<Header {...defaultProps} />)
    expect(screen.getByText('Intent in.')).toBeInTheDocument()
    expect(screen.getByText('Software out.')).toBeInTheDocument()
  })

  it('renders app version when available in config', () => {
    mockUseHydraFlow.mockReturnValue({
      stageStatus: mockStageStatus(),
      config: { app_version: '0.9.0' },
    })
    render(<Header {...defaultProps} />)
    expect(screen.getByText('v0.9.0')).toBeInTheDocument()
  })

  it('renders update notice with command when update is available', () => {
    mockUseHydraFlow.mockReturnValue({
      stageStatus: mockStageStatus(),
      config: {
        app_version: '0.9.0',
        latest_version: '0.9.2',
        update_available: true,
      },
    })
    render(<Header {...defaultProps} />)
    expect(screen.getByText('Update available: v0.9.2 (`hf check-update`)')).toBeInTheDocument()
  })

  it('controls section has marginLeft for spacing from center content', () => {
    render(<Header {...defaultProps} />)
    const startBtn = screen.getByText('Start')
    const controlsDiv = startBtn.parentElement
    expect(controlsDiv.style.marginLeft).toBe('10px')
  })

  it('left section has flexShrink 0 to prevent collapsing', () => {
    render(<Header {...defaultProps} />)
    const logo = screen.getByText('HYDRAFLOW')
    // logo is inside logoGroup -> left div; go up two levels past logoGroup
    const leftDiv = logo.parentElement.parentElement
    expect(leftDiv.style.flexShrink).toBe('0')
  })

  it('controls section has flexShrink 0 to prevent collapsing', () => {
    render(<Header {...defaultProps} />)
    const startBtn = screen.getByText('Start')
    const controlsDiv = startBtn.parentElement
    expect(controlsDiv.style.flexShrink).toBe('0')
  })

  it('center section has minWidth 0 and overflow hidden for graceful truncation', () => {
    render(<Header {...defaultProps} />)
    const sessionLabel = screen.getByText('Session')
    const centerDiv = sessionLabel.closest('div').parentElement
    expect(centerDiv.style.minWidth).toBe('0px')
    expect(centerDiv.style.overflow).toBe('hidden')
  })

  describe('session pipeline row', () => {
    const counterFixture = {
      sessionTriaged: 7,
      sessionPlanned: 5,
      sessionImplemented: 4,
      sessionReviewed: 3,
      mergedCount: 2,
    }

    beforeEach(() => {
      mockUseHydraFlow.mockReturnValue({
        stageStatus: mockStageStatus({}, counterFixture),
        config: null,
      })
    })

    it('renders compact stage pills with arrows separating each stage', () => {
      render(<Header {...defaultProps} />)
      const pipelineRow = screen.getByTestId('session-pipeline')
      expect(pipelineRow).toBeInTheDocument()

      const expectedCounts = {
        triage: counterFixture.sessionTriaged,
        plan: counterFixture.sessionPlanned,
        implement: counterFixture.sessionImplemented,
        review: counterFixture.sessionReviewed,
        merged: counterFixture.mergedCount,
      }

      PIPELINE_STAGES.forEach(stage => {
        const pill = screen.getByTestId(`session-stage-${stage.key}`)
        expect(pill).toHaveTextContent(String(expectedCounts[stage.key] ?? 0))
      })

      const arrows = screen.getAllByText('→')
      expect(arrows.length).toBe(PIPELINE_STAGES.length - 1)
    })

    it('shows abbreviated stage labels in each session pill', () => {
      render(<Header {...defaultProps} />)
      PIPELINE_STAGES.forEach(stage => {
        const pill = screen.getByTestId(`session-stage-${stage.key}`)
        expect(pill).toHaveTextContent(stageAbbreviations[stage.key])
      })
    })

    it('uses pipeline stage colors on each session pill border', () => {
      render(<Header {...defaultProps} />)
      PIPELINE_STAGES.forEach(stage => {
        const pill = screen.getByTestId(`session-stage-${stage.key}`)
        expect(pill.style.borderColor).toBe(stage.color)
      })
    })
  })

  describe('stopping state with active workers', () => {
    const activeWorkers = {
      1: { status: 'running', worker: 1, role: 'implementer', title: 'Issue #1', branch: '', transcript: [], pr: null },
      2: { status: 'done', worker: 2, role: 'implementer', title: 'Issue #2', branch: '', transcript: [], pr: null },
    }
    const allDoneWorkers = {
      1: { status: 'done', worker: 1, role: 'implementer', title: 'Issue #1', branch: '', transcript: [], pr: null },
      2: { status: 'done', worker: 2, role: 'implementer', title: 'Issue #2', branch: '', transcript: [], pr: null },
    }
    const planningWorkers = {
      1: { status: 'planning', worker: 1, role: 'planner', title: 'Plan #1', branch: '', transcript: [], pr: null },
    }

    it('shows Start when orchestratorStatus is idle even with stale active workers', () => {
      mockUseHydraFlow.mockReturnValue({ stageStatus: mockStageStatus(activeWorkers) })
      render(<Header {...defaultProps} orchestratorStatus="idle" />)
      expect(screen.getByText('Start')).toBeInTheDocument()
      expect(screen.queryByText('Stopping\u2026')).toBeNull()
    })

    it('shows Start when idle and all workers are done', () => {
      mockUseHydraFlow.mockReturnValue({ stageStatus: mockStageStatus(allDoneWorkers) })
      render(<Header {...defaultProps} orchestratorStatus="idle" />)
      expect(screen.getByText('Start')).toBeInTheDocument()
      expect(screen.queryByText('Stopping\u2026')).toBeNull()
    })

    it('shows Stopping badge when orchestratorStatus is stopping', () => {
      render(<Header {...defaultProps} orchestratorStatus="stopping" />)
      expect(screen.getByText('Stopping\u2026')).toBeInTheDocument()
      expect(screen.queryByText('Start')).toBeNull()
      expect(screen.queryByText('Stop')).toBeNull()
    })

    it('shows Start when orchestratorStatus is idle even with stale planning workers', () => {
      mockUseHydraFlow.mockReturnValue({ stageStatus: mockStageStatus(planningWorkers) })
      render(<Header {...defaultProps} orchestratorStatus="idle" />)
      expect(screen.getByText('Start')).toBeInTheDocument()
      expect(screen.queryByText('Stopping\u2026')).toBeNull()
    })

    it('shows Start when orchestratorStatus is done and no active workers', () => {
      mockUseHydraFlow.mockReturnValue({ stageStatus: mockStageStatus(allDoneWorkers) })
      render(<Header {...defaultProps} orchestratorStatus="done" />)
      expect(screen.getByText('Start')).toBeInTheDocument()
    })

    it('shows Start when orchestratorStatus is done even with stale active workers', () => {
      mockUseHydraFlow.mockReturnValue({ stageStatus: mockStageStatus(activeWorkers) })
      render(<Header {...defaultProps} orchestratorStatus="done" />)
      expect(screen.getByText('Start')).toBeInTheDocument()
      expect(screen.queryByText('Stopping\u2026')).toBeNull()
    })

    it('shows Credits Paused badge and Stop button when credits_paused', () => {
      render(<Header {...defaultProps} orchestratorStatus="credits_paused" />)
      expect(screen.getByText('Credits Paused')).toBeInTheDocument()
      expect(screen.getByText('Stop')).toBeInTheDocument()
      expect(screen.queryByText('Start')).toBeNull()
    })
  })

  describe('minimum stopping hold timer', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it('clears Stopping immediately when transitioning to idle with no active workers', () => {
      const { rerender } = render(
        <Header {...defaultProps} orchestratorStatus="stopping" />
      )
      expect(screen.getByText('Stopping\u2026')).toBeInTheDocument()

      // Transition to idle with no active workers — second effect clears held state early
      rerender(<Header {...defaultProps} orchestratorStatus="idle" />)

      expect(screen.getByText('Start')).toBeInTheDocument()
    })

    it('holds Stopping badge while workers are still active after idle', () => {
      const activeWorkers = {
        1: { status: 'running', worker: 1, role: 'implementer', title: 'Issue #1', branch: '', transcript: [], pr: null },
      }

      mockUseHydraFlow.mockReturnValue({ stageStatus: mockStageStatus(activeWorkers) })
      const { rerender } = render(
        <Header {...defaultProps} orchestratorStatus="stopping" />
      )
      expect(screen.getByText('Stopping\u2026')).toBeInTheDocument()

      // Status transitions to idle but workers still active
      rerender(<Header {...defaultProps} orchestratorStatus="idle" />)

      // Should still show Stopping because workers are active
      expect(screen.getByText('Stopping\u2026')).toBeInTheDocument()
      expect(screen.queryByText('Start')).toBeNull()

      // Workers finish
      mockUseHydraFlow.mockReturnValue({ stageStatus: mockStageStatus({}) })
      rerender(<Header {...defaultProps} orchestratorStatus="idle" />)

      // Now Start should appear
      expect(screen.getByText('Start')).toBeInTheDocument()
    })

    it('handles disconnect during stopping gracefully', () => {
      render(
        <Header {...defaultProps} orchestratorStatus="stopping" connected={false} />
      )
      expect(screen.getByText('Stopping\u2026')).toBeInTheDocument()
      expect(screen.queryByText('Start')).toBeNull()
    })
  })

  describe('repo-aware indicator', () => {
    it('shows running repos count when runtimes have running repos', () => {
      mockUseHydraFlow.mockReturnValue({
        stageStatus: mockStageStatus(),
        config: null,
        submitReport: vi.fn(),
        runtimes: [
          { slug: 'repo-a', running: true },
          { slug: 'repo-b', running: false },
          { slug: 'repo-c', running: true },
        ],
        supervisedRepos: [
          { slug: 'repo-a', path: 'org/repo-a' },
          { slug: 'repo-b', path: 'org/repo-b' },
          { slug: 'repo-c', path: 'org/repo-c' },
        ],
      })
      render(<Header {...defaultProps} orchestratorStatus="running" />)
      expect(screen.getByTestId('repos-running-badge')).toBeInTheDocument()
      expect(screen.getByTestId('repos-running-badge')).toHaveTextContent('2 / 3 repos')
    })

    it('does not show badge when no supervised repos exist', () => {
      mockUseHydraFlow.mockReturnValue({
        stageStatus: mockStageStatus(),
        config: null,
        submitReport: vi.fn(),
        runtimes: [],
        supervisedRepos: [],
      })
      render(<Header {...defaultProps} />)
      expect(screen.queryByTestId('repos-running-badge')).toBeNull()
    })

    it('shows 0 running when all repos are stopped', () => {
      mockUseHydraFlow.mockReturnValue({
        stageStatus: mockStageStatus(),
        config: null,
        submitReport: vi.fn(),
        runtimes: [
          { slug: 'repo-a', running: false },
        ],
        supervisedRepos: [
          { slug: 'repo-a', path: 'org/repo-a' },
        ],
      })
      render(<Header {...defaultProps} />)
      expect(screen.getByTestId('repos-running-badge')).toHaveTextContent('0 / 1 repo')
    })

    it('shows singular "repo" for single supervised repo', () => {
      mockUseHydraFlow.mockReturnValue({
        stageStatus: mockStageStatus(),
        config: null,
        submitReport: vi.fn(),
        runtimes: [
          { slug: 'repo-a', running: true },
        ],
        supervisedRepos: [
          { slug: 'repo-a', path: 'org/repo-a' },
        ],
      })
      render(<Header {...defaultProps} />)
      expect(screen.getByTestId('repos-running-badge')).toHaveTextContent('1 / 1 repo')
    })

    it('handles missing runtimes gracefully', () => {
      mockUseHydraFlow.mockReturnValue({
        stageStatus: mockStageStatus(),
        config: null,
        submitReport: vi.fn(),
        supervisedRepos: [
          { slug: 'repo-a', path: 'org/repo-a' },
        ],
      })
      render(<Header {...defaultProps} />)
      expect(screen.getByTestId('repos-running-badge')).toHaveTextContent('0 / 1 repo')
    })

    it('applies green color to badge when at least one repo is running', () => {
      mockUseHydraFlow.mockReturnValue({
        stageStatus: mockStageStatus(),
        config: null,
        submitReport: vi.fn(),
        runtimes: [{ slug: 'repo-a', running: true }],
        supervisedRepos: [{ slug: 'repo-a', path: 'org/repo-a' }],
      })
      render(<Header {...defaultProps} />)
      const badge = screen.getByTestId('repos-running-badge')
      expect(badge.style.color).toBe(theme.green)
      expect(badge.style.borderColor).toBe(theme.green)
    })

    it('applies muted color to badge when no repos are running', () => {
      mockUseHydraFlow.mockReturnValue({
        stageStatus: mockStageStatus(),
        config: null,
        submitReport: vi.fn(),
        runtimes: [{ slug: 'repo-a', running: false }],
        supervisedRepos: [{ slug: 'repo-a', path: 'org/repo-a' }],
      })
      render(<Header {...defaultProps} />)
      const badge = screen.getByTestId('repos-running-badge')
      expect(badge.style.color).toBe(theme.textMuted)
    })

    it('excludes non-supervised runtimes from running count', () => {
      mockUseHydraFlow.mockReturnValue({
        stageStatus: mockStageStatus(),
        config: null,
        submitReport: vi.fn(),
        runtimes: [
          { slug: 'supervised', running: true },
          { slug: 'unsupervised', running: true },
        ],
        supervisedRepos: [{ slug: 'supervised', path: 'org/supervised' }],
      })
      render(<Header {...defaultProps} />)
      expect(screen.getByTestId('repos-running-badge')).toHaveTextContent('1 / 1 repo')
    })
  })

  describe('Report button', () => {
    it('renders in idle state', () => {
      render(<Header {...defaultProps} orchestratorStatus="idle" />)
      expect(screen.getByTestId('report-button')).toBeInTheDocument()
    })

    it('renders in running state', () => {
      render(<Header {...defaultProps} orchestratorStatus="running" />)
      expect(screen.getByTestId('report-button')).toBeInTheDocument()
    })

    it('renders in stopping state', () => {
      render(<Header {...defaultProps} orchestratorStatus="stopping" />)
      expect(screen.getByTestId('report-button')).toBeInTheDocument()
    })

    it('renders in done state', () => {
      render(<Header {...defaultProps} orchestratorStatus="done" />)
      expect(screen.getByTestId('report-button')).toBeInTheDocument()
    })

    it('is disabled when disconnected', () => {
      render(<Header {...defaultProps} connected={false} />)
      const btn = screen.getByTestId('report-button')
      expect(btn).toBeDisabled()
    })

    it('is enabled when connected', () => {
      render(<Header {...defaultProps} connected={true} />)
      const btn = screen.getByTestId('report-button')
      expect(btn).not.toBeDisabled()
    })

    it('opens modal with screenshot thumbnail after capture', async () => {
      html2canvasFn.mockResolvedValue({
        toDataURL: () => 'data:image/png;base64,header-screenshot',
      })

      const root = createRootContainer()

      render(<Header {...defaultProps} connected={true} />, { container: root })
      fireEvent.click(screen.getByTestId('report-button'))

      await waitFor(() => {
        expect(screen.getByTestId('report-modal-overlay')).toBeInTheDocument()
        expect(screen.getByTestId('screenshot-thumbnail')).toBeInTheDocument()
      })
      expect(html2canvasFn).toHaveBeenCalledTimes(1)
    })

    it('retries screenshot capture with safe mode when first pass fails', async () => {
      html2canvasFn
        .mockRejectedValueOnce(new Error('primary failed'))
        .mockResolvedValueOnce({
          toDataURL: () => 'data:image/png;base64,safe-mode-screenshot',
        })

      const root = createRootContainer()

      render(<Header {...defaultProps} connected={true} />, { container: root })
      fireEvent.click(screen.getByTestId('report-button'))

      await waitFor(() => {
        expect(screen.getByTestId('report-modal-overlay')).toBeInTheDocument()
        expect(screen.getByTestId('screenshot-thumbnail')).toBeInTheDocument()
      })
      expect(html2canvasFn).toHaveBeenCalledTimes(2)
    })
  })
})
