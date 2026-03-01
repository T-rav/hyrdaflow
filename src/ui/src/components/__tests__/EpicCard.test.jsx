import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { EpicCard } from '../EpicCard'

const baseEpic = {
  epic_number: 100,
  title: 'Epic: Build dashboard',
  url: 'https://github.com/org/repo/issues/100',
  status: 'active',
  merge_strategy: 'independent',
  created_at: '2026-01-15T10:00:00Z',
  total_children: 5,
  merged_children: 2,
  active_children: 1,
  queued_children: 2,
  children: [
    { issue_number: 101, title: 'Sub A', url: '#', current_stage: 'merged', status: 'done', stage_entered_at: null },
    { issue_number: 102, title: 'Sub B', url: '#', current_stage: 'merged', status: 'done', stage_entered_at: null },
    { issue_number: 103, title: 'Sub C', url: '#', current_stage: 'implement', status: 'running', stage_entered_at: new Date().toISOString() },
    { issue_number: 104, title: 'Sub D', url: '#', current_stage: 'triage', status: 'queued', stage_entered_at: null },
    { issue_number: 105, title: 'Sub E', url: '#', current_stage: 'triage', status: 'queued', stage_entered_at: null },
  ],
}

describe('EpicCard', () => {
  it('renders the epic number and title', () => {
    render(<EpicCard epic={baseEpic} />)
    expect(screen.getByText('#100')).toBeInTheDocument()
    expect(screen.getByText('Epic: Build dashboard')).toBeInTheDocument()
  })

  it('renders the strategy badge', () => {
    render(<EpicCard epic={baseEpic} />)
    expect(screen.getByText('Independent')).toBeInTheDocument()
  })

  it('renders progress counts', () => {
    render(<EpicCard epic={baseEpic} />)
    expect(screen.getByText(/2 merged/)).toBeInTheDocument()
    expect(screen.getByText(/1 active/)).toBeInTheDocument()
    expect(screen.getByText(/2 queued/)).toBeInTheDocument()
  })

  it('renders percentage label', () => {
    render(<EpicCard epic={baseEpic} />)
    expect(screen.getByText('40%')).toBeInTheDocument()
  })

  it('renders progress bar with correct width', () => {
    render(<EpicCard epic={baseEpic} />)
    const bar = screen.getByTestId('progress-bar-100')
    expect(bar.style.width).toBe('40%')
  })

  it('renders created date', () => {
    render(<EpicCard epic={baseEpic} />)
    expect(screen.getByText(/Created/)).toBeInTheDocument()
  })

  it('is collapsed by default — no swimlane visible', () => {
    render(<EpicCard epic={baseEpic} />)
    expect(screen.queryByTestId('epic-swimlane')).not.toBeInTheDocument()
  })

  it('expands to show swimlane on click', () => {
    render(<EpicCard epic={baseEpic} />)
    // Click the header to expand
    fireEvent.click(screen.getByText('Epic: Build dashboard'))
    expect(screen.getByTestId('epic-swimlane')).toBeInTheDocument()
    expect(screen.getByTestId('swimlane-row-101')).toBeInTheDocument()
  })

  it('collapses swimlane on second click', () => {
    render(<EpicCard epic={baseEpic} />)
    fireEvent.click(screen.getByText('Epic: Build dashboard'))
    expect(screen.getByTestId('epic-swimlane')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Epic: Build dashboard'))
    expect(screen.queryByTestId('epic-swimlane')).not.toBeInTheDocument()
  })

  it('renders bundled strategy badge', () => {
    const epic = { ...baseEpic, merge_strategy: 'bundled' }
    render(<EpicCard epic={epic} />)
    expect(screen.getByText('Bundled')).toBeInTheDocument()
  })

  it('renders bundled_hitl strategy badge', () => {
    const epic = { ...baseEpic, merge_strategy: 'bundled_hitl' }
    render(<EpicCard epic={epic} />)
    expect(screen.getByText('Bundled HITL')).toBeInTheDocument()
  })

  it('renders ordered strategy badge', () => {
    const epic = { ...baseEpic, merge_strategy: 'ordered' }
    render(<EpicCard epic={epic} />)
    expect(screen.getByText('Ordered')).toBeInTheDocument()
  })

  it('handles epic with no children gracefully', () => {
    const epic = { ...baseEpic, total_children: 0, merged_children: 0, active_children: 0, children: [] }
    render(<EpicCard epic={epic} />)
    expect(screen.getByText('0%')).toBeInTheDocument()
  })

  it('shows 100% when all children are merged', () => {
    const epic = { ...baseEpic, total_children: 3, merged_children: 3, active_children: 0 }
    render(<EpicCard epic={epic} />)
    expect(screen.getByText('100%')).toBeInTheDocument()
  })

  it('expands via keyboard Enter key', () => {
    render(<EpicCard epic={baseEpic} />)
    const header = screen.getByText('Epic: Build dashboard').closest('[role="button"]')
    fireEvent.keyDown(header, { key: 'Enter' })
    expect(screen.getByTestId('epic-swimlane')).toBeInTheDocument()
  })

  it('renders the data-testid on the card', () => {
    render(<EpicCard epic={baseEpic} />)
    expect(screen.getByTestId('epic-card-100')).toBeInTheDocument()
  })
})
