import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { deriveStageStatus } from '../../hooks/useStageStatus'
import { PIPELINE_STAGES } from '../../constants'
import {
  dotConnected, dotDisconnected,
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
  mockUseHydraFlow.mockReturnValue({
    stageStatus: mockStageStatus(),
    config: null,
    submitReport: vi.fn(),
    startOrchestrator: vi.fn(),
    stopOrchestrator: vi.fn(),
  })
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

  it('style objects are referentially stable', () => {
    expect(dotConnected).toBe(dotConnected)
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
  }

  it('renders without errors', () => {
    render(<Header {...defaultProps} />)
    expect(screen.getByText('HYDRAFLOW')).toBeInTheDocument()
  })

  it('renders Start button when orchestrator is idle', () => {
    render(<Header {...defaultProps} />)
    expect(screen.getByTestId('header-start-button')).toBeInTheDocument()
  })

  it('renders Stop button when orchestrator is running', () => {
    render(<Header {...defaultProps} orchestratorStatus="running" />)
    expect(screen.getByTestId('header-stop-button')).toBeInTheDocument()
  })

  it('renders Stopping badge when orchestrator is stopping', () => {
    render(<Header {...defaultProps} orchestratorStatus="stopping" />)
    expect(screen.getByText('Stopping\u2026')).toBeInTheDocument()
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

  it('does not render Session label', () => {
    render(<Header {...defaultProps} />)
    expect(screen.queryByText('Session')).toBeNull()
    // pipeline row must still be present to confirm the container rendered
    expect(screen.getByTestId('session-pipeline')).toBeInTheDocument()
  })

  it('session box has accessible aria-label', () => {
    render(<Header {...defaultProps} />)
    const sessionBox = screen.getByTestId('session-box')
    expect(sessionBox).toHaveAttribute('aria-label', 'Session pipeline statistics')
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
    const reportBtn = screen.getByTestId('report-button')
    const controlsDiv = reportBtn.parentElement
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
    const reportBtn = screen.getByTestId('report-button')
    const controlsDiv = reportBtn.parentElement
    expect(controlsDiv.style.flexShrink).toBe('0')
  })

  it('calls startOrchestrator when Start is clicked', () => {
    const startOrchestrator = vi.fn()
    mockUseHydraFlow.mockReturnValue({
      stageStatus: mockStageStatus(),
      config: null,
      submitReport: vi.fn(),
      startOrchestrator,
      stopOrchestrator: vi.fn(),
    })
    render(<Header {...defaultProps} orchestratorStatus="idle" />)
    fireEvent.click(screen.getByTestId('header-start-button'))
    expect(startOrchestrator).toHaveBeenCalled()
  })

  it('calls stopOrchestrator when Stop is clicked', () => {
    const stopOrchestrator = vi.fn()
    mockUseHydraFlow.mockReturnValue({
      stageStatus: mockStageStatus(),
      config: null,
      submitReport: vi.fn(),
      startOrchestrator: vi.fn(),
      stopOrchestrator,
    })
    render(<Header {...defaultProps} orchestratorStatus="running" />)
    fireEvent.click(screen.getByTestId('header-stop-button'))
    expect(stopOrchestrator).toHaveBeenCalled()
  })

  it('center section has minWidth 0 and overflow hidden for graceful truncation', () => {
    render(<Header {...defaultProps} />)
    const sessionBox = screen.getByTestId('session-box')
    const centerDiv = sessionBox.parentElement
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

      const arrows = screen.getAllByText('\u2192')
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

  describe('Report button', () => {
    it('renders as an icon button with aria-label', () => {
      render(<Header {...defaultProps} />)
      const btn = screen.getByTestId('report-button')
      expect(btn).toBeInTheDocument()
      expect(btn.getAttribute('aria-label')).toBe('Report issue')
    })

    it('contains an SVG icon instead of text', () => {
      render(<Header {...defaultProps} />)
      const btn = screen.getByTestId('report-button')
      expect(btn.querySelector('svg')).not.toBeNull()
      expect(btn.textContent).toBe('')
    })

    it('has a title attribute for tooltip', () => {
      render(<Header {...defaultProps} />)
      const btn = screen.getByTestId('report-button')
      expect(btn.getAttribute('title')).toBe('Report issue')
    })

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

    it('opens modal without screenshot when all capture attempts fail', async () => {
      html2canvasFn
        .mockRejectedValueOnce(new Error('attempt 1 failed'))
        .mockRejectedValueOnce(new Error('attempt 2 failed'))
        .mockRejectedValueOnce(new Error('attempt 3 failed'))

      const root = createRootContainer()

      render(<Header {...defaultProps} connected={true} />, { container: root })
      fireEvent.click(screen.getByTestId('report-button'))

      await waitFor(() => {
        expect(screen.getByTestId('report-modal-overlay')).toBeInTheDocument()
      })
      expect(screen.queryByTestId('screenshot-thumbnail')).toBeNull()
      expect(html2canvasFn).toHaveBeenCalledTimes(3)
    })
  })
})
