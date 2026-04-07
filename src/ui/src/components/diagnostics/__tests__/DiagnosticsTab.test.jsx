import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts" />,
}))

global.fetch = vi.fn((url) => {
  if (url.includes('/overview')) {
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        total_tokens: 247000, total_runs: 1, total_tool_invocations: 7, cache_hit_rate: 0.5,
      }),
    })
  }
  return Promise.resolve({ ok: true, json: () => Promise.resolve([]) })
})

import { DiagnosticsTab } from '../DiagnosticsTab'

describe('DiagnosticsTab', () => {
  it('fetches and renders overview', async () => {
    render(<DiagnosticsTab />)
    await waitFor(() => {
      expect(screen.getByText(/247K/)).toBeInTheDocument()
    })
  })

  it('renders range filter dropdown', async () => {
    render(<DiagnosticsTab />)
    expect(await screen.findByLabelText(/Range/i)).toBeInTheDocument()
  })
})
