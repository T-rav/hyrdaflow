import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { IssueTable } from '../IssueTable'

describe('IssueTable', () => {
  const sample = [
    { issue: 42, phase: 'implement', run_id: 1, tokens: 1700, duration_seconds: 120, tool_count: 7, skill_pass_count: 1, skill_total: 1, crashed: false },
    { issue: 99, phase: 'plan', run_id: 1, tokens: 800, duration_seconds: 30, tool_count: 3, skill_pass_count: 0, skill_total: 0, crashed: false },
  ]

  it('renders rows', () => {
    render(<IssueTable rows={sample} onRowClick={() => {}} />)
    expect(screen.getByText('42')).toBeInTheDocument()
    expect(screen.getByText('99')).toBeInTheDocument()
  })

  it('calls onRowClick when row is clicked', () => {
    const onClick = vi.fn()
    render(<IssueTable rows={sample} onRowClick={onClick} />)
    fireEvent.click(screen.getByText('42'))
    expect(onClick).toHaveBeenCalledWith(expect.objectContaining({ issue: 42 }))
  })

  it('handles empty state', () => {
    render(<IssueTable rows={[]} onRowClick={() => {}} />)
    expect(screen.getByText(/No data/i)).toBeInTheDocument()
  })
})
