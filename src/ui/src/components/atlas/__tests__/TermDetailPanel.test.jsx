import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { TermDetailPanel } from '../TermDetailPanel'

const SAMPLE_TERM = {
  id: 'n1',
  name: 'AgentRunner',
  kind: 'runner',
  bounded_context: 'builder',
  code_anchor: 'src/agent.py:AgentRunner',
  confidence: 'accepted',
  definition: 'Subprocess runner for the implement phase.',
  invariants: ['Phase name is fixed.', 'Commits but never pushes.'],
  aliases: ['agent runner', 'implement runner'],
  edges: [{ kind: 'depends_on', target_id: 'n2', target_name: 'EventBus' }],
  evidence: [],
  superseded_by: null,
  superseded_reason: null,
}

beforeEach(() => {
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(SAMPLE_TERM) }),
  )
})

describe('TermDetailPanel', () => {
  it('shows a hint when no term is selected', () => {
    render(<TermDetailPanel selectedNodeId={null} />)
    expect(screen.getByText(/pick a node/i)).toBeInTheDocument()
  })

  it('renders the selected term details after fetch', async () => {
    render(<TermDetailPanel selectedNodeId="n1" />)
    await waitFor(() => screen.getByText('AgentRunner'))
    expect(
      screen.getByText('Subprocess runner for the implement phase.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Phase name is fixed.')).toBeInTheDocument()
  })

  it('renders edge rows with target name and edge kind', async () => {
    render(<TermDetailPanel selectedNodeId="n1" />)
    await waitFor(() => screen.getByText('AgentRunner'))
    expect(screen.getByText(/→depends_on/)).toBeInTheDocument()
    expect(screen.getByText('EventBus')).toBeInTheDocument()
  })

  it('renders aliases as chips', async () => {
    render(<TermDetailPanel selectedNodeId="n1" />)
    await waitFor(() => screen.getByText('AgentRunner'))
    expect(screen.getByText('agent runner')).toBeInTheDocument()
    expect(screen.getByText('implement runner')).toBeInTheDocument()
  })

  it('shows an error when the fetch fails', async () => {
    global.fetch = vi.fn(() => Promise.resolve({ ok: false, status: 500 }))
    render(<TermDetailPanel selectedNodeId="n1" />)
    await waitFor(() => {
      expect(screen.getByText(/unable to load term/i)).toBeInTheDocument()
    })
  })
})
