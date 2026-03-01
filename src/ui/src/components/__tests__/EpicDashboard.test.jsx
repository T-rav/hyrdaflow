import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'

const mockEpics = [
  {
    epic_number: 100,
    title: 'Epic Alpha',
    url: '#',
    status: 'active',
    merge_strategy: 'independent',
    created_at: '2026-01-10T00:00:00Z',
    total_children: 4,
    merged_children: 2,
    active_children: 1,
    children: [
      { issue_number: 101, title: 'A1', url: '#', current_stage: 'merged', status: 'done', stage_entered_at: null },
      { issue_number: 102, title: 'A2', url: '#', current_stage: 'merged', status: 'done', stage_entered_at: null },
      { issue_number: 103, title: 'A3', url: '#', current_stage: 'implement', status: 'running', stage_entered_at: new Date().toISOString() },
      { issue_number: 104, title: 'A4', url: '#', current_stage: 'triage', status: 'queued', stage_entered_at: null },
    ],
  },
  {
    epic_number: 200,
    title: 'Epic Beta',
    url: '#',
    status: 'active',
    merge_strategy: 'bundled',
    created_at: '2026-02-01T00:00:00Z',
    total_children: 3,
    merged_children: 3,
    active_children: 0,
    children: [],
  },
  {
    epic_number: 300,
    title: 'Epic Gamma',
    url: '#',
    status: 'released',
    merge_strategy: 'ordered',
    created_at: '2025-12-01T00:00:00Z',
    total_children: 2,
    merged_children: 2,
    active_children: 0,
    children: [],
  },
]

const { mockState } = vi.hoisted(() => ({
  mockState: { epics: [], epicReleasing: null, releaseEpic: () => {} },
}))

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: () => mockState,
}))

beforeEach(() => {
  mockState.epics = [...mockEpics]
  cleanup()
})

