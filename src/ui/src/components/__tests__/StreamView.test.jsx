import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PIPELINE_STAGES } from '../../constants'
import { deriveStageStatus } from '../../hooks/useStageStatus'
import { STAGE_KEYS } from '../../hooks/useTimeline'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { StreamView, toStreamIssue, findWorkerTranscript } = await import('../StreamView')

function defaultHydraFlowContext(overrides = {}) {
  const defaultPipeline = { triage: [], plan: [], implement: [], review: [], merged: [] }
  const pipelineIssues = overrides.pipelineIssues
    ? { ...defaultPipeline, ...overrides.pipelineIssues }
    : defaultPipeline
  const workers = overrides.workers || {}
  const backgroundWorkers = overrides.backgroundWorkers || []
  const config = overrides.config || { max_triagers: 1, max_planners: 2, max_workers: 3, max_reviewers: 2 }
  return {
    pipelineIssues,
    workers,
    prs: [],
    config,
    backgroundWorkers,
    stageStatus: deriveStageStatus(
      pipelineIssues,
      workers,
      backgroundWorkers,
      {},
      config,
    ),
    ...overrides,
  }
}

const defaultHydraFlow = defaultHydraFlowContext()

beforeEach(() => {
  mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext())
})

// All stages open by default for test visibility
const allExpanded = Object.fromEntries(PIPELINE_STAGES.map(s => [s.key, true]))

const defaultProps = {
  intents: [],
  expandedStages: allExpanded,
  onToggleStage: () => {},
  onRequestChanges: () => {},
}

const basePipeIssue = {
  issue_number: 42,
  title: 'Test issue',
  url: 'https://github.com/test/42',
}

