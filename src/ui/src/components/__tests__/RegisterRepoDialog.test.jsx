import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { RegisterRepoDialog, extractSlugFromUrl } = await import('../RegisterRepoDialog')

describe('RegisterRepoDialog', () => {
  beforeEach(() => {
    mockUseHydraFlow.mockReturnValue({
      addRepoBySlug: vi.fn().mockResolvedValue({ ok: true }),
      addRepoByPath: vi.fn().mockResolvedValue({ ok: true }),
    })
  })

  it('does not render when closed', () => {
    const { container } = render(<RegisterRepoDialog isOpen={false} onClose={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('validates when no inputs provided', () => {
    render(<RegisterRepoDialog isOpen onClose={() => {}} />)
    fireEvent.submit(screen.getByTestId('register-submit').closest('form'))
    expect(screen.getByText('Enter a GitHub URL, slug, or repo path')).toBeInTheDocument()
  })

  it('submits slug via addRepoBySlug', async () => {
    const addRepoBySlug = vi.fn().mockResolvedValue({ ok: true })
    mockUseHydraFlow.mockReturnValue({
      addRepoBySlug,
      addRepoByPath: vi.fn(),
    })
    const onClose = vi.fn()
    render(<RegisterRepoDialog isOpen onClose={onClose} />)
    fireEvent.change(screen.getByLabelText('GitHub URL or slug'), { target: { value: 'acme/app' } })
    fireEvent.click(screen.getByTestId('register-submit'))
    await waitFor(() => expect(addRepoBySlug).toHaveBeenCalledWith('acme/app'))
    expect(onClose).toHaveBeenCalled()
  })

  it('falls back to path registration when slug is empty', async () => {
    const addRepoByPath = vi.fn().mockResolvedValue({ ok: true })
    mockUseHydraFlow.mockReturnValue({
      addRepoBySlug: vi.fn(),
      addRepoByPath,
    })
    render(<RegisterRepoDialog isOpen onClose={() => {}} />)
    fireEvent.change(screen.getByLabelText('Filesystem path'), { target: { value: '/repos/demo' } })
    fireEvent.click(screen.getByTestId('register-submit'))
    await waitFor(() => expect(addRepoByPath).toHaveBeenCalledWith('/repos/demo'))
  })

  it('displays error message when registration fails', async () => {
    const addRepoBySlug = vi.fn().mockResolvedValue({ ok: false, error: 'Repo not found' })
    mockUseHydraFlow.mockReturnValue({
      addRepoBySlug,
      addRepoByPath: vi.fn(),
    })
    const onClose = vi.fn()
    render(<RegisterRepoDialog isOpen onClose={onClose} />)
    fireEvent.change(screen.getByLabelText('GitHub URL or slug'), { target: { value: 'acme/missing' } })
    fireEvent.click(screen.getByTestId('register-submit'))
    await waitFor(() => expect(screen.getByText('Repo not found')).toBeInTheDocument())
    expect(onClose).not.toHaveBeenCalled()
  })

  it('shows default error when result has no error message', async () => {
    const addRepoBySlug = vi.fn().mockResolvedValue({ ok: false })
    mockUseHydraFlow.mockReturnValue({
      addRepoBySlug,
      addRepoByPath: vi.fn(),
    })
    render(<RegisterRepoDialog isOpen onClose={() => {}} />)
    fireEvent.change(screen.getByLabelText('GitHub URL or slug'), { target: { value: 'acme/fail' } })
    fireEvent.click(screen.getByTestId('register-submit'))
    await waitFor(() => expect(screen.getByText('Registration failed')).toBeInTheDocument())
  })

  it('closes on Escape key', () => {
    const onClose = vi.fn()
    render(<RegisterRepoDialog isOpen onClose={onClose} />)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('closes when clicking overlay background', () => {
    const onClose = vi.fn()
    render(<RegisterRepoDialog isOpen onClose={onClose} />)
    fireEvent.click(screen.getByTestId('register-repo-overlay'))
    expect(onClose).toHaveBeenCalled()
  })

  it('does not close when clicking inside the card', () => {
    const onClose = vi.fn()
    render(<RegisterRepoDialog isOpen onClose={onClose} />)
    // Click the subtitle paragraph inside the card (not overlay, not a close button)
    fireEvent.click(screen.getByText(/Paste a GitHub URL/))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('closes via the X button', () => {
    const onClose = vi.fn()
    render(<RegisterRepoDialog isOpen onClose={onClose} />)
    fireEvent.click(screen.getByLabelText('Close register repo dialog'))
    expect(onClose).toHaveBeenCalled()
  })

  it('closes via Cancel button', () => {
    const onClose = vi.fn()
    render(<RegisterRepoDialog isOpen onClose={onClose} />)
    fireEvent.click(screen.getByText('Cancel'))
    expect(onClose).toHaveBeenCalled()
  })

  it('resets form state when reopened', () => {
    const { rerender } = render(<RegisterRepoDialog isOpen onClose={() => {}} />)
    fireEvent.change(screen.getByLabelText('GitHub URL or slug'), { target: { value: 'acme/app' } })
    expect(screen.getByLabelText('GitHub URL or slug').value).toBe('acme/app')
    // Close and reopen
    rerender(<RegisterRepoDialog isOpen={false} onClose={() => {}} />)
    rerender(<RegisterRepoDialog isOpen onClose={() => {}} />)
    expect(screen.getByLabelText('GitHub URL or slug').value).toBe('')
  })

  it('submit button is disabled when both inputs are empty', () => {
    render(<RegisterRepoDialog isOpen onClose={() => {}} />)
    const btn = screen.getByTestId('register-submit')
    expect(btn).toBeDisabled()
  })

  it('submit button is enabled when slug is provided', () => {
    render(<RegisterRepoDialog isOpen onClose={() => {}} />)
    fireEvent.change(screen.getByLabelText('GitHub URL or slug'), { target: { value: 'acme/app' } })
    const btn = screen.getByTestId('register-submit')
    expect(btn).not.toBeDisabled()
  })

  it('shows Registering text while submitting', async () => {
    let resolveSubmit
    const addRepoBySlug = vi.fn().mockImplementation(() => new Promise(r => { resolveSubmit = r }))
    mockUseHydraFlow.mockReturnValue({
      addRepoBySlug,
      addRepoByPath: vi.fn(),
    })
    render(<RegisterRepoDialog isOpen onClose={() => {}} />)
    fireEvent.change(screen.getByLabelText('GitHub URL or slug'), { target: { value: 'acme/app' } })
    fireEvent.click(screen.getByTestId('register-submit'))
    await waitFor(() => expect(screen.getByText('Registering\u2026')).toBeInTheDocument())
    resolveSubmit({ ok: true })
  })

  it('prefers slug over path when both are provided', async () => {
    const addRepoBySlug = vi.fn().mockResolvedValue({ ok: true })
    const addRepoByPath = vi.fn().mockResolvedValue({ ok: true })
    mockUseHydraFlow.mockReturnValue({ addRepoBySlug, addRepoByPath })
    render(<RegisterRepoDialog isOpen onClose={() => {}} />)
    fireEvent.change(screen.getByLabelText('GitHub URL or slug'), { target: { value: 'acme/app' } })
    fireEvent.change(screen.getByLabelText('Filesystem path'), { target: { value: '/repos/app' } })
    fireEvent.click(screen.getByTestId('register-submit'))
    await waitFor(() => expect(addRepoBySlug).toHaveBeenCalledWith('acme/app'))
    expect(addRepoByPath).not.toHaveBeenCalled()
  })

  it('extracts slug from GitHub URL and submits it', async () => {
    const addRepoBySlug = vi.fn().mockResolvedValue({ ok: true })
    mockUseHydraFlow.mockReturnValue({
      addRepoBySlug,
      addRepoByPath: vi.fn(),
    })
    const onClose = vi.fn()
    render(<RegisterRepoDialog isOpen onClose={onClose} />)
    fireEvent.change(screen.getByLabelText('GitHub URL or slug'), {
      target: { value: 'https://github.com/acme/app' },
    })
    fireEvent.click(screen.getByTestId('register-submit'))
    await waitFor(() => expect(addRepoBySlug).toHaveBeenCalledWith('acme/app'))
    expect(onClose).toHaveBeenCalled()
  })

  it('extracts slug from GitHub URL with .git suffix', async () => {
    const addRepoBySlug = vi.fn().mockResolvedValue({ ok: true })
    mockUseHydraFlow.mockReturnValue({
      addRepoBySlug,
      addRepoByPath: vi.fn(),
    })
    render(<RegisterRepoDialog isOpen onClose={() => {}} />)
    fireEvent.change(screen.getByLabelText('GitHub URL or slug'), {
      target: { value: 'https://github.com/acme/app.git' },
    })
    fireEvent.click(screen.getByTestId('register-submit'))
    await waitFor(() => expect(addRepoBySlug).toHaveBeenCalledWith('acme/app'))
  })

  it('passes through plain slug unchanged', async () => {
    const addRepoBySlug = vi.fn().mockResolvedValue({ ok: true })
    mockUseHydraFlow.mockReturnValue({
      addRepoBySlug,
      addRepoByPath: vi.fn(),
    })
    render(<RegisterRepoDialog isOpen onClose={() => {}} />)
    fireEvent.change(screen.getByLabelText('GitHub URL or slug'), {
      target: { value: 'acme/app' },
    })
    fireEvent.click(screen.getByTestId('register-submit'))
    await waitFor(() => expect(addRepoBySlug).toHaveBeenCalledWith('acme/app'))
  })
})

// ---------------------------------------------------------------------------
// extractSlugFromUrl unit tests
// ---------------------------------------------------------------------------

describe('extractSlugFromUrl', () => {
  it('extracts slug from https GitHub URL', () => {
    expect(extractSlugFromUrl('https://github.com/owner/repo')).toBe('owner/repo')
  })

  it('extracts slug from http GitHub URL', () => {
    expect(extractSlugFromUrl('http://github.com/owner/repo')).toBe('owner/repo')
  })

  it('extracts slug from URL with .git suffix', () => {
    expect(extractSlugFromUrl('https://github.com/owner/repo.git')).toBe('owner/repo')
  })

  it('extracts slug from URL with trailing path segments', () => {
    expect(extractSlugFromUrl('https://github.com/owner/repo/tree/main/src')).toBe('owner/repo')
  })

  it('extracts slug from bare github.com URL without protocol', () => {
    expect(extractSlugFromUrl('github.com/owner/repo')).toBe('owner/repo')
  })

  it('extracts slug from www.github.com URL', () => {
    expect(extractSlugFromUrl('https://www.github.com/owner/repo')).toBe('owner/repo')
  })

  it('returns null for plain slug (not a URL)', () => {
    expect(extractSlugFromUrl('owner/repo')).toBeNull()
  })

  it('returns null for empty string', () => {
    expect(extractSlugFromUrl('')).toBeNull()
  })

  it('returns null for null input', () => {
    expect(extractSlugFromUrl(null)).toBeNull()
  })

  it('returns null for GitHub URL with only owner (no repo)', () => {
    expect(extractSlugFromUrl('https://github.com/owner')).toBeNull()
  })

  it('returns null for non-GitHub URL', () => {
    expect(extractSlugFromUrl('https://gitlab.com/owner/repo')).toBeNull()
  })

  it('returns null for lookalike domains ending in github.com', () => {
    expect(extractSlugFromUrl('https://notgithub.com/owner/repo')).toBeNull()
  })

  it('returns null for GitHub subdomain URLs (e.g. gist.github.com)', () => {
    expect(extractSlugFromUrl('https://gist.github.com/owner/abc123')).toBeNull()
  })

  it('handles whitespace around URL', () => {
    expect(extractSlugFromUrl('  https://github.com/owner/repo  ')).toBe('owner/repo')
  })
})
