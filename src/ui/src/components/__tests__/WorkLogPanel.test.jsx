import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { WorkLogPanel } from '../WorkLogPanel'

const mockCrates = [
  {
    number: 1,
    title: 'Release v2.0',
    description: 'Major milestone',
    due_on: '2026-03-15T00:00:00Z',
    state: 'open',
    open_issues: 3,
    closed_issues: 2,
    total_issues: 5,
    progress: 40,
    created_at: '2026-02-01T00:00:00Z',
    updated_at: '2026-02-20T00:00:00Z',
  },
  {
    number: 2,
    title: 'Hotfix batch',
    description: '',
    due_on: null,
    state: 'closed',
    open_issues: 0,
    closed_issues: 3,
    total_issues: 3,
    progress: 100,
    created_at: '2026-02-10T00:00:00Z',
    updated_at: '2026-02-15T00:00:00Z',
  },
]

describe('WorkLogPanel', () => {
  beforeEach(() => {
    global.fetch = vi.fn((url) => {
      if (url === '/api/crates') {
        return Promise.resolve({ ok: true, json: async () => mockCrates })
      }
      return Promise.resolve({ ok: true, json: async () => [] })
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders crate list', async () => {
    render(<WorkLogPanel />)
    await waitFor(() => expect(screen.getByText('Release v2.0')).toBeInTheDocument())
    expect(screen.getByText('Hotfix batch')).toBeInTheDocument()
  })

  it('renders crates section', async () => {
    render(<WorkLogPanel />)
    await waitFor(() => expect(screen.getByText('Release v2.0')).toBeInTheDocument())
    expect(screen.getByTestId('crates-list')).toBeInTheDocument()
  })

  it('shows create crate input and button', async () => {
    render(<WorkLogPanel />)
    await waitFor(() => expect(screen.getByTestId('new-crate-input')).toBeInTheDocument())
    expect(screen.getByTestId('create-crate-btn')).toBeInTheDocument()
  })

  it('create crate button is disabled when input is empty', async () => {
    render(<WorkLogPanel />)
    await waitFor(() => expect(screen.getByTestId('create-crate-btn')).toBeInTheDocument())
    expect(screen.getByTestId('create-crate-btn')).toBeDisabled()
  })

  it('filters crates by state', async () => {
    render(<WorkLogPanel />)
    await waitFor(() => expect(screen.getByText('Release v2.0')).toBeInTheDocument())

    const crateSelect = screen.getByTestId('crate-filter')
    fireEvent.change(crateSelect, { target: { value: 'closed' } })
    expect(screen.queryByText('Release v2.0')).not.toBeInTheDocument()
    expect(screen.getByText('Hotfix batch')).toBeInTheDocument()
  })

  it('shows summary cards with counts', async () => {
    render(<WorkLogPanel />)
    await waitFor(() => expect(screen.getByText('Release v2.0')).toBeInTheDocument())
    // Summary cards show crate and epic counts — use getAllByText since numbers may appear elsewhere
    expect(screen.getAllByText('2').length).toBeGreaterThanOrEqual(1) // 2 crates
  })

  it('calls POST /api/crates when creating a crate', async () => {
    render(<WorkLogPanel />)
    await waitFor(() => expect(screen.getByTestId('new-crate-input')).toBeInTheDocument())

    fireEvent.change(screen.getByTestId('new-crate-input'), { target: { value: 'Sprint 3' } })
    fireEvent.click(screen.getByTestId('create-crate-btn'))

    await waitFor(() => {
      const postCalls = global.fetch.mock.calls.filter(
        ([url, opts]) => url === '/api/crates' && opts?.method === 'POST'
      )
      expect(postCalls.length).toBe(1)
      const body = JSON.parse(postCalls[0][1].body)
      expect(body.title).toBe('Sprint 3')
    })
  })

  it('shows loading text while fetching', () => {
    global.fetch = vi.fn(() => new Promise(() => {}))
    render(<WorkLogPanel />)
    expect(screen.getByText('Loading delivery queue...')).toBeInTheDocument()
  })

  it('shows error message when API fails', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('network error'))
    render(<WorkLogPanel />)
    await waitFor(() => expect(screen.getByText('Could not load delivery queue data')).toBeInTheDocument())
  })

  it('filters crates by search text', async () => {
    render(<WorkLogPanel />)
    await waitFor(() => expect(screen.getByText('Release v2.0')).toBeInTheDocument())

    fireEvent.change(screen.getByPlaceholderText('Search crates'), { target: { value: 'hotfix' } })
    expect(screen.getByText('Hotfix batch')).toBeInTheDocument()
    expect(screen.queryByText('Release v2.0')).not.toBeInTheDocument()
  })

  it('creates crate on Enter key', async () => {
    render(<WorkLogPanel />)
    await waitFor(() => expect(screen.getByTestId('new-crate-input')).toBeInTheDocument())

    const input = screen.getByTestId('new-crate-input')
    fireEvent.change(input, { target: { value: 'Sprint 4' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => {
      const postCalls = global.fetch.mock.calls.filter(
        ([url, opts]) => url === '/api/crates' && opts?.method === 'POST'
      )
      expect(postCalls.length).toBe(1)
    })
  })
})
