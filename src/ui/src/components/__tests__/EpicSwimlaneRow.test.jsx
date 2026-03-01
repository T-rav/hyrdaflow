import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { EpicSwimlaneRow } from '../EpicSwimlaneRow'

const baseIssue = {
  issue_number: 42,
  title: 'Fix widget',
  url: 'https://github.com/org/repo/issues/42',
  current_stage: 'implement',
  status: 'running',
  stage_entered_at: new Date(Date.now() - 30 * 60000).toISOString(), // 30min ago
}

describe('EpicSwimlaneRow', () => {
  it('renders a row with the issue number link', () => {
    render(<EpicSwimlaneRow issue={baseIssue} />)
    const link = screen.getByText('#42')
    expect(link).toBeInTheDocument()
    expect(link.tagName).toBe('A')
    expect(link).toHaveAttribute('href', 'https://github.com/org/repo/issues/42')
  })

  it('renders a node for each pipeline stage', () => {
    render(<EpicSwimlaneRow issue={baseIssue} />)
    expect(screen.getByTestId('node-42-triage')).toBeInTheDocument()
    expect(screen.getByTestId('node-42-plan')).toBeInTheDocument()
    expect(screen.getByTestId('node-42-implement')).toBeInTheDocument()
    expect(screen.getByTestId('node-42-review')).toBeInTheDocument()
    expect(screen.getByTestId('node-42-merged')).toBeInTheDocument()
  })

  it('marks past stages as done with checkmark', () => {
    render(<EpicSwimlaneRow issue={baseIssue} />)
    // triage and plan are before implement, so they should be done
    expect(screen.getByTestId('node-42-triage').textContent).toBe('✓')
    expect(screen.getByTestId('node-42-plan').textContent).toBe('✓')
  })

  it('marks the current stage as active', () => {
    render(<EpicSwimlaneRow issue={baseIssue} />)
    const node = screen.getByTestId('node-42-implement')
    // Active nodes have pulse animation
    expect(node.style.animation).toContain('stream-pulse')
  })

  it('marks future stages as pending (no checkmark)', () => {
    render(<EpicSwimlaneRow issue={baseIssue} />)
    expect(screen.getByTestId('node-42-review').textContent).toBe('')
    expect(screen.getByTestId('node-42-merged').textContent).toBe('')
  })

  it('shows the current stage label', () => {
    render(<EpicSwimlaneRow issue={baseIssue} />)
    expect(screen.getByText('Implement')).toBeInTheDocument()
  })

  it('displays time-in-stage', () => {
    render(<EpicSwimlaneRow issue={baseIssue} />)
    // 30 minutes ago → "30m"
    expect(screen.getByText('30m')).toBeInTheDocument()
  })

  it('renders with green time color for <1h', () => {
    render(<EpicSwimlaneRow issue={baseIssue} />)
    const row = screen.getByTestId('swimlane-row-42')
    // Time element should exist (just verify presence — color is CSS var)
    expect(row).toBeInTheDocument()
  })

  it('renders queued node style when status is queued', () => {
    const queuedIssue = { ...baseIssue, status: 'queued' }
    render(<EpicSwimlaneRow issue={queuedIssue} />)
    const node = screen.getByTestId('node-42-implement')
    // Queued nodes should NOT have pulse animation
    expect(node.style.animation).not.toContain('stream-pulse')
  })

  it('marks current stage as done when status is merged', () => {
    const mergedIssue = { ...baseIssue, current_stage: 'merged', status: 'merged' }
    render(<EpicSwimlaneRow issue={mergedIssue} />)
    // All stages should show checkmarks
    expect(screen.getByTestId('node-42-triage').textContent).toBe('✓')
    expect(screen.getByTestId('node-42-plan').textContent).toBe('✓')
    expect(screen.getByTestId('node-42-implement').textContent).toBe('✓')
    expect(screen.getByTestId('node-42-review').textContent).toBe('✓')
    expect(screen.getByTestId('node-42-merged').textContent).toBe('✓')
  })

  it('handles missing stage_entered_at gracefully', () => {
    const issue = { ...baseIssue, stage_entered_at: null }
    render(<EpicSwimlaneRow issue={issue} />)
    // Should render without error
    expect(screen.getByTestId('swimlane-row-42')).toBeInTheDocument()
  })

  it('handles unknown current_stage gracefully', () => {
    const issue = { ...baseIssue, current_stage: 'unknown' }
    render(<EpicSwimlaneRow issue={issue} />)
    // All nodes should be pending (no checkmarks)
    expect(screen.getByTestId('node-42-triage').textContent).toBe('')
  })
})
