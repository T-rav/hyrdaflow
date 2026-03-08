import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { RepoSelector } = await import('../RepoSelector')

function makeContext(overrides = {}) {
  return {
    supervisedRepos: [],
    runtimes: [],
    selectedRepoSlug: null,
    selectRepo: vi.fn(),
    ...overrides,
  }
}

describe('RepoSelector', () => {
  beforeEach(() => {
    mockUseHydraFlow.mockReturnValue(makeContext())
  })

  it('shows All repos label when no repo is selected', () => {
    render(<RepoSelector />)
    expect(screen.getByText('All repos')).toBeInTheDocument()
  })

  it('renders options and selects repo', () => {
    const selectRepo = vi.fn()
    mockUseHydraFlow.mockReturnValue(makeContext({
      supervisedRepos: [{ slug: 'acme/app', path: '/repos/acme/app', running: true }],
      selectRepo,
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    fireEvent.click(screen.getByText('acme/app'))
    expect(selectRepo).toHaveBeenCalledWith('acme/app')
  })

  it('opens register dialog when clicking register button', () => {
    const onOpenRegister = vi.fn()
    render(<RepoSelector onOpenRegister={onOpenRegister} />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    fireEvent.click(screen.getByText('+ Register repo'))
    expect(onOpenRegister).toHaveBeenCalledTimes(1)
  })

  it('shows selected repo label in trigger', () => {
    mockUseHydraFlow.mockReturnValue(makeContext({
      supervisedRepos: [{ slug: 'acme/app', path: '/repos/acme/app' }],
      selectedRepoSlug: 'acme-app',
    }))
    render(<RepoSelector />)
    expect(screen.getByTestId('repo-selector-trigger')).toHaveTextContent('acme/app')
  })

  it('falls back to All repos when selected slug does not match any repo', () => {
    mockUseHydraFlow.mockReturnValue(makeContext({
      supervisedRepos: [{ slug: 'acme/app' }],
      selectedRepoSlug: 'unknown-slug',
    }))
    render(<RepoSelector />)
    expect(screen.getByTestId('repo-selector-trigger')).toHaveTextContent('All repos')
  })

  it('selects All repos by passing null slug', () => {
    const selectRepo = vi.fn()
    mockUseHydraFlow.mockReturnValue(makeContext({
      supervisedRepos: [{ slug: 'acme/app' }],
      selectedRepoSlug: 'acme-app',
      selectRepo,
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    // Click the "All repos" option
    const allReposOptions = screen.getAllByText('All repos')
    fireEvent.click(allReposOptions[allReposOptions.length - 1])
    expect(selectRepo).toHaveBeenCalledWith(null)
  })

  it('shows empty state when no repos are registered', () => {
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByText('No repos registered')).toBeInTheDocument()
  })

  it('shows Running status for running repos', () => {
    mockUseHydraFlow.mockReturnValue(makeContext({
      supervisedRepos: [{ slug: 'acme/app', running: true }],
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByText('Running')).toBeInTheDocument()
  })

  it('shows Stopped status for stopped repos', () => {
    mockUseHydraFlow.mockReturnValue(makeContext({
      supervisedRepos: [{ slug: 'acme/app', running: false }],
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByText('Stopped')).toBeInTheDocument()
  })

  it('uses runtime status over repo.running when available', () => {
    mockUseHydraFlow.mockReturnValue(makeContext({
      supervisedRepos: [{ slug: 'acme/app', running: false }],
      runtimes: [{ slug: 'acme/app', running: true }],
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByText('Running')).toBeInTheDocument()
  })

  it('closes dropdown on outside click', () => {
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByTestId('repo-selector-dropdown')).toBeInTheDocument()
    // Simulate outside click
    fireEvent.mouseDown(document.body)
    expect(screen.queryByTestId('repo-selector-dropdown')).toBeNull()
  })

  it('sorts repos alphabetically', () => {
    mockUseHydraFlow.mockReturnValue(makeContext({
      supervisedRepos: [
        { slug: 'zeta/repo' },
        { slug: 'alpha/repo' },
        { slug: 'mid/repo' },
      ],
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    const options = screen.getAllByRole('option')
    // First option is "All repos", then alphabetically sorted repos
    expect(options[1]).toHaveTextContent('alpha/repo')
    expect(options[2]).toHaveTextContent('mid/repo')
    expect(options[3]).toHaveTextContent('zeta/repo')
  })

  it('highlights the selected repo option', () => {
    mockUseHydraFlow.mockReturnValue(makeContext({
      supervisedRepos: [
        { slug: 'acme/app' },
        { slug: 'acme/lib' },
      ],
      selectedRepoSlug: 'acme-app',
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    const options = screen.getAllByRole('option')
    // "All repos" should not be selected
    expect(options[0]).toHaveAttribute('aria-selected', 'false')
    // "acme/app" should be selected
    expect(options[1]).toHaveAttribute('aria-selected', 'true')
    // "acme/lib" should not be selected
    expect(options[2]).toHaveAttribute('aria-selected', 'false')
  })

  it('shows sub-label with path when available', () => {
    mockUseHydraFlow.mockReturnValue(makeContext({
      supervisedRepos: [{ slug: 'acme/app', path: '/home/user/projects/app' }],
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByText('/home/user/projects/app')).toBeInTheDocument()
  })

  it('closes dropdown after selecting a repo', () => {
    mockUseHydraFlow.mockReturnValue(makeContext({
      supervisedRepos: [{ slug: 'acme/app' }],
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByTestId('repo-selector-dropdown')).toBeInTheDocument()
    fireEvent.click(screen.getByText('acme/app'))
    expect(screen.queryByTestId('repo-selector-dropdown')).toBeNull()
  })

  it('closes dropdown and opens register dialog on register click', () => {
    const onOpenRegister = vi.fn()
    render(<RepoSelector onOpenRegister={onOpenRegister} />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByTestId('repo-selector-dropdown')).toBeInTheDocument()
    fireEvent.click(screen.getByText('+ Register repo'))
    expect(screen.queryByTestId('repo-selector-dropdown')).toBeNull()
    expect(onOpenRegister).toHaveBeenCalled()
  })

  it('uses full_name for display when available', () => {
    mockUseHydraFlow.mockReturnValue(makeContext({
      supervisedRepos: [{ full_name: 'My Custom Name', slug: 'acme/app' }],
    }))
    render(<RepoSelector />)
    fireEvent.click(screen.getByTestId('repo-selector-trigger'))
    expect(screen.getByText('My Custom Name')).toBeInTheDocument()
  })

  it('trigger has aria-haspopup and aria-expanded attributes', () => {
    render(<RepoSelector />)
    const trigger = screen.getByTestId('repo-selector-trigger')
    expect(trigger).toHaveAttribute('aria-haspopup', 'listbox')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
  })
})