describe('StreamView stage indicators', () => {
  it('keeps stream card horizontal inset aligned with its stage header', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        review: [{ issue_number: 42, title: 'Review card', status: 'queued' }],
      },
    }))
    render(<StreamView {...defaultProps} />)

    const header = screen.getByTestId('stage-header-review')
    const card = screen.getByTestId('stream-card-42')

    expect(header.style.margin).toBe('8px 8px 4px')
    expect(card.style.margin).toBe('0px 8px 8px')
  })

  describe('Status dot colors', () => {
    it('shows green dot when stage has active workers', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        workers: {
          'triage-5': { status: 'evaluating', worker: 1, role: 'triage', title: 'Triage #5', branch: '', transcript: [], pr: null },
        },
        pipelineIssues: {
          triage: [{ issue_number: 5, title: 'Test', status: 'active' }],
          plan: [], implement: [], review: [],
        },
        backgroundWorkers: [
          { name: 'triage', status: 'ok', enabled: true, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      const dot = screen.getByTestId('stage-dot-triage')
      expect(dot.style.background).toBe('var(--green)')
    })

    it('shows yellow dot when stage is enabled but no active workers', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        backgroundWorkers: [
          { name: 'plan', status: 'ok', enabled: true, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      const dot = screen.getByTestId('stage-dot-plan')
      expect(dot.style.background).toBe('var(--yellow)')
    })

    it('shows red dot when stage is disabled', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        backgroundWorkers: [
          { name: 'implement', status: 'ok', enabled: false, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      const dot = screen.getByTestId('stage-dot-implement')
      expect(dot.style.background).toBe('var(--red)')
    })

    it('defaults to enabled (yellow) when no backgroundWorkers entry exists', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        backgroundWorkers: [],
      }))
      render(<StreamView {...defaultProps} />)
      const dot = screen.getByTestId('stage-dot-triage')
      expect(dot.style.background).toBe('var(--yellow)')
    })
  })

  describe('Disabled badge', () => {
    it('shows "Disabled" badge when stage is disabled', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        backgroundWorkers: [
          { name: 'review', status: 'ok', enabled: false, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      expect(screen.getByTestId('stage-disabled-review')).toHaveTextContent('Disabled')
    })

    it('does not show "Disabled" badge when stage is enabled', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        backgroundWorkers: [
          { name: 'review', status: 'ok', enabled: true, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      expect(screen.queryByTestId('stage-disabled-review')).not.toBeInTheDocument()
    })
  })

  describe('Opacity dimming', () => {
    it('applies reduced opacity when stage is disabled', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        backgroundWorkers: [
          { name: 'implement', status: 'ok', enabled: false, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      const section = screen.getByTestId('stage-section-implement')
      expect(section.style.opacity).toBe('0.5')
    })

    it('has full opacity when stage is enabled', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        backgroundWorkers: [
          { name: 'implement', status: 'ok', enabled: true, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      const section = screen.getByTestId('stage-section-implement')
      expect(section.style.opacity).toBe('1')
    })
  })

  describe('Merged stage dot', () => {
    it('renders green status dot for merged stage', () => {
      render(<StreamView {...defaultProps} />)
      const dot = screen.getByTestId('stage-dot-merged')
      expect(dot).toBeInTheDocument()
      expect(dot.style.background).toBe('var(--green)')
    })
  })

  describe('Multiple stages with mixed states', () => {
    it('shows correct indicators for multiple stages simultaneously', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        workers: {
          'triage-5': { status: 'evaluating', worker: 1, role: 'triage', title: 'Triage #5', branch: '', transcript: [], pr: null },
        },
        backgroundWorkers: [
          { name: 'triage', status: 'ok', enabled: true, last_run: null, details: {} },
          { name: 'plan', status: 'ok', enabled: true, last_run: null, details: {} },
          { name: 'implement', status: 'ok', enabled: false, last_run: null, details: {} },
          { name: 'review', status: 'ok', enabled: true, last_run: null, details: {} },
        ],
      }))
      render(<StreamView {...defaultProps} />)
      // Triage: enabled + active worker = green
      expect(screen.getByTestId('stage-dot-triage').style.background).toBe('var(--green)')
      // Plan: enabled + no workers = yellow
      expect(screen.getByTestId('stage-dot-plan').style.background).toBe('var(--yellow)')
      // Implement: disabled = red
      expect(screen.getByTestId('stage-dot-implement').style.background).toBe('var(--red)')
      // Review: enabled + no workers = yellow
      expect(screen.getByTestId('stage-dot-review').style.background).toBe('var(--yellow)')

      // Only implement should be disabled
      expect(screen.getByTestId('stage-disabled-implement')).toBeInTheDocument()
      expect(screen.queryByTestId('stage-disabled-triage')).not.toBeInTheDocument()
      expect(screen.queryByTestId('stage-disabled-plan')).not.toBeInTheDocument()
      expect(screen.queryByTestId('stage-disabled-review')).not.toBeInTheDocument()

      // Opacity check
      expect(screen.getByTestId('stage-section-implement').style.opacity).toBe('0.5')
      expect(screen.getByTestId('stage-section-triage').style.opacity).toBe('1')
    })
  })
})

describe('toStreamIssue status mapping', () => {
  it('maps active status to overallStatus active', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'plan', [])
    expect(result.overallStatus).toBe('active')
  })

  it('maps queued status to overallStatus queued', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'queued' }, 'plan', [])
    expect(result.overallStatus).toBe('queued')
  })

  it('maps hitl status to overallStatus hitl', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'hitl' }, 'plan', [])
    expect(result.overallStatus).toBe('hitl')
  })

  it('maps failed status to overallStatus failed', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'failed' }, 'plan', [])
    expect(result.overallStatus).toBe('failed')
  })

  it('maps error status to overallStatus failed', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'error' }, 'plan', [])
    expect(result.overallStatus).toBe('failed')
  })

  it('maps done status to overallStatus done', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'done' }, 'merged', [])
    expect(result.overallStatus).toBe('done')
  })

  it('maps unknown status to overallStatus queued', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'something_else' }, 'plan', [])
    expect(result.overallStatus).toBe('queued')
  })

  it('defaults to queued when status is undefined', () => {
    const result = toStreamIssue({ ...basePipeIssue }, 'plan', [])
    expect(result.overallStatus).toBe('queued')
  })
})

