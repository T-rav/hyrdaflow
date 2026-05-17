import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ArticlesView } from '../ArticlesView'

const ADRS = [
  {
    number: 59,
    title: 'Atlas knowledge graph dashboard',
    status: 'Accepted',
    date: '2026-05-08',
  },
]
const ADR_DETAIL = {
  number: 59,
  title: 'Atlas knowledge graph dashboard',
  status: 'Accepted',
  date: '2026-05-08',
  body: '# ADR-0059: Atlas\n\nDecision body content.',
  related: [],
}
const REPOS = [{ owner: 'acme', repo: 'widget' }]
const ENTRIES = [
  {
    id: '0001',
    issue: '10',
    topic: 'patterns',
    owner: 'acme',
    repo: 'widget',
    filename: '0001-issue-10-first-pattern.md',
    status: 'active',
    source_phase: 'plan',
    source_issue: '10',
    created_at: '2026-04-01T00:00:00Z',
  },
]
const ENTRY_DETAIL = {
  id: '0001',
  topic: 'patterns',
  owner: 'acme',
  repo: 'widget',
  filename: '0001-issue-10-first-pattern.md',
  frontmatter: { status: 'active' },
  body: '# First pattern\n\nPattern body content.',
}

beforeEach(() => {
  global.fetch = vi.fn((url) => {
    if (url === '/api/atlas/adrs')
      return Promise.resolve({ ok: true, json: () => Promise.resolve(ADRS) })
    if (url.startsWith('/api/atlas/adrs/'))
      return Promise.resolve({ ok: true, json: () => Promise.resolve(ADR_DETAIL) })
    if (url === '/api/wiki/repos')
      return Promise.resolve({ ok: true, json: () => Promise.resolve(REPOS) })
    if (url.includes('/entries/0001'))
      return Promise.resolve({ ok: true, json: () => Promise.resolve(ENTRY_DETAIL) })
    if (url.includes('/entries'))
      return Promise.resolve({ ok: true, json: () => Promise.resolve(ENTRIES) })
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
  })
})

describe('ArticlesView', () => {
  it('renders both ADR rows and wiki entry rows in the unified list', async () => {
    render(<ArticlesView />)
    await waitFor(() => {
      expect(screen.getByText(/atlas knowledge graph/i)).toBeInTheDocument()
      expect(
        screen.getByText('0001-issue-10-first-pattern.md'),
      ).toBeInTheDocument()
    })
  })

  it('shows ADR and WIKI type chips on rows', async () => {
    render(<ArticlesView />)
    await waitFor(() => screen.getByText(/atlas knowledge graph/i))
    await waitFor(() =>
      screen.getByText('0001-issue-10-first-pattern.md'),
    )
    expect(screen.getAllByText('ADR').length).toBeGreaterThan(0)
    expect(screen.getAllByText('WIKI').length).toBeGreaterThan(0)
  })

  it('hides wiki rows when type filter is set to ADRs only', async () => {
    render(<ArticlesView />)
    await waitFor(() =>
      screen.getByText('0001-issue-10-first-pattern.md'),
    )
    fireEvent.change(screen.getByLabelText(/^type$/i), {
      target: { value: 'adrs' },
    })
    expect(
      screen.queryByText('0001-issue-10-first-pattern.md'),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/atlas knowledge graph/i)).toBeInTheDocument()
  })

  it('renders selected ADR markdown body when an ADR row is clicked', async () => {
    render(<ArticlesView />)
    await waitFor(() => screen.getByText(/atlas knowledge graph/i))
    fireEvent.click(screen.getByText(/atlas knowledge graph/i))
    await waitFor(() => {
      const heading = screen.getByRole('heading', { level: 1, name: /adr-0059/i })
      expect(heading.tagName).toBe('H1')
    })
  })

  it('renders selected wiki entry markdown body when a wiki row is clicked', async () => {
    render(<ArticlesView />)
    await waitFor(() => screen.getByText('0001-issue-10-first-pattern.md'))
    fireEvent.click(screen.getByText('0001-issue-10-first-pattern.md'))
    await waitFor(() => {
      const heading = screen.getByRole('heading', { name: /first pattern/i })
      expect(heading.tagName).toBe('H1')
    })
  })

  it('renders the Linked-to-term filter dropdown when wiki entries are in scope', async () => {
    render(<ArticlesView />)
    await waitFor(() =>
      expect(screen.getByLabelText(/linked to term/i)).toBeInTheDocument(),
    )
    const select = screen.getByLabelText(/linked to term/i)
    expect(select.tagName).toBe('SELECT')
    // All three options must be available.
    expect(
      screen.getByRole('option', { name: /linked to a term/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('option', { name: /discovered \(orphan\)/i }),
    ).toBeInTheDocument()
  })

  it('hides the Linked filter when type is set to ADRs only', async () => {
    render(<ArticlesView />)
    await waitFor(() =>
      expect(screen.getByLabelText(/linked to term/i)).toBeInTheDocument(),
    )
    fireEvent.change(screen.getByLabelText(/^type$/i), {
      target: { value: 'adrs' },
    })
    // The whole wiki bar (including the link filter) is gated on ADRs/wiki/all.
    expect(
      screen.queryByLabelText(/linked to term/i),
    ).not.toBeInTheDocument()
  })
})
