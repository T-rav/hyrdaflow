import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { CostByModelChart } from '../CostByModelChart'

describe('CostByModelChart', () => {
  const rows = [
    {
      model: 'claude-opus-4-7',
      cost_usd: 12.5,
      calls: 100,
      input_tokens: 800_000,
      output_tokens: 50_000,
      cache_read_tokens: 1_500_000,
      cache_write_tokens: 10_000,
    },
    {
      model: 'claude-sonnet-4-6',
      cost_usd: 2.5,
      calls: 60,
      input_tokens: 400_000,
      output_tokens: 30_000,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
    },
    {
      model: 'claude-haiku-4-5-20251001',
      cost_usd: 0.5,
      calls: 200,
      input_tokens: 1_000_000,
      output_tokens: 80_000,
      cache_read_tokens: 0,
      cache_write_tokens: 0,
    },
  ]

  it('renders a segment per model', () => {
    render(<CostByModelChart rows={rows} />)
    expect(screen.getByTestId('seg-claude-opus-4-7')).toBeInTheDocument()
    expect(screen.getByTestId('seg-claude-sonnet-4-6')).toBeInTheDocument()
    expect(screen.getByTestId('seg-claude-haiku-4-5-20251001')).toBeInTheDocument()
  })

  it('defaults unit to dollars', () => {
    render(<CostByModelChart rows={rows} />)
    expect(screen.getByTestId('cost-by-model-unit')).toHaveTextContent('$')
  })

  it('switches units when a unit button is clicked', () => {
    render(<CostByModelChart rows={rows} />)
    fireEvent.click(screen.getByRole('button', { name: 'Calls' }))
    expect(screen.getByTestId('cost-by-model-unit')).toHaveTextContent('Calls')
    fireEvent.click(screen.getByRole('button', { name: 'Input tokens' }))
    expect(screen.getByTestId('cost-by-model-unit')).toHaveTextContent('Input tokens')
  })

  it('renders empty placeholder when no rows', () => {
    render(<CostByModelChart rows={[]} />)
    expect(screen.getByText(/no model spend data/i)).toBeInTheDocument()
  })

  it('renders empty placeholder when rows is null', () => {
    render(<CostByModelChart rows={null} />)
    expect(screen.getByText(/no model spend data/i)).toBeInTheDocument()
  })
})
