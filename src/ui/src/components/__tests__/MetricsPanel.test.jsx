import React from 'react'
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

  it('prefers local lifetime when github metrics are all zeros', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      metrics: {
        lifetime: { issues_completed: 12, prs_merged: 9, issues_created: 3 },
        rates: {},
      },
      githubMetrics: {
        open_by_label: {},
        total_closed: 0,
        total_merged: 0,
      },
    }))
    render(<MetricsPanel />)
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.getByText('9')).toBeInTheDocument()
    expect(screen.queryByText('Open Issues')).not.toBeInTheDocument()
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

  it('does not render Snapshot History even when snapshots exist', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      metricsHistory: {
        current: {
          merge_rate: 0.5,
          first_pass_approval_rate: 0.5,
          quality_fix_rate: 0.2,
          hitl_escalation_rate: 0.1,
          issues_completed: 5,
          prs_merged: 4,
        },
        snapshots: [
          {
            issues_completed: 4,
            prs_merged: 3,
          },
        ],
      },
    }))
    render(<MetricsPanel />)
    expect(screen.queryByText('Snapshot History')).not.toBeInTheDocument()
  })

  it('renders trend indicators when previous snapshot data exists', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      metricsHistory: {
        current: {
          merge_rate: 0.8,
          first_pass_approval_rate: 0.7,
          quality_fix_rate: 0.1,
          hitl_escalation_rate: 0.05,
          issues_completed: 10,
          prs_merged: 8,
        },
        snapshots: [
          {
            merge_rate: 0.6,
            first_pass_approval_rate: 0.5,
            quality_fix_rate: 0.2,
            hitl_escalation_rate: 0.1,
            issues_completed: 8,
            prs_merged: 6,
          },
        ],
      },
    }))
    render(<MetricsPanel />)
    // TrendIndicators should render delta arrows since current > previous
    // e.g. issues_completed: 10 - 8 = 2 → renders "↑ 2"
    const upArrows = screen.getAllByText(/↑/)
    expect(upArrows.length).toBeGreaterThan(0)
  })

  it('renders inference lifetime and session totals when provided', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      metrics: {
        lifetime: { issues_completed: 1, prs_merged: 1, issues_created: 1 },
        rates: {},
        inference_lifetime: { total_tokens: 1234, inference_calls: 12, pruned_chars_total: 8000 },
        inference_session: { total_tokens: 234, inference_calls: 3, pruned_chars_total: 400 },
      },
    }))
    render(<MetricsPanel />)
    expect(screen.getByText('Inference')).toBeInTheDocument()
    expect(screen.getByText('Session Tokens')).toBeInTheDocument()
    expect(screen.getByText('Lifetime Tokens')).toBeInTheDocument()
    expect(screen.getByText('Session Pruned Chars')).toBeInTheDocument()
    expect(screen.getByText('Lifetime Pruned Chars')).toBeInTheDocument()
    expect(screen.getByText('1,234')).toBeInTheDocument()
    expect(screen.getByText('234')).toBeInTheDocument()
    expect(screen.getByText('8,000')).toBeInTheDocument()
    expect(screen.getByText('400')).toBeInTheDocument()
  })

  it('uses metrics-grid layout wrappers with data test ids', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({
      githubMetrics: {
        open_by_label: { ready: 1 },
        total_closed: 2,
        total_merged: 1,
      },
      metricsHistory: {
        current: {
          merge_rate: 0.8,
          first_pass_approval_rate: 0.7,
          quality_fix_rate: 0.2,
          hitl_escalation_rate: 0.1,
          issues_completed: 4,
          prs_merged: 3,
        },
        snapshots: [{
          merge_rate: 0.7,
          first_pass_approval_rate: 0.6,
          quality_fix_rate: 0.1,
          hitl_escalation_rate: 0.05,
          issues_completed: 3,
          prs_merged: 2,
        }],
      },
      stageStatus: mockStageStatusFromSession({
        triaged: 1,
        planned: 1,
        implemented: 1,
        reviewed: 1,
        merged: 1,
      }),
      metrics: {
        lifetime: { issues_completed: 2, prs_merged: 1 },
        inference_lifetime: { total_tokens: 100, inference_calls: 2, pruned_chars_total: 3 },
        inference_session: { total_tokens: 10, inference_calls: 1, pruned_chars_total: 1 },
        time_to_merge: { avg: 50, p50: 40, p90: 65 },
      },
    }))

    render(<MetricsPanel />)

    const sectionWrapper = screen.getByTestId('metrics-sections')
    expect(sectionWrapper.className).toContain('metrics-sections')

    const lifetimeGrid = screen.getByTestId('metrics-grid-lifetime')
    const ratesGrid = screen.getByTestId('metrics-grid-rates')
    const sessionGrid = screen.getByTestId('metrics-grid-session')
    const inferenceGrid = screen.getByTestId('metrics-grid-inference')
    const mergeTimeGrid = screen.getByTestId('metrics-grid-time-to-merge')

    expect(lifetimeGrid.className).toContain('metrics-grid')
    expect(ratesGrid.className).toContain('metrics-grid')
    expect(sessionGrid.className).toContain('metrics-grid')
    expect(inferenceGrid.className).toContain('metrics-grid')
    expect(mergeTimeGrid.className).toContain('metrics-grid')

    const sectionCards = sectionWrapper.getElementsByClassName('metrics-section-card')
    expect(sectionCards.length).toBeGreaterThanOrEqual(5)
    expect(sectionWrapper.querySelector('.metrics-section-card--full')).not.toBeNull()
  })
})
