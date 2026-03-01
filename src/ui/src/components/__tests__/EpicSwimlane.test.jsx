import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { EpicSwimlane } from '../EpicSwimlane'

const mockChildren = [
  {
    issue_number: 10,
    title: 'Sub-issue A',
    url: 'https://github.com/org/repo/issues/10',
    current_stage: 'implement',
    status: 'running',
    stage_entered_at: new Date().toISOString(),
  },
  {
    issue_number: 11,
    title: 'Sub-issue B',
    url: 'https://github.com/org/repo/issues/11',
    current_stage: 'review',
    status: 'queued',
    stage_entered_at: new Date().toISOString(),
  },
]

describe('EpicSwimlane', () => {
  it('renders the swimlane container', () => {
    render(<EpicSwimlane issues={mockChildren} />)
    expect(screen.getByTestId('epic-swimlane')).toBeInTheDocument()
  })

  it('renders a row for each sub-issue', () => {
    render(<EpicSwimlane issues={mockChildren} />)
    expect(screen.getByTestId('swimlane-row-10')).toBeInTheDocument()
    expect(screen.getByTestId('swimlane-row-11')).toBeInTheDocument()
  })

  it('renders stage header labels', () => {
    render(<EpicSwimlane issues={mockChildren} />)
    // Stage names appear in both header and row labels; use getAllByText to verify presence
    expect(screen.getAllByText('Triage').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Plan').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Implement').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Review').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Merged').length).toBeGreaterThanOrEqual(1)
  })

  it('renders Stage and Time column headers', () => {
    render(<EpicSwimlane issues={mockChildren} />)
    expect(screen.getByText('Stage')).toBeInTheDocument()
    expect(screen.getByText('Time')).toBeInTheDocument()
  })

  it('shows empty state when issues is empty', () => {
    render(<EpicSwimlane issues={[]} />)
    expect(screen.getByTestId('swimlane-empty')).toBeInTheDocument()
    expect(screen.getByText('No sub-issues')).toBeInTheDocument()
  })

  it('shows empty state when issues is null', () => {
    render(<EpicSwimlane issues={null} />)
    expect(screen.getByTestId('swimlane-empty')).toBeInTheDocument()
  })
})
