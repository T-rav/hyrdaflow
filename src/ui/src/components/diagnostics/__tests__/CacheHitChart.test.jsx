import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts" />,
}))

import { CacheHitChart } from '../CacheHitChart'

describe('CacheHitChart', () => {
  it('renders with time-series data', () => {
    render(<CacheHitChart data={[
      { timestamp: '2026-04-06T10:00:00Z', cache_hit_rate: 0.5 },
      { timestamp: '2026-04-06T11:00:00Z', cache_hit_rate: 0.78 },
    ]} />)
    expect(screen.getByTestId('echarts')).toBeInTheDocument()
  })

  it('renders empty state', () => {
    render(<CacheHitChart data={[]} />)
    expect(screen.getByText(/No data/i)).toBeInTheDocument()
  })
})
