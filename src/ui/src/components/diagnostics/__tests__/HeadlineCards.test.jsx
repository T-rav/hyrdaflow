import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { HeadlineCards } from '../HeadlineCards'

describe('HeadlineCards', () => {
  it('renders three KPI cards', () => {
    render(<HeadlineCards data={{
      total_tokens: 247000,
      total_runs: 18,
      total_tool_invocations: 240,
      cache_hit_rate: 0.78,
    }} />)
    expect(screen.getByText(/247K/)).toBeInTheDocument()
    expect(screen.getByText(/18/)).toBeInTheDocument()
    expect(screen.getByText(/78%/)).toBeInTheDocument()
  })

  it('handles loading state', () => {
    render(<HeadlineCards data={null} loading={true} />)
    expect(screen.getByText(/Loading/i)).toBeInTheDocument()
  })

  it('handles empty state', () => {
    render(<HeadlineCards data={{
      total_tokens: 0, total_runs: 0,
      total_tool_invocations: 0, cache_hit_rate: 0,
    }} />)
    expect(screen.getAllByText(/0/).length).toBeGreaterThan(0)
  })
})
