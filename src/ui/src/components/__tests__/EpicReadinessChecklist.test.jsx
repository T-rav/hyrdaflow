import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { EpicReadinessChecklist, deriveReadiness } from '../EpicReadinessChecklist'

const allReadyEpic = {
  epic_number: 100,
  total_children: 3,
  merged_children: 3,
  children: [],
  readiness: {
    all_implemented: true,
    all_approved: true,
    ci_passing: true,
    no_conflicts: true,
    changelog_generated: true,
    version_determined: true,
    approved_count: 3,
    total_count: 3,
    version: '1.2.0',
  },
}

const partialEpic = {
  epic_number: 101,
  total_children: 5,
  merged_children: 2,
  children: [],
  readiness: {
    all_implemented: false,
    all_approved: false,
    ci_passing: true,
    no_conflicts: false,
    changelog_generated: false,
    version_determined: false,
    approved_count: 1,
    total_count: 5,
  },
}

const noReadinessEpic = {
  epic_number: 102,
  total_children: 4,
  merged_children: 0,
  children: [],
}

describe('deriveReadiness', () => {
  it('returns all passed for a fully ready epic', () => {
    const checks = deriveReadiness(allReadyEpic)
    expect(checks).toHaveLength(6)
    expect(checks.every(c => c.passed)).toBe(true)
  })

  it('returns mixed results for partial epic', () => {
    const checks = deriveReadiness(partialEpic)
    const passed = checks.filter(c => c.passed)
    expect(passed).toHaveLength(1) // only ci_passing
  })

  it('returns all false for epic without readiness data', () => {
    const checks = deriveReadiness(noReadinessEpic)
    expect(checks.every(c => !c.passed)).toBe(true)
  })

  it('includes approved count detail', () => {
    const checks = deriveReadiness(partialEpic)
    const approved = checks.find(c => c.key === 'approved')
    expect(approved.detail).toBe('1/5')
  })

  it('includes version in version check detail', () => {
    const checks = deriveReadiness(allReadyEpic)
    const version = checks.find(c => c.key === 'version')
    expect(version.detail).toBe('1.2.0')
  })
})

describe('EpicReadinessChecklist', () => {
  it('renders checklist with data-testid', () => {
    render(<EpicReadinessChecklist epic={allReadyEpic} />)
    expect(screen.getByTestId('readiness-checklist')).toBeInTheDocument()
  })

  it('renders all six check items', () => {
    render(<EpicReadinessChecklist epic={allReadyEpic} />)
    expect(screen.getByTestId('check-implemented')).toBeInTheDocument()
    expect(screen.getByTestId('check-approved')).toBeInTheDocument()
    expect(screen.getByTestId('check-ci')).toBeInTheDocument()
    expect(screen.getByTestId('check-conflicts')).toBeInTheDocument()
    expect(screen.getByTestId('check-changelog')).toBeInTheDocument()
    expect(screen.getByTestId('check-version')).toBeInTheDocument()
  })

  it('shows Ready badge when all checks pass', () => {
    render(<EpicReadinessChecklist epic={allReadyEpic} />)
    expect(screen.getByText('Ready')).toBeInTheDocument()
  })

  it('does not show Ready badge when checks are incomplete', () => {
    render(<EpicReadinessChecklist epic={partialEpic} />)
    expect(screen.queryByText('Ready')).not.toBeInTheDocument()
  })

  it('renders checkmarks for passed checks', () => {
    render(<EpicReadinessChecklist epic={allReadyEpic} />)
    const checks = screen.getAllByText('✓')
    expect(checks.length).toBe(6)
  })

  it('renders circles for pending checks', () => {
    render(<EpicReadinessChecklist epic={noReadinessEpic} />)
    const circles = screen.getAllByText('○')
    expect(circles.length).toBe(6)
  })

  it('renders warning symbol for conflict check when no_conflicts is false', () => {
    render(<EpicReadinessChecklist epic={partialEpic} />)
    expect(screen.getByText('⚠')).toBeInTheDocument()
  })

  it('renders the header title', () => {
    render(<EpicReadinessChecklist epic={allReadyEpic} />)
    expect(screen.getByText('Release Readiness')).toBeInTheDocument()
  })

  it('renders count details', () => {
    render(<EpicReadinessChecklist epic={partialEpic} />)
    expect(screen.getByText('2/5')).toBeInTheDocument() // implemented
    expect(screen.getByText('1/5')).toBeInTheDocument() // approved
  })
})
