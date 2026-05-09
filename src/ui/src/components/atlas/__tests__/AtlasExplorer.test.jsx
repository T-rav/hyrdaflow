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