describe('toStreamIssue stage building', () => {
  it('sets all stages to done for merged/done items', () => {
    const result = toStreamIssue(
      { issue_number: 10, title: 'Test', status: 'done' },
      'merged',
      []
    )
    for (const key of STAGE_KEYS) {
      expect(result.stages[key].status).toBe('done')
    }
    expect(result.overallStatus).toBe('done')
  })

  it('sets current stage to active when issue status is active', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'implement', [])
    expect(result.stages.triage.status).toBe('done')
    expect(result.stages.plan.status).toBe('done')
    expect(result.stages.implement.status).toBe('active')
    expect(result.stages.review.status).toBe('pending')
    expect(result.stages.merged.status).toBe('pending')
    expect(result.overallStatus).toBe('active')
  })

  it('sets current stage to queued when issue status is queued', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'queued' }, 'implement', [])
    expect(result.stages.triage.status).toBe('done')
    expect(result.stages.plan.status).toBe('done')
    expect(result.stages.implement.status).toBe('queued')
    expect(result.stages.review.status).toBe('pending')
    expect(result.stages.merged.status).toBe('pending')
    expect(result.overallStatus).toBe('queued')
  })

  it('sets current stage to failed for failed items', () => {
    const result = toStreamIssue(
      { issue_number: 10, title: 'Test', status: 'failed' },
      'implement',
      []
    )
    expect(result.overallStatus).toBe('failed')
    expect(result.stages.triage.status).toBe('done')
    expect(result.stages.plan.status).toBe('done')
    expect(result.stages.implement.status).toBe('failed')
    expect(result.stages.review.status).toBe('pending')
    expect(result.stages.merged.status).toBe('pending')
  })

  it('sets current stage to hitl for hitl items', () => {
    const result = toStreamIssue(
      { issue_number: 10, title: 'Test', status: 'hitl' },
      'review',
      []
    )
    expect(result.overallStatus).toBe('hitl')
    expect(result.stages.triage.status).toBe('done')
    expect(result.stages.plan.status).toBe('done')
    expect(result.stages.implement.status).toBe('done')
    expect(result.stages.review.status).toBe('hitl')
    expect(result.stages.merged.status).toBe('pending')
  })

  it('sets prior stages to done', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'review', [])
    expect(result.stages.triage.status).toBe('done')
    expect(result.stages.plan.status).toBe('done')
    expect(result.stages.implement.status).toBe('done')
  })

  it('sets later stages to pending', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'plan', [])
    expect(result.stages.implement.status).toBe('pending')
    expect(result.stages.review.status).toBe('pending')
    expect(result.stages.merged.status).toBe('pending')
  })
})

describe('toStreamIssue output shape', () => {
  it('returns correct issueNumber and title', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'plan', [])
    expect(result.issueNumber).toBe(42)
    expect(result.title).toBe('Test issue')
  })

  it('returns currentStage matching the stageKey argument', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'implement', [])
    expect(result.currentStage).toBe('implement')
  })

  it('builds a stages object with all STAGE_KEYS', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'plan', [])
    for (const key of STAGE_KEYS) {
      expect(result.stages).toHaveProperty(key)
      expect(result.stages[key]).toHaveProperty('status')
      expect(result.stages[key]).toHaveProperty('startTime')
      expect(result.stages[key]).toHaveProperty('endTime')
      expect(result.stages[key]).toHaveProperty('transcript')
    }
  })

  it('matches PR from prs array by issue_number', () => {
    const prs = [{ issue: 42, pr: 100, url: 'https://github.com/pr/100' }]
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'review', prs)
    expect(result.pr).toEqual({ number: 100, url: 'https://github.com/pr/100' })
  })

  it('returns null pr when no matching PR exists', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'plan', [])
    expect(result.pr).toBeNull()
  })

  it('passes through issueUrl from pipeIssue url field', () => {
    const result = toStreamIssue({ ...basePipeIssue, status: 'active' }, 'plan', [])
    expect(result.issueUrl).toBe('https://github.com/test/42')
  })

  it('returns null issueUrl when url is empty', () => {
    const result = toStreamIssue(
      { issue_number: 1, title: 'X', url: '', status: 'active' },
      'plan',
      []
    )
    expect(result.issueUrl).toBeNull()
  })

  it('returns null issueUrl when url is missing', () => {
    const result = toStreamIssue(
      { issue_number: 1, title: 'X', status: 'active' },
      'plan',
      []
    )
    expect(result.issueUrl).toBeNull()
  })
})

