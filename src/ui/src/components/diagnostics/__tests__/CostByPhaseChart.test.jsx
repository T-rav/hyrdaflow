import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts" />,
}))

import { CostByPhaseChart } from '../CostByPhaseChart'

describe('CostByPhaseChart', () => {
  it('renders with phase data', () => {
    render(<CostByPhaseChart data={{ implement: 50000, plan: 12000, review: 8000 }} />)
    expect(screen.getByTestId('echarts')).toBeInTheDocument()
  })

  it('renders empty state', () => {
    render(<CostByPhaseChart data={{}} />)
    expect(screen.getByText(/No data/i)).toBeInTheDocument()
  })
})
