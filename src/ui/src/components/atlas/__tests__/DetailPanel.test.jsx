import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { DetailPanel } from '../DetailPanel'

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    if (url.startsWith('/api/atlas/adrs/')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            number: 60,
            title: 'X',
            status: 'Accepted',
            date: '2026-05-09',
            body: '# X\n\nbody',
            related: [],
          }),
      })
    }
    if (url.startsWith('/api/atlas/terms/')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            id: 'n1',
            name: 'AgentRunner',
            kind: 'runner',
            bounded_context: 'builder',
            code_anchor: 'src/agent.py:AgentRunner',
            confidence: 'accepted',
            definition: 'A runner.',
            invariants: [],
            aliases: [],
            edges: [],
            evidence: [],
            superseded_by: null,
            superseded_reason: null,
            proposed_by: null,
            proposed_at: null,
            proposal_signals: null,
            proposal_imports_seen: null,
          }),
      })
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
  })
})

describe('DetailPanel', () => {
  it('shows hint when no node selected', () => {
    render(<DetailPanel selectedNodeId={null} />)
    expect(screen.getByText(/pick a node/i)).toBeInTheDocument()
  })

  it('routes adr-N ids to AdrDetailPanel', async () => {
    render(<DetailPanel selectedNodeId="adr-60" />)
    await waitFor(() => screen.getByText(/selected adr/i))
  })

  it('routes other ids to TermDetailPanel', async () => {
    render(<DetailPanel selectedNodeId="some-term-id" />)
    await waitFor(() => screen.getByText(/selected term/i))
  })
})