describe('Stage header failed/hitl counts', () => {
  it('shows failed count when stage has failed issues', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        pipelineIssues: {
          triage: [], plan: [], review: [],
        implement: [
          { issue_number: 1, title: 'Active issue', status: 'active' },
          { issue_number: 2, title: 'Failed issue', status: 'failed' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-implement')
    expect(section.textContent).toContain('1 failed')
  })

  it('shows hitl count when stage has hitl issues', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        pipelineIssues: {
          triage: [], plan: [], implement: [],
        review: [
          { issue_number: 1, title: 'Active issue', status: 'active' },
          { issue_number: 2, title: 'HITL issue', status: 'hitl' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-review')
    expect(section.textContent).toContain('1 hitl')
  })

  it('hides failed and hitl counts when zero', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        pipelineIssues: {
          triage: [], implement: [], review: [],
        plan: [
          { issue_number: 1, title: 'Active issue', status: 'active' },
          { issue_number: 2, title: 'Queued issue', status: 'queued' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-plan')
    expect(section.textContent).not.toContain('failed')
    expect(section.textContent).not.toContain('hitl')
  })

  it('excludes failed and hitl from queued count', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        pipelineIssues: {
          triage: [], plan: [], review: [],
        implement: [
          { issue_number: 1, title: 'Active', status: 'active' },
          { issue_number: 2, title: 'Failed', status: 'failed' },
          { issue_number: 3, title: 'HITL', status: 'hitl' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-implement')
    expect(section.textContent).toContain('0 queued')
    expect(section.textContent).toContain('1 failed')
    expect(section.textContent).toContain('1 hitl')
  })

  it('shows correct counts with only failed issues (no active/queued)', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
        pipelineIssues: {
          triage: [], plan: [], review: [],
        implement: [
          { issue_number: 1, title: 'Failed 1', status: 'failed' },
          { issue_number: 2, title: 'Failed 2', status: 'failed' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-implement')
    expect(section.textContent).toContain('0 queued')
    expect(section.textContent).toContain('2 failed')
  })
})

describe('PipelineFlow visualization', () => {
  it('renders "Pipeline Flow" label in the flow indicator', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [{ issue_number: 1, title: 'Test', status: 'queued' }],
        plan: [], implement: [], review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const flow = screen.getByTestId('pipeline-flow')
    expect(flow.textContent).toContain('Pipeline Flow')
  })

  it('renders all pipeline stage labels in the flow', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [{ issue_number: 1, title: 'Test', status: 'queued' }],
        plan: [], implement: [], review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const flow = screen.getByTestId('pipeline-flow')
    expect(flow).toBeInTheDocument()
    expect(flow.textContent).toContain('Triage')
    expect(flow.textContent).toContain('Plan')
    expect(flow.textContent).toContain('Implement')
    expect(flow.textContent).toContain('Review')
    expect(flow.textContent).toContain('Merged')
  })

  it('renders dots for issues at their current stage', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [
          { issue_number: 10, title: 'Plan issue', status: 'queued' },
          { issue_number: 11, title: 'Plan issue 2', status: 'active' },
        ],
        implement: [],
        review: [{ issue_number: 20, title: 'Review issue', status: 'active' }],
      },
    }))
    render(<StreamView {...defaultProps} />)
    expect(screen.getByTestId('flow-dot-10')).toBeInTheDocument()
    expect(screen.getByTestId('flow-dot-11')).toBeInTheDocument()
    expect(screen.getByTestId('flow-dot-20')).toBeInTheDocument()
  })

  it('renders pipeline flow even when no issues exist', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: { triage: [], plan: [], implement: [], review: [] },
    }))
    render(<StreamView {...defaultProps} />)
    const flow = screen.getByTestId('pipeline-flow')
    expect(flow).toBeInTheDocument()
    expect(flow.textContent).toContain('Triage')
    expect(flow.textContent).toContain('Plan')
    expect(flow.textContent).toContain('Implement')
    expect(flow.textContent).toContain('Review')
    expect(flow.textContent).toContain('Merged')
  })

  it('shows all stage labels even when some stages have no issues', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [{ issue_number: 5, title: 'Only plan', status: 'queued' }],
        implement: [], review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const flow = screen.getByTestId('pipeline-flow')
    expect(flow.textContent).toContain('Triage')
    expect(flow.textContent).toContain('Plan')
    expect(flow.textContent).toContain('Implement')
    expect(flow.textContent).toContain('Review')
    expect(flow.textContent).toContain('Merged')
  })

  it('applies pulse animation to active issue dots', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [
          { issue_number: 10, title: 'Active', status: 'active' },
          { issue_number: 11, title: 'Queued', status: 'queued' },
        ],
        implement: [], review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const activeDot = screen.getByTestId('flow-dot-10')
    const queuedDot = screen.getByTestId('flow-dot-11')
    expect(activeDot.style.animation).toContain('stream-pulse')
    expect(queuedDot.style.animation).toBe('')
  })
})

