import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AdrDetailPanel } from '../AdrDetailPanel'

const ADR = {
  number: 60,
  title: 'Atlas graph view',
  status: 'Accepted',
  date: '2026-05-09',
  body: '# ADR-0060: Atlas\n\nDecision text.',
  related: [],
}

beforeEach(() => {
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(ADR) }),
  )
})

describe('AdrDetailPanel', () => {
  it('renders header + markdown body for an ADR id', async () => {
    render(<AdrDetailPanel selectedNodeId="adr-60" />)
    await waitFor(() => screen.getByText(/atlas graph view/i))
    expect(
      screen.getByText(/Accepted/),
    ).toBeInTheDocument()
    const heading = screen.getByRole('heading', { level: 1, name: /adr-0060/i })
    expect(heading.tagName).toBe('H1')
  })

  it('shows error when fetch fails', async () => {
    global.fetch = vi.fn(() => Promise.resolve({ ok: false, status: 500 }))
    render(<AdrDetailPanel selectedNodeId="adr-60" />)
    await waitFor(() => {
      expect(screen.getByText(/unable to load adr/i)).toBeInTheDocument()
    })
  })

  it('shows error for non-adr id', async () => {
    render(<AdrDetailPanel selectedNodeId="not-an-adr" />)
    await waitFor(() => {
      expect(screen.getByText(/unable to load adr/i)).toBeInTheDocument()
    })
  })
})
