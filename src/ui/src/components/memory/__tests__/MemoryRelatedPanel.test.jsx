import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRelatedPanel } from '../MemoryRelatedPanel'

beforeEach(() => {
  global.fetch = vi.fn()
})
afterEach(() => {
  vi.restoreAllMocks()
})

function mockFetchJson(payload) {
  global.fetch.mockResolvedValue({
    ok: true,
    json: async () => payload,
  })
}

describe('MemoryRelatedPanel', () => {
  it('renders nothing when entity is null', () => {
    const { container } = render(<MemoryRelatedPanel entity={null} onClose={() => {}} />)
    expect(container.firstChild).toBeNull()
  })

  it('fetches /api/memory/issue/1234 when issue entity is focused', async () => {
    mockFetchJson({
      query: 'issue #1234',
      items: [
        { bank: 'hydraflow-tribal', content: 'Known fix', relevance_score: 0.9 },
      ],
    })
    render(
      <MemoryRelatedPanel
        entity={{ type: 'issue', value: 1234 }}
        onClose={() => {}}
      />,
    )
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('/api/memory/issue/1234')
    })
    expect(await screen.findByText('Known fix')).toBeInTheDocument()
  })

  it('fetches /api/memory/pr/567 when pr entity is focused', async () => {
    mockFetchJson({ query: 'PR #567', items: [] })
    render(
      <MemoryRelatedPanel
        entity={{ type: 'pr', value: 567 }}
        onClose={() => {}}
      />,
    )
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('/api/memory/pr/567')
    })
  })

  it('renders empty state when items is empty', async () => {
    mockFetchJson({ query: 'issue #1', items: [] })
    render(
      <MemoryRelatedPanel
        entity={{ type: 'issue', value: 1 }}
        onClose={() => {}}
      />,
    )
    expect(await screen.findByText(/no related memories/i)).toBeInTheDocument()
  })

  it('renders error state when fetch rejects', async () => {
    global.fetch.mockRejectedValue(new Error('boom'))
    render(
      <MemoryRelatedPanel
        entity={{ type: 'issue', value: 1 }}
        onClose={() => {}}
      />,
    )
    expect(await screen.findByText(/Hindsight unavailable/i)).toBeInTheDocument()
  })

  it('close button invokes onClose', async () => {
    mockFetchJson({ query: 'issue #1', items: [] })
    const onClose = vi.fn()
    render(
      <MemoryRelatedPanel
        entity={{ type: 'issue', value: 1 }}
        onClose={onClose}
      />,
    )
    const close = await screen.findByTestId('related-close')
    close.click()
    expect(onClose).toHaveBeenCalled()
  })
})
