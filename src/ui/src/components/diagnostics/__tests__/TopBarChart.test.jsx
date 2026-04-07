import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('echarts-for-react', () => ({
  default: ({ option }) => (
    <div data-testid="echarts" data-option={JSON.stringify(option)} />
  ),
}))

import { TopBarChart } from '../TopBarChart'

describe('TopBarChart', () => {
  it('renders with tool data', () => {
    render(<TopBarChart title="Top Tools" data={[
      { name: 'Read', count: 12 },
      { name: 'Bash', count: 5 },
    ]} valueKey="count" />)
    expect(screen.getByTestId('echarts')).toBeInTheDocument()
  })

  it('renders empty state', () => {
    render(<TopBarChart title="Top Tools" data={[]} valueKey="count" />)
    expect(screen.getByText(/No data/i)).toBeInTheDocument()
  })
})
