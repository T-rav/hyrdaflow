import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { GitHubRepoPicker } from '../GitHubRepoPicker'

describe('GitHubRepoPicker', () => {
  let fetchSpy

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    fetchSpy = vi.fn()
    globalThis.fetch = fetchSpy
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  const mockRepoResponse = (repos = []) => {
    fetchSpy.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ repos }),
    })
  }

  it('renders search input', async () => {
    mockRepoResponse()
    await act(async () => {
      render(<GitHubRepoPicker onSelect={vi.fn()} />)
    })
    expect(screen.getByTestId('github-repo-search')).toBeInTheDocument()
  })

  it('fetches repos on mount', async () => {
    mockRepoResponse([
      { name: 'myrepo', owner: { login: 'alice' }, description: 'A repo' },
    ])
    await act(async () => {
      render(<GitHubRepoPicker onSelect={vi.fn()} />)
    })
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith('/api/github/repos')
    })
    expect(screen.getByText('alice/myrepo')).toBeInTheDocument()
    expect(screen.getByText('A repo')).toBeInTheDocument()
  })

  it('shows empty state when no repos found', async () => {
    mockRepoResponse([])
    await act(async () => {
      render(<GitHubRepoPicker onSelect={vi.fn()} />)
    })
    await waitFor(() => {
      expect(screen.getByText('No repos found')).toBeInTheDocument()
    })
  })

  it('shows error when fetch fails', async () => {
    fetchSpy.mockResolvedValue({
      ok: false,
      status: 503,
      json: () => Promise.resolve({ error: 'gh CLI not found' }),
    })
    await act(async () => {
      render(<GitHubRepoPicker onSelect={vi.fn()} />)
    })
    await waitFor(() => {
      expect(screen.getByText('gh CLI not found')).toBeInTheDocument()
    })
  })

  it('shows error when fetch throws', async () => {
    fetchSpy.mockRejectedValue(new Error('Network error'))
    await act(async () => {
      render(<GitHubRepoPicker onSelect={vi.fn()} />)
    })
    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument()
    })
  })

  it('debounces search queries', async () => {
    mockRepoResponse()
    await act(async () => {
      render(<GitHubRepoPicker onSelect={vi.fn()} />)
    })
    // Initial fetch
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1))

    fetchSpy.mockClear()
    mockRepoResponse()

    // Type quickly
    await act(async () => {
      fireEvent.change(screen.getByTestId('github-repo-search'), { target: { value: 'f' } })
    })
    await act(async () => {
      fireEvent.change(screen.getByTestId('github-repo-search'), { target: { value: 'fo' } })
    })
    await act(async () => {
      fireEvent.change(screen.getByTestId('github-repo-search'), { target: { value: 'foo' } })
    })

    // Before debounce fires, no new fetch
    expect(fetchSpy).not.toHaveBeenCalled()

    // Advance timer past debounce
    await act(async () => {
      vi.advanceTimersByTime(350)
    })

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(1)
      expect(fetchSpy).toHaveBeenCalledWith('/api/github/repos?query=foo')
    })
  })

  it('clones repo on click and calls onSelect', async () => {
    mockRepoResponse([
      { name: 'myrepo', owner: { login: 'alice' }, description: '' },
    ])
    const onSelect = vi.fn()
    await act(async () => {
      render(<GitHubRepoPicker onSelect={onSelect} />)
    })
    await waitFor(() => {
      expect(screen.getByText('alice/myrepo')).toBeInTheDocument()
    })

    // Mock the clone response
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ status: 'ok', slug: 'alice/myrepo', path: '/repos/alice/myrepo' }),
    })

    await act(async () => {
      fireEvent.click(screen.getByTestId('github-repo-item-alice/myrepo'))
    })

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith('/api/github/clone', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slug: 'alice/myrepo' }),
      })
    })
    expect(onSelect).toHaveBeenCalledWith('alice/myrepo')
  })

  it('shows error when clone fails', async () => {
    mockRepoResponse([
      { name: 'myrepo', owner: { login: 'alice' }, description: '' },
    ])
    await act(async () => {
      render(<GitHubRepoPicker onSelect={vi.fn()} />)
    })
    await waitFor(() => {
      expect(screen.getByText('alice/myrepo')).toBeInTheDocument()
    })

    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: () => Promise.resolve({ error: 'Clone failed: not found' }),
    })

    await act(async () => {
      fireEvent.click(screen.getByTestId('github-repo-item-alice/myrepo'))
    })

    await waitFor(() => {
      expect(screen.getByText('Clone failed: not found')).toBeInTheDocument()
    })
  })

  it('disables buttons when disabled prop is true', async () => {
    mockRepoResponse([
      { name: 'myrepo', owner: { login: 'alice' }, description: '' },
    ])
    await act(async () => {
      render(<GitHubRepoPicker onSelect={vi.fn()} disabled />)
    })
    await waitFor(() => {
      expect(screen.getByTestId('github-repo-search')).toBeDisabled()
    })
  })
})
