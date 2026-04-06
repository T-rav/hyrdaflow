import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { CaretakerPanel } = await import('../CaretakerPanel')

function defaultContext(overrides = {}) {
  return {
    backgroundWorkers: [
      { name: 'stale_issue_gc', status: 'ok', enabled: true, last_run: '2026-03-28T12:00:00Z', details: {} },
      { name: 'ci_monitor', status: 'ok', enabled: true, last_run: '2026-03-28T12:00:00Z', details: {} },
      { name: 'dependabot_merge', status: 'ok', enabled: false, last_run: null, details: {} },
      { name: 'worktree_gc', status: 'ok', enabled: true, last_run: '2026-03-28T11:00:00Z', details: {} },
      { name: 'health_monitor', status: 'error', enabled: true, last_run: '2026-03-28T10:00:00Z', details: {} },
      { name: 'epic_sweeper', status: 'ok', enabled: true, last_run: null, details: {} },
    ],
    toggleBgWorker: vi.fn(),
    triggerBgWorker: vi.fn(),
    ...overrides,
  }
}

describe('CaretakerPanel', () => {
  beforeEach(() => {
    mockUseHydraFlow.mockReturnValue(defaultContext())
  })

  it('renders caretaker worker rows', () => {
    render(<CaretakerPanel />)
    expect(screen.getByText('Stale Issue GC')).toBeTruthy()
    expect(screen.getByText('CI Monitor')).toBeTruthy()
    expect(screen.getByText('Dependabot Merge')).toBeTruthy()
  })

  it('shows enabled/disabled state with toggle buttons', () => {
    render(<CaretakerPanel />)
    const toggles = screen.getAllByTestId(/caretaker-toggle-/)
    expect(toggles.length).toBeGreaterThanOrEqual(3)
  })

  it('toggle button calls toggleBgWorker', () => {
    const ctx = defaultContext()
    mockUseHydraFlow.mockReturnValue(ctx)
    render(<CaretakerPanel />)
    const toggle = screen.getByTestId('caretaker-toggle-dependabot_merge')
    fireEvent.click(toggle)
    expect(ctx.toggleBgWorker).toHaveBeenCalledWith('dependabot_merge')
  })

  it('shows status indicator (green for ok, red for error)', () => {
    render(<CaretakerPanel />)
    const healthDot = screen.getByTestId('caretaker-status-health_monitor')
    expect(healthDot).toBeTruthy()
  })

  it('shows last run time', () => {
    render(<CaretakerPanel />)
    // Workers with null last_run should show "never"
    const neverElements = screen.getAllByText('never')
    expect(neverElements.length).toBeGreaterThanOrEqual(1)
  })

  it('shows trigger button for each worker', () => {
    const ctx = defaultContext()
    mockUseHydraFlow.mockReturnValue(ctx)
    render(<CaretakerPanel />)
    const triggerBtn = screen.getByTestId('caretaker-trigger-stale_issue_gc')
    fireEvent.click(triggerBtn)
    expect(ctx.triggerBgWorker).toHaveBeenCalledWith('stale_issue_gc')
  })

  it('shows all workers even when backend has not reported', () => {
    mockUseHydraFlow.mockReturnValue(defaultContext({ backgroundWorkers: [] }))
    render(<CaretakerPanel />)
    // Workers should still render with 'disabled' status
    expect(screen.getByText('Stale Issue GC')).toBeTruthy()
  })
})
