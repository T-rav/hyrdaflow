import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { PerLoopCostTable } from '../PerLoopCostTable'

// Sanity-check render tests for the §4.11p2 Task 12 per-loop table.

describe('PerLoopCostTable', () => {
  const rows = [
    {
      loop: 'implementer',
      cost_usd: 3.1234,
      llm_calls: 42,
      ticks: 9,
      tick_cost_avg_usd: 0.3471,
      tick_cost_avg_usd_prev_period: 0.1,
      wall_clock_seconds: 600,
      sparkline_points: [0.1, 0.2, 0.35],
    },
    {
      loop: 'reviewer',
      cost_usd: 0.5,
      llm_calls: 5,
      ticks: 2,
      tick_cost_avg_usd: 0.25,
      tick_cost_avg_usd_prev_period: 0.3,
      wall_clock_seconds: 120,
      sparkline_points: [],
    },
  ]

  it('renders rows, column headers, and spike highlight', () => {
    render(<PerLoopCostTable rows={rows} />)
    // Column headers
    expect(screen.getByText(/Loop/i)).toBeInTheDocument()
    expect(screen.getByText(/Cost \(USD\)/i)).toBeInTheDocument()
    expect(screen.getByText(/LLM Calls/i)).toBeInTheDocument()
    expect(screen.getByText(/Avg \$\/Tick/i)).toBeInTheDocument()
    // Row loop names
    expect(screen.getByText('implementer')).toBeInTheDocument()
    expect(screen.getByText('reviewer')).toBeInTheDocument()
    // Spike: implementer cur 0.3471 vs prev 0.1 → >= 2x → flagged via data attr.
    const implementerRow = screen.getByText('implementer').closest('tr')
    expect(implementerRow).toHaveAttribute('data-spike', 'true')
    const reviewerRow = screen.getByText('reviewer').closest('tr')
    expect(reviewerRow).toHaveAttribute('data-spike', 'false')
    // Sparkline rendered for the row that has points.
    expect(screen.getByTestId('sparkline-implementer')).toBeInTheDocument()
  })

  it('renders empty state when no rows', () => {
    render(<PerLoopCostTable rows={[]} />)
    expect(screen.getByText(/No loop cost data in range/i)).toBeInTheDocument()
  })
})

describe('PerLoopCostTable model_breakdown expansion', () => {
  const rowsWithBreakdown = [
    {
      loop: 'implementer',
      cost_usd: 1.5,
      llm_calls: 10,
      ticks: 2,
      tick_cost_avg_usd: 0.75,
      tick_cost_avg_usd_prev_period: 0.5,
      wall_clock_seconds: 60,
      sparkline_points: [],
      model_breakdown: {
        'claude-opus-4-7': {
          cost_usd: 1.4,
          calls: 7,
          input_tokens: 50000,
          output_tokens: 5000,
          cache_read_tokens: 100000,
          cache_write_tokens: 0,
        },
        'claude-haiku-4-5-20251001': {
          cost_usd: 0.1,
          calls: 3,
          input_tokens: 20000,
          output_tokens: 1000,
          cache_read_tokens: 0,
          cache_write_tokens: 0,
        },
      },
    },
  ]

  it('does not show the model sub-table by default', () => {
    render(<PerLoopCostTable rows={rowsWithBreakdown} />)
    expect(screen.queryByText('claude-opus-4-7')).not.toBeInTheDocument()
  })

  it('shows the per-model sub-table when the loop cell is clicked', () => {
    render(<PerLoopCostTable rows={rowsWithBreakdown} />)
    fireEvent.click(screen.getByTestId('expand-toggle-implementer'))
    expect(screen.getByText('claude-opus-4-7')).toBeInTheDocument()
    expect(screen.getByText('claude-haiku-4-5-20251001')).toBeInTheDocument()
  })

  it('shows percent share of loop cost per model', () => {
    render(<PerLoopCostTable rows={rowsWithBreakdown} />)
    fireEvent.click(screen.getByTestId('expand-toggle-implementer'))
    // 1.4 / 1.5 ≈ 93.3%
    expect(screen.getByText(/93\.3%/)).toBeInTheDocument()
    // 0.1 / 1.5 ≈ 6.7%
    expect(screen.getByText(/6\.7%/)).toBeInTheDocument()
  })

  it('omits the expand control when model_breakdown is absent (backward compat)', () => {
    const legacyRow = { ...rowsWithBreakdown[0] }
    delete legacyRow.model_breakdown
    render(<PerLoopCostTable rows={[legacyRow]} />)
    expect(screen.queryByTestId('expand-toggle-implementer')).not.toBeInTheDocument()
  })

  it('expand toggle does not trigger onRowClick', () => {
    const onRowClick = vi.fn()
    render(<PerLoopCostTable rows={rowsWithBreakdown} onRowClick={onRowClick} />)
    fireEvent.click(screen.getByTestId('expand-toggle-implementer'))
    expect(onRowClick).not.toHaveBeenCalled()
  })
})