describe('Merged stage rendering', () => {
  it('renders merged PR issues in the merged stage section', () => {
      mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      prs: [{ pr: 42, issue: 10, title: 'Fix bug', merged: true, url: 'https://github.com/test/pr/42' }],
    }))
    render(<StreamView {...defaultProps} />)
    expect(screen.getByText('#10')).toBeInTheDocument()
    expect(screen.getByText('Fix bug')).toBeInTheDocument()
    // Merged-from-PR cards should NOT use the PR url as an issue link
    expect(screen.getByText('#10').tagName).toBe('SPAN')
  })

  it('renders merged PR issue as a dot in PipelineFlow', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      prs: [{ pr: 42, issue: 10, title: 'Fix bug', merged: true, url: 'https://github.com/test/pr/42' }],
    }))
    render(<StreamView {...defaultProps} />)
    expect(screen.getByTestId('pipeline-flow')).toBeInTheDocument()
    const dot = screen.getByTestId('flow-dot-10')
    expect(dot).toBeInTheDocument()
    expect(dot.style.animation).toBe('')
  })

  it('does not set issueUrl from PR url for merged-from-PR cards', () => {
    // PRData.url is a PR URL, not an issue URL — merged cards should have issueUrl null
    const result = toStreamIssue(
      { issue_number: 10, title: 'Fix bug', url: null, status: 'done' },
      'merged',
      []
    )
    expect(result.issueUrl).toBeNull()
  })
})

describe('Merged stage count display', () => {
  it('shows merged item count instead of worker metrics', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      prs: [{ pr: 42, issue: 10, title: 'Fix bug', merged: true, url: 'https://github.com/test/pr/42' }],
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-merged')
    expect(section.textContent).toContain('1 merged')
    expect(section.textContent).not.toContain('active')
    expect(section.textContent).not.toContain('queued')
    expect(section.textContent).not.toContain('workers')
  })

  it('shows correct count with multiple merged items', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      prs: [
        { pr: 42, issue: 10, title: 'Fix bug', merged: true, url: 'https://github.com/test/pr/42' },
        { pr: 43, issue: 11, title: 'Add feature', merged: true, url: 'https://github.com/test/pr/43' },
        { pr: 44, issue: 12, title: 'Refactor', merged: true, url: 'https://github.com/test/pr/44' },
      ],
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-merged')
    expect(section.textContent).toContain('3 merged')
  })

  it('shows "0 merged" when no merged items exist', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext())
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-merged')
    expect(section.textContent).toContain('0 merged')
  })

  it('does not affect worker metrics display on non-merged stages', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [], plan: [], review: [],
        implement: [
          { issue_number: 1, title: 'Active issue', status: 'active' },
          { issue_number: 2, title: 'Queued issue', status: 'queued' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-implement')
    expect(section.textContent).toContain('1 queued')
    expect(section.textContent).toContain('workers')
  })

  it('counts items from pipelineIssues.merged', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [], plan: [], implement: [], review: [],
        merged: [
          { issue_number: 5, title: 'Pipeline merged issue', status: 'done' },
          { issue_number: 6, title: 'Another merged issue', status: 'done' },
        ],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-merged')
    expect(section.textContent).toContain('2 merged')
  })

  it('deduplicates items present in both pipelineIssues.merged and prs', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [], plan: [], implement: [], review: [],
        merged: [
          { issue_number: 10, title: 'Shared issue', status: 'done' },
        ],
      },
      prs: [
        { pr: 42, issue: 10, title: 'Shared issue', merged: true, url: 'https://github.com/test/pr/42' },
        { pr: 43, issue: 11, title: 'PR-only issue', merged: true, url: 'https://github.com/test/pr/43' },
      ],
    }))
    render(<StreamView {...defaultProps} />)
    const section = screen.getByTestId('stage-section-merged')
    // issue 10 appears in both sources — should count once; issue 11 from prs only
    expect(section.textContent).toContain('2 merged')
  })
})

