import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts" />,
}))

import { DrillDownPane } from '../DrillDownPane'

describe('DrillDownPane', () => {
  it('renders subprocess hierarchy', () => {
    render(<DrillDownPane runData={{
      summary: { issue_number: 42, phase: 'implement', run_id: 1, tokens: { prompt_tokens: 1000 } },
      subprocesses: [
        { subprocess_idx: 0, backend: 'claude', tokens: { prompt_tokens: 500, completion_tokens: 200 }, tool_calls: [], skill_results: [] },
        { subprocess_idx: 1, backend: 'claude', tokens: { prompt_tokens: 500, completion_tokens: 100 }, tool_calls: [], skill_results: [] },
      ],
    }} onClose={() => {}} />)
    expect(screen.getByText(/subprocess-0/)).toBeInTheDocument()
    expect(screen.getByText(/subprocess-1/)).toBeInTheDocument()
  })

  it('renders empty when no run', () => {
    render(<DrillDownPane runData={null} onClose={() => {}} />)
    expect(screen.getByText(/Select a row/i)).toBeInTheDocument()
  })

  it('renders gantt without throwing when tool_call started_at is null', () => {
    render(<DrillDownPane runData={{
      summary: { issue_number: 42, phase: 'implement', run_id: 1 },
      subprocesses: [
        {
          subprocess_idx: 0,
          backend: 'claude',
          tokens: { prompt_tokens: 100 },
          tool_calls: [
            { started_at: null, duration_ms: 100, tool_name: 'Read', succeeded: true },
            { started_at: 'not-a-date', duration_ms: 50, tool_name: 'Bash', succeeded: true },
          ],
          skill_results: [],
        },
      ],
    }} onClose={() => {}} />)
    expect(screen.getByTestId('echarts')).toBeInTheDocument()
  })

  it('renders error state when runData.error is set', () => {
    render(<DrillDownPane runData={{ error: 'Failed to load run (500)' }} onClose={() => {}} />)
    expect(screen.getByText(/Failed to load run/i)).toBeInTheDocument()
  })
})
