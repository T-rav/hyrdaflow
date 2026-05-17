import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AtlasExplorer } from '../AtlasExplorer'

beforeEach(() => {
  global.fetch = vi.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ nodes: [], edges: [], contexts: [] }),
    }),
  )
  // P4 added deep-link URL state that survives between tests in jsdom.
  // Reset to a clean URL so each test starts with the default tab.
  window.history.replaceState({}, '', '/')
  // Saved-views localStorage state likewise survives — clear it.
  window.localStorage.removeItem('atlas-saved-views')
})

describe('AtlasExplorer', () => {
  it('renders four sub-tab buttons', () => {
    render(<AtlasExplorer />)
    expect(screen.getByRole('button', { name: /^domain$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^graph$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^articles$/i })).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /^maintenance$/i }),
    ).toBeInTheDocument()
  })

  it('switches to Graph view when its tab is clicked', async () => {
    render(<AtlasExplorer />)
    fireEvent.click(screen.getByRole('button', { name: /^graph$/i }))
    await waitFor(() =>
      expect(screen.getByTestId('atlas-graph-view')).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('atlas-domain-view')).not.toBeInTheDocument()
  })

  it('honours ?atlas_sub deep link on initial mount', async () => {
    window.history.replaceState({}, '', '/?atlas_sub=articles')
    render(<AtlasExplorer />)
    await waitFor(() =>
      expect(screen.getByTestId('atlas-articles-view')).toBeInTheDocument(),
    )
  })

  it('writes ?atlas_sub when the user changes sub-tab', async () => {
    render(<AtlasExplorer />)
    fireEvent.click(screen.getByRole('button', { name: /^graph$/i }))
    await waitFor(() =>
      expect(screen.getByTestId('atlas-graph-view')).toBeInTheDocument(),
    )
    expect(window.location.search).toContain('atlas_sub=graph')
  })

  it('renders the Focus mode toggle in the filter bar', () => {
    render(<AtlasExplorer />)
    expect(
      screen.getByRole('button', { name: /toggle focus mode/i }),
    ).toBeInTheDocument()
  })

  it('shows the Domain view by default', () => {
    render(<AtlasExplorer />)
    expect(screen.getByTestId('atlas-domain-view')).toBeInTheDocument()
    expect(screen.queryByTestId('atlas-articles-view')).not.toBeInTheDocument()
  })

  it('switches to Articles when its tab is clicked', async () => {
    render(<AtlasExplorer />)
    fireEvent.click(screen.getByRole('button', { name: /^articles$/i }))
    await waitFor(() =>
      expect(screen.getByTestId('atlas-articles-view')).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('atlas-domain-view')).not.toBeInTheDocument()
  })

  it('switches to Maintenance when its tab is clicked', async () => {
    render(<AtlasExplorer />)
    fireEvent.click(screen.getByRole('button', { name: /^maintenance$/i }))
    await waitFor(() =>
      expect(screen.getByTestId('atlas-maintenance-view')).toBeInTheDocument(),
    )
  })
})