describe('PipelineFlow failed and hitl dots', () => {
  it('renders failed dots with red background and no animation', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [
          { issue_number: 1, title: 'Failed issue', status: 'failed' },
        ],
        review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const dot = screen.getByTestId('flow-dot-1')
    expect(dot).toBeInTheDocument()
    expect(dot.style.background).toBe('var(--red)')
    expect(dot.style.animation).toBe('')
  })

  it('renders hitl dots with yellow background and no animation', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [
          { issue_number: 2, title: 'HITL issue', status: 'hitl' },
        ],
        review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const dot = screen.getByTestId('flow-dot-2')
    expect(dot).toBeInTheDocument()
    expect(dot.style.background).toBe('var(--yellow)')
    expect(dot.style.animation).toBe('')
  })

  it('renders queued dots with subtle stage color', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [
          { issue_number: 3, title: 'Queued issue', status: 'queued' },
        ],
        review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const dot = screen.getByTestId('flow-dot-3')
    expect(dot.style.background).toBe('var(--accent-subtle)')
    expect(dot.style.animation).toBe('')
  })

  it('renders mixed status dots with correct colors in the same stage', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [
          { issue_number: 10, title: 'Active', status: 'active' },
          { issue_number: 11, title: 'Failed', status: 'failed' },
          { issue_number: 12, title: 'HITL', status: 'hitl' },
          { issue_number: 13, title: 'Queued', status: 'queued' },
        ],
        review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    // Active: stage color (accent) + pulse animation
    const activeDot = screen.getByTestId('flow-dot-10')
    expect(activeDot.style.background).toBe('var(--accent)')
    expect(activeDot.style.animation).toContain('stream-pulse')
    // Failed: red, no animation
    const failedDot = screen.getByTestId('flow-dot-11')
    expect(failedDot.style.background).toBe('var(--red)')
    expect(failedDot.style.animation).toBe('')
    // HITL: yellow, no animation
    const hitlDot = screen.getByTestId('flow-dot-12')
    expect(hitlDot.style.background).toBe('var(--yellow)')
    expect(hitlDot.style.animation).toBe('')
    // Queued: subtle stage color (accent), no animation
    const queuedDot = screen.getByTestId('flow-dot-13')
    expect(queuedDot.style.background).toBe('var(--accent-subtle)')
    expect(queuedDot.style.animation).toBe('')
  })
})

describe('PipelineFlow summary counts', () => {
  it('shows summary counts when merged and failed issues exist', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [
          { issue_number: 1, title: 'Failed', status: 'failed' },
        ],
        review: [],
      },
      prs: [
        { pr: 42, issue: 10, title: 'Fix bug', merged: true, url: 'https://github.com/test/pr/42' },
        { pr: 43, issue: 11, title: 'Add feature', merged: true, url: 'https://github.com/test/pr/43' },
      ],
    }))
    render(<StreamView {...defaultProps} />)
    const summary = screen.getByTestId('flow-summary')
    expect(summary).toBeInTheDocument()
    expect(summary.textContent).toContain('2 merged')
    expect(summary.textContent).toContain('1 failed')
  })

  it('shows only merged count when no failed issues', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [],
        review: [],
      },
      prs: [
        { pr: 42, issue: 10, title: 'Fix bug', merged: true, url: 'https://github.com/test/pr/42' },
      ],
    }))
    render(<StreamView {...defaultProps} />)
    const summary = screen.getByTestId('flow-summary')
    expect(summary.textContent).toContain('1 merged')
    expect(summary.textContent).not.toContain('failed')
  })

  it('shows only failed count when no merged issues', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [],
        implement: [
          { issue_number: 1, title: 'Failed', status: 'failed' },
        ],
        review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    const summary = screen.getByTestId('flow-summary')
    expect(summary.textContent).toContain('1 failed')
    expect(summary.textContent).not.toContain('merged')
  })

  it('hides summary when both counts are zero', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [],
        plan: [{ issue_number: 1, title: 'Queued', status: 'queued' }],
        implement: [],
        review: [],
      },
    }))
    render(<StreamView {...defaultProps} />)
    expect(screen.queryByTestId('flow-summary')).not.toBeInTheDocument()
  })
})