describe('EpicDashboard', () => {
  it('renders the epic dashboard container', async () => {
    const { EpicDashboard } = await import('../EpicDashboard')
    render(<EpicDashboard />)
    expect(screen.getByTestId('epic-dashboard')).toBeInTheDocument()
  })

  it('renders all epic cards', async () => {
    const { EpicDashboard } = await import('../EpicDashboard')
    render(<EpicDashboard />)
    expect(screen.getByTestId('epic-card-100')).toBeInTheDocument()
    expect(screen.getByTestId('epic-card-200')).toBeInTheDocument()
    expect(screen.getByTestId('released-card-300')).toBeInTheDocument()
  })

  it('renders filter pills', async () => {
    const { EpicDashboard } = await import('../EpicDashboard')
    render(<EpicDashboard />)
    expect(screen.getByText('All')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Ready to Release')).toBeInTheDocument()
    expect(screen.getByText('Released')).toBeInTheDocument()
  })

  it('filters to Active epics when Active pill is clicked', async () => {
    const { EpicDashboard } = await import('../EpicDashboard')
    render(<EpicDashboard />)
    fireEvent.click(screen.getByText('Active'))
    // Epic Alpha (active, not fully merged) should show
    expect(screen.getByTestId('epic-card-100')).toBeInTheDocument()
    // Epic Beta is active but all merged → "ready_to_release" category, should be hidden
    expect(screen.queryByTestId('epic-card-200')).not.toBeInTheDocument()
    // Epic Gamma is released, should be hidden
    expect(screen.queryByTestId('released-card-300')).not.toBeInTheDocument()
  })

  it('filters to Ready to Release epics', async () => {
    const { EpicDashboard } = await import('../EpicDashboard')
    render(<EpicDashboard />)
    fireEvent.click(screen.getByText('Ready to Release'))
    // Epic Beta: all 3 children merged, status active → ready_to_release
    expect(screen.getByTestId('epic-card-200')).toBeInTheDocument()
    expect(screen.queryByTestId('epic-card-100')).not.toBeInTheDocument()
    expect(screen.queryByTestId('released-card-300')).not.toBeInTheDocument()
  })

  it('filters to Released epics', async () => {
    const { EpicDashboard } = await import('../EpicDashboard')
    render(<EpicDashboard />)
    fireEvent.click(screen.getByText('Released'))
    expect(screen.getByTestId('released-card-300')).toBeInTheDocument()
    expect(screen.queryByTestId('epic-card-100')).not.toBeInTheDocument()
    expect(screen.queryByTestId('epic-card-200')).not.toBeInTheDocument()
  })

  it('shows All epics when All pill is re-clicked', async () => {
    const { EpicDashboard } = await import('../EpicDashboard')
    render(<EpicDashboard />)
    fireEvent.click(screen.getByText('Active'))
    fireEvent.click(screen.getByText('All'))
    expect(screen.getByTestId('epic-card-100')).toBeInTheDocument()
    expect(screen.getByTestId('epic-card-200')).toBeInTheDocument()
    expect(screen.getByTestId('released-card-300')).toBeInTheDocument()
  })

  it('sorts by progress (ready_to_release first)', async () => {
    const { EpicDashboard } = await import('../EpicDashboard')
    const { container } = render(<EpicDashboard />)
    // released cards have different testid prefix, query both patterns
    const cards = container.querySelectorAll('[data-testid^="epic-card-"], [data-testid^="released-card-"]')
    // ready_to_release (200) should come before active (100), then released (300)
    expect(cards[0].dataset.testid).toBe('epic-card-200')
    expect(cards[1].dataset.testid).toBe('epic-card-100')
    expect(cards[2].dataset.testid).toBe('released-card-300')
  })

  it('sorts by created date when Created sort is selected', async () => {
    const { EpicDashboard } = await import('../EpicDashboard')
    render(<EpicDashboard />)
    fireEvent.click(screen.getByText('Created'))
    // Within same category group, newest first
    // ready_to_release: 200 (Feb), active: 100 (Jan), released: 300 (Dec)
    // Category sort still applies (ready first, then active, then released)
    const cards = screen.getByTestId('epic-dashboard').querySelectorAll('[data-testid^="epic-card-"], [data-testid^="released-card-"]')
    expect(cards[0].dataset.testid).toBe('epic-card-200')
    expect(cards[1].dataset.testid).toBe('epic-card-100')
    expect(cards[2].dataset.testid).toBe('released-card-300')
  })

  it('filters by search text matching title', async () => {
    const { EpicDashboard } = await import('../EpicDashboard')
    render(<EpicDashboard />)
    const searchInput = screen.getByTestId('epic-search')
    fireEvent.change(searchInput, { target: { value: 'Alpha' } })
    expect(screen.getByTestId('epic-card-100')).toBeInTheDocument()
    expect(screen.queryByTestId('epic-card-200')).not.toBeInTheDocument()
  })

  it('filters by search text matching epic number', async () => {
    const { EpicDashboard } = await import('../EpicDashboard')
    render(<EpicDashboard />)
    const searchInput = screen.getByTestId('epic-search')
    fireEvent.change(searchInput, { target: { value: '200' } })
    expect(screen.getByTestId('epic-card-200')).toBeInTheDocument()
    expect(screen.queryByTestId('epic-card-100')).not.toBeInTheDocument()
  })

  it('shows empty state when no epics', async () => {
    mockState.epics = []
    const { EpicDashboard } = await import('../EpicDashboard')
    render(<EpicDashboard />)
    expect(screen.getByTestId('epic-empty')).toBeInTheDocument()
    expect(screen.getByText('No epics found')).toBeInTheDocument()
  })

  it('shows "No matching epics" when filter/search yields nothing', async () => {
    const { EpicDashboard } = await import('../EpicDashboard')
    render(<EpicDashboard />)
    const searchInput = screen.getByTestId('epic-search')
    fireEvent.change(searchInput, { target: { value: 'nonexistent' } })
    expect(screen.getByText('No matching epics')).toBeInTheDocument()
  })

  it('renders sort controls', async () => {
    const { EpicDashboard } = await import('../EpicDashboard')
    render(<EpicDashboard />)
    expect(screen.getByText('Progress')).toBeInTheDocument()
    expect(screen.getByText('Created')).toBeInTheDocument()
  })

  it('renders search input', async () => {
    const { EpicDashboard } = await import('../EpicDashboard')
    render(<EpicDashboard />)
    expect(screen.getByTestId('epic-search')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Search epics...')).toBeInTheDocument()
  })
})
