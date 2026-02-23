import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { MetricsPanel } = await import('../MetricsPanel')

const emptyStage = { issueCount: 0, activeCount: 0, queuedCount: 0, workerCount: 0, enabled: true, sessionCount: 0 }

function mockStageStatusFromSession(sessionCounts = {}) {
  return {
    triage: { ...emptyStage, sessionCount: sessionCounts.triaged || 0 },
    plan: { ...emptyStage, sessionCount: sessionCounts.planned || 0 },
    implement: { ...emptyStage, sessionCount: sessionCounts.implemented || 0 },
    review: { ...emptyStage, sessionCount: sessionCounts.reviewed || 0 },
    merged: { ...emptyStage, sessionCount: sessionCounts.merged || 0 },
    workload: { total: 0, active: 0, done: 0, failed: 0 },
  }
}

function defaultContext(overrides = {}) {
  return {
    metrics: null,
    lifetimeStats: null,
    githubMetrics: null,
    metricsHistory: null,
    stageStatus: mockStageStatusFromSession({}),
    ...overrides,
  }
}

beforeEach(() => {
  mockUseHydraFlow.mockReturnValue(defaultContext())
})

describe('MetricsPanel', () => {
  it('shows empty state message when no data at all', () => {
    render(<MetricsPanel />)
    expect(screen.getByText('No metrics data available yet.')).toBeInTheDocument()
  })

  it('renders lifetime stats from GitHub metrics', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      githubMetrics: {
        open_by_label: { 'hydraflow-plan': 2, 'hydraflow-ready': 1, 'hydraflow-review': 0, 'hydraflow-hitl': 0, 'hydraflow-fixed': 0 },
        total_closed: 10,
        total_merged: 8,
      },
    }))
    render(<MetricsPanel />)
    expect(screen.getByText('Lifetime')).toBeInTheDocument()
    expect(screen.getByText('10')).toBeInTheDocument()
    expect(screen.getByText('8')).toBeInTheDocument()
    expect(screen.getByText('Issues Completed')).toBeInTheDocument()
    expect(screen.getByText('PRs Merged')).toBeInTheDocument()
  })

  it('shows open issues count from GitHub metrics', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      githubMetrics: {
        open_by_label: { 'hydraflow-plan': 3, 'hydraflow-ready': 2, 'hydraflow-review': 1, 'hydraflow-hitl': 0, 'hydraflow-fixed': 0 },
        total_closed: 5,
        total_merged: 4,
      },
    }))
    render(<MetricsPanel />)
    expect(screen.getByText('Open Issues')).toBeInTheDocument()
    expect(screen.getByText('6')).toBeInTheDocument() // 3+2+1
  })

  it('renders session stats when session has activity', () => {
    const sessionCounts = { triaged: 3, planned: 2, implemented: 1, reviewed: 1, merged: 0 }
    mockUseHydraFlow.mockReturnValue(defaultContext({
      stageStatus: mockStageStatusFromSession(sessionCounts),
      githubMetrics: {
        open_by_label: {},
        total_closed: 0,
        total_merged: 0,
      },
    }))
    render(<MetricsPanel />)
    expect(screen.getByText('Session')).toBeInTheDocument()
    expect(screen.getByText('Triaged')).toBeInTheDocument()
    expect(screen.getByText('Planned')).toBeInTheDocument()
    expect(screen.getByText('Implemented')).toBeInTheDocument()
    expect(screen.getByText('Reviewed')).toBeInTheDocument()
    expect(screen.getByText('Merged')).toBeInTheDocument()
  })

  it('does not render session section when all session counts are zero', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      githubMetrics: {
        open_by_label: {},
        total_closed: 5,
        total_merged: 3,
      },
    }))
    render(<MetricsPanel />)
    expect(screen.queryByText('Session')).not.toBeInTheDocument()
  })

  it('does not render pipeline section (moved to StreamView)', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      githubMetrics: {
        open_by_label: { 'hydraflow-plan': 3, 'hydraflow-ready': 1, 'hydraflow-review': 2, 'hydraflow-hitl': 0, 'hydraflow-fixed': 0 },
        total_closed: 0,
        total_merged: 0,
      },
    }))
    render(<MetricsPanel />)
    expect(screen.queryByText('Pipeline')).not.toBeInTheDocument()
  })

  it('falls back to lifetimeStats when metrics and githubMetrics are null', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      lifetimeStats: { issues_completed: 5, prs_merged: 3, issues_created: 1 },
    }))
    render(<MetricsPanel />)
    expect(screen.getByText('5')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('falls back to metrics.lifetime when githubMetrics is null', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      metrics: {
        lifetime: { issues_completed: 10, prs_merged: 8, issues_created: 3 },
        rates: {},
      },
    }))
    render(<MetricsPanel />)
    expect(screen.getByText('10')).toBeInTheDocument()
    expect(screen.getByText('8')).toBeInTheDocument()
  })

  it('shows empty state when everything is null and session is empty', () => {
    render(<MetricsPanel />)
    expect(screen.getByText('No metrics data available yet.')).toBeInTheDocument()
  })

  it('renders rates section when metricsHistory has current snapshot', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      metricsHistory: {
        current: { merge_rate: 0.8, first_pass_approval_rate: 0.6, quality_fix_rate: 0.1, hitl_escalation_rate: 0.05, issues_completed: 10, prs_merged: 8 },
        snapshots: [],
      },
    }))
    render(<MetricsPanel />)
    expect(screen.getByText('Rates')).toBeInTheDocument()
    expect(screen.getByText('Merge Rate')).toBeInTheDocument()
    expect(screen.getByText('First-Pass Approval')).toBeInTheDocument()
  })
})