describe('findWorkerTranscript', () => {
  const workers = {
    'triage-42': { transcript: ['triaging issue 42'] },
    'plan-42': { transcript: ['planning issue 42'] },
    '42': { transcript: ['implementing issue 42'] },
    'review-100': { transcript: ['reviewing PR 100'] },
  }
  const prs = [{ issue: 42, pr: 100, url: 'https://github.com/pr/100' }]

  it('matches triage worker by triage-{issueNumber} key', () => {
    const result = findWorkerTranscript(workers, prs, 'triage', 42)
    expect(result).toEqual(['triaging issue 42'])
  })

  it('matches plan worker by plan-{issueNumber} key', () => {
    const result = findWorkerTranscript(workers, prs, 'plan', 42)
    expect(result).toEqual(['planning issue 42'])
  })

  it('matches implement worker by bare issue number key', () => {
    const result = findWorkerTranscript(workers, prs, 'implement', 42)
    expect(result).toEqual(['implementing issue 42'])
  })

  it('matches review worker via PR lookup to review-{prNumber} key', () => {
    const result = findWorkerTranscript(workers, prs, 'review', 42)
    expect(result).toEqual(['reviewing PR 100'])
  })

  it('returns empty array when no matching worker exists', () => {
    const result = findWorkerTranscript(workers, prs, 'implement', 999)
    expect(result).toEqual([])
  })

  it('returns empty array for merged stage', () => {
    const result = findWorkerTranscript(workers, prs, 'merged', 42)
    expect(result).toEqual([])
  })

  it('returns empty array when worker exists but has no transcript', () => {
    const workersNoTranscript = { '42': { status: 'running' } }
    const result = findWorkerTranscript(workersNoTranscript, [], 'implement', 42)
    expect(result).toEqual([])
  })

  it('returns empty array when workers is null', () => {
    const result = findWorkerTranscript(null, prs, 'triage', 42)
    expect(result).toEqual([])
  })

  it('returns empty array for review when no PR exists for issue', () => {
    const result = findWorkerTranscript(workers, [], 'review', 42)
    expect(result).toEqual([])
  })
})

describe('StreamView transcript integration', () => {
  it('passes transcript to StreamCard for active issue with matching worker', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [], plan: [], review: [],
        implement: [{ issue_number: 42, title: 'Test issue', status: 'active' }],
      },
      workers: {
        '42': { status: 'running', worker: 1, role: 'implementer', title: 'Test issue', branch: '', transcript: ['line 1', 'line 2', 'line 3'], pr: null },
      },
    }))
    render(<StreamView {...defaultProps} />)
    // Active card should be expanded by default and show transcript preview
    expect(screen.getByTestId('transcript-preview')).toBeInTheDocument()
    expect(screen.getByText('line 1')).toBeInTheDocument()
  })

  it('does not show transcript for queued issues even with worker data', () => {
    mockUseHydraFlow.mockReturnValue(defaultHydraFlowContext({
      pipelineIssues: {
        triage: [], plan: [], review: [],
        implement: [{ issue_number: 42, title: 'Test issue', status: 'queued' }],
      },
      workers: {
        '42': { status: 'queued', worker: 1, role: 'implementer', title: 'Test issue', branch: '', transcript: ['line 1'], pr: null },
      },
    }))
    render(<StreamView {...defaultProps} />)
    expect(screen.queryByTestId('transcript-preview')).not.toBeInTheDocument()
  })
})
