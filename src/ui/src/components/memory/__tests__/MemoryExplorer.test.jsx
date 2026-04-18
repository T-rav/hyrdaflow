import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()
vi.mock('../../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { MemoryExplorer } = await import('../MemoryExplorer')

const BASE_CONTEXT = {
  memories: { total_items: 1, items: [{ issue_number: 42, learning: 'thing' }] },
  retrospectives: { total_entries: 0 },
  reviewInsights: { total_reviews: 0 },
  troubleshooting: { total_patterns: 0 },
  harnessInsights: null,
}

beforeEach(() => {
  mockUseHydraFlow.mockReturnValue(BASE_CONTEXT)
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ banks: [{ id: 'hydraflow-tribal', name: 'TRIBAL' }] }),
  })
})
afterEach(() => { vi.restoreAllMocks() })

describe('MemoryExplorer', () => {
  it('renders top bar, section list, and no related panel initially', async () => {
    render(<MemoryExplorer />)
    expect(screen.getByTestId('memory-top-bar')).toBeInTheDocument()
    expect(screen.getByTestId('memory-explorer')).toBeInTheDocument()
    expect(screen.queryByTestId('memory-related-panel')).not.toBeInTheDocument()
  })

  it('clicking an issue chip opens the related panel', async () => {
    global.fetch.mockImplementation((url) => {
      if (String(url).includes('/api/memory/banks')) {
        return Promise.resolve({ ok: true, json: async () => ({ banks: [] }) })
      }
      return Promise.resolve({ ok: true, json: async () => ({ query: 'issue #42', items: [] }) })
    })
    render(<MemoryExplorer />)
    fireEvent.click(screen.getByTestId('entity-chip-issue-42'))
    expect(await screen.findByTestId('memory-related-panel')).toBeInTheDocument()
  })

  it('close button on related panel clears focus', async () => {
    global.fetch.mockImplementation((url) => {
      if (String(url).includes('/api/memory/banks')) {
        return Promise.resolve({ ok: true, json: async () => ({ banks: [] }) })
      }
      return Promise.resolve({ ok: true, json: async () => ({ query: 'issue #42', items: [] }) })
    })
    render(<MemoryExplorer />)
    fireEvent.click(screen.getByTestId('entity-chip-issue-42'))
    const panel = await screen.findByTestId('memory-related-panel')
    expect(panel).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('related-close'))
    await waitFor(() => {
      expect(screen.queryByTestId('memory-related-panel')).not.toBeInTheDocument()
    })
  })

  it('Escape key clears focus when panel is open', async () => {
    global.fetch.mockImplementation((url) => {
      if (String(url).includes('/api/memory/banks')) {
        return Promise.resolve({ ok: true, json: async () => ({ banks: [] }) })
      }
      return Promise.resolve({ ok: true, json: async () => ({ query: 'issue #42', items: [] }) })
    })
    render(<MemoryExplorer />)
    fireEvent.click(screen.getByTestId('entity-chip-issue-42'))
    await screen.findByTestId('memory-related-panel')
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => {
      expect(screen.queryByTestId('memory-related-panel')).not.toBeInTheDocument()
    })
  })

  it('search input filters visible items in the section list', async () => {
    global.fetch.mockImplementation((url) => {
      if (String(url).includes('/api/memory/banks')) {
        return Promise.resolve({ ok: true, json: async () => ({ banks: [] }) })
      }
      return Promise.resolve({ ok: true, json: async () => ({ query: '', items: [] }) })
    })
    render(<MemoryExplorer />)
    expect(screen.getByText(/thing/i)).toBeInTheDocument()
    fireEvent.change(screen.getByTestId('memory-search-input'), { target: { value: 'nomatch-xyz' } })
    await waitFor(() => {
      expect(screen.queryByText(/thing/i)).not.toBeInTheDocument()
    })
  })
})
