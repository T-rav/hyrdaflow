import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { SessionSidebar } = await import('../SessionSidebar')

function defaultContext(overrides = {}) {
  return {
    sessions: [],
    currentSessionId: null,
    selectedSessionId: null,
    selectedRepoSlug: null,
    stageStatus: { workload: { total: 0, active: 0, done: 0, failed: 0 } },
    selectSession: vi.fn(),
    selectRepo: vi.fn(),
    deleteSession: vi.fn(),
    supervisedRepos: [],
    runtimes: [],
    startRuntime: vi.fn(),
    stopRuntime: vi.fn(),
    addRepoByPath: vi.fn(),
    removeRepoShortcut: vi.fn(),
    ...overrides,
  }
}

beforeEach(() => {
  mockUseHydraFlow.mockReturnValue(defaultContext())
})

const SESSION_A = {
  id: 'org-repo-20240315T142530',
  repo: 'org/repo',
  started_at: '2024-03-15T14:25:30+00:00',
  ended_at: '2024-03-15T15:00:00+00:00',
  issues_processed: [1, 2, 3],
  issues_succeeded: 2,
  issues_failed: 1,
  status: 'completed',
}

const SESSION_B = {
  id: 'org-repo-20240316T100000',
  repo: 'org/repo',
  started_at: '2024-03-16T10:00:00+00:00',
  ended_at: null,
  issues_processed: [],
  issues_succeeded: 0,
  issues_failed: 0,
  status: 'active',
}

const SESSION_OTHER = {
  id: 'other-repo-20240315T090000',
  repo: 'other-org/other-repo',
  started_at: '2024-03-15T09:00:00+00:00',
  ended_at: '2024-03-15T09:30:00+00:00',
  issues_processed: [10],
  issues_succeeded: 1,
  issues_failed: 0,
  status: 'completed',
}

const SUPERVISED_REPO = {
  slug: 'demo',
  path: '/repos/demo',
  running: true,
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

describe('SessionSidebar with no sessions', () => {
  it('renders "Sessions" header', () => {
    render(<SessionSidebar />)
    expect(screen.getByText('Sessions')).toBeDefined()
  })

  it('renders "All Repos" button', () => {
    render(<SessionSidebar />)
    expect(screen.getByText('All Repos')).toBeDefined()
  })

  it('shows empty state message when no sessions', () => {
    render(<SessionSidebar />)
    expect(screen.getByText('No sessions yet')).toBeDefined()
  })

  it('does not show count badge when sessions is empty', () => {
    render(<SessionSidebar />)
    // count badge only appears if sessions.length > 0
    expect(screen.queryByText('0')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Sessions rendering
// ---------------------------------------------------------------------------

describe('SessionSidebar with sessions', () => {
  beforeEach(() => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_A, SESSION_B] })
    )
  })

  it('renders repo group header', () => {
    render(<SessionSidebar />)
    expect(screen.getByText('org/repo')).toBeDefined()
  })

  it('shows issue count pill for sessions with processed issues', () => {
    render(<SessionSidebar />)
    // SESSION_A has 3 issues_processed
    expect(screen.getByText('3')).toBeDefined()
  })

  it('shows success count for sessions with successes', () => {
    render(<SessionSidebar />)
    // SESSION_A has 2 successes
    expect(screen.getByText('2✓')).toBeDefined()
  })

  it('shows fail count for sessions with failures', () => {
    render(<SessionSidebar />)
    // SESSION_A has 1 failure
    expect(screen.getByText('1✗')).toBeDefined()
  })

  it('shows total session count badge in header', () => {
    render(<SessionSidebar />)
    // Both header badge and repo count show '2', verify at least one exists
    expect(screen.getAllByText('2').length).toBeGreaterThanOrEqual(1)
  })
})

// ---------------------------------------------------------------------------
// Multi-repo grouping
// ---------------------------------------------------------------------------

describe('SessionSidebar with multiple repos', () => {
  beforeEach(() => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_A, SESSION_OTHER] })
    )
  })

  it('renders both repo group headers', () => {
    render(<SessionSidebar />)
    expect(screen.getByText('org/repo')).toBeDefined()
    expect(screen.getByText('other-org/other-repo')).toBeDefined()
  })

  it('renders add repo button and disconnect button per supervised repo', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        sessions: [SESSION_A],
        supervisedRepos: [{ slug: 'repo', path: 'org/repo', running: false }],
      })
    )
    render(<SessionSidebar />)
    expect(screen.getByLabelText('Add repo')).toBeDefined()
    expect(screen.getByLabelText('Disconnect repo')).toBeDefined()
  })

  it('does not render disconnect button for session-only repos', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_A] })
    )
    render(<SessionSidebar />)
    expect(screen.getByLabelText('Add repo')).toBeDefined()
    expect(screen.queryByLabelText('Disconnect repo')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Supervised repos fallback
// ---------------------------------------------------------------------------

describe('SessionSidebar supervised repo state', () => {
  it('renders supervised repo even when no sessions exist', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ supervisedRepos: [SUPERVISED_REPO] })
    )
    render(<SessionSidebar />)
    expect(screen.getByText('demo')).toBeDefined()
    expect(screen.getByText('/repos/demo')).toBeDefined()
    // Running repo shows Stop button instead of RUNNING label
    expect(screen.getByText('Stop')).toBeDefined()
  })

  it('shows Start button for non-running supervised repo', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        supervisedRepos: [{ ...SUPERVISED_REPO, running: false }],
      })
    )
    render(<SessionSidebar />)
    expect(screen.getByText('Start')).toBeDefined()
  })
})

// ---------------------------------------------------------------------------
// Selection
// ---------------------------------------------------------------------------

describe('SessionSidebar selection', () => {
  it('calls selectSession(null) and selectRepo(null) when clicking All Repos button', () => {
    const selectSession = vi.fn()
    const selectRepo = vi.fn()
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_A], selectSession, selectRepo })
    )
    render(<SessionSidebar />)
    fireEvent.click(screen.getByText('All Repos'))
    expect(selectSession).toHaveBeenCalledWith(null)
    expect(selectRepo).toHaveBeenCalledWith(null)
  })

  it('calls selectSession with session id when clicking a session row', () => {
    const selectSession = vi.fn()
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_A], selectSession })
    )
    render(<SessionSidebar />)
    // session time is shown as relative text; click the row using test-id workaround
    // The session row includes the relativeTime + meta; click anywhere in the list
    const repoGroup = screen.getByText('org/repo')
    // The session row is rendered after the repo group; find session-specific text
    // Since SESSION_A has 3 issues and 2 succeeded, clicking the success count fires selectSession
    fireEvent.click(screen.getByText('2✓'))
    expect(selectSession).toHaveBeenCalledWith(SESSION_A.id)
  })
})

// ---------------------------------------------------------------------------
// Repo collapse / expand
// ---------------------------------------------------------------------------

describe('SessionSidebar collapsible repo sections', () => {
  beforeEach(() => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_A] })
    )
  })

  it('sessions are visible when repo section is expanded (default)', () => {
    render(<SessionSidebar />)
    // Issue count pill for SESSION_A should be visible
    expect(screen.getByText('3')).toBeDefined()
  })

  it('sessions are hidden after collapsing repo section', () => {
    render(<SessionSidebar />)
    // Click arrow to collapse (arrow is in its own clickable span)
    fireEvent.click(screen.getByText('▾'))
    // Issue count pill should no longer be in the DOM
    expect(screen.queryByText('3')).toBeNull()
  })

  it('toggle arrow changes on collapse/expand', () => {
    render(<SessionSidebar />)
    // Initially expanded — down arrow
    expect(screen.getByText('▾')).toBeDefined()
    fireEvent.click(screen.getByText('▾'))
    // After collapse — right arrow
    expect(screen.getByText('▸')).toBeDefined()
  })
})

// ---------------------------------------------------------------------------
// Active session highlighting
// ---------------------------------------------------------------------------

describe('SessionSidebar active session state', () => {
  it('currentSessionId is reflected (session with active status rendered)', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        sessions: [SESSION_B],
        currentSessionId: SESSION_B.id,
        selectedSessionId: null,
      })
    )
    render(<SessionSidebar />)
    // Active session has status 'active' — no issue pill since issues_processed is empty
    // The repo header should be visible
    expect(screen.getByText('org/repo')).toBeDefined()
  })

  it('shows live success/fail counts for current active session', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        sessions: [SESSION_B],
        currentSessionId: SESSION_B.id,
        stageStatus: { workload: { total: 9, active: 2, done: 4, failed: 1 } },
      })
    )
    render(<SessionSidebar />)
    expect(screen.getByText('4✓')).toBeDefined()
    expect(screen.getByText('1✗')).toBeDefined()
    // issue pill uses done+failed for live active session
    expect(screen.getByText('5')).toBeDefined()
  })
})

// ---------------------------------------------------------------------------
// Session naming: date/time instead of relative time
// ---------------------------------------------------------------------------

describe('SessionSidebar session naming', () => {
  it('displays formatted date/time instead of relative time', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_A] })
    )
    render(<SessionSidebar />)
    // Should show toLocaleString() output for the session's started_at
    const expected = new Date(SESSION_A.started_at).toLocaleString()
    expect(screen.getByText(expected)).toBeDefined()
  })

  it('does not show relative time strings', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_A] })
    )
    render(<SessionSidebar />)
    // Relative time strings like "Xm ago", "Xh ago", "Xd ago" should not appear
    expect(screen.queryByText(/\d+[mhd] ago/)).toBeNull()
    expect(screen.queryByText('just now')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Repo slug in session row
// ---------------------------------------------------------------------------

describe('SessionSidebar repo slug display', () => {
  it('shows short repo name in each session row', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_A] })
    )
    render(<SessionSidebar />)
    // Short repo slug "repo" should appear in session row
    expect(screen.getByText('repo')).toBeDefined()
  })

  it('shows short repo name for multi-segment repo', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_OTHER] })
    )
    render(<SessionSidebar />)
    // Short slug for 'other-org/other-repo' is 'other-repo'
    expect(screen.getByText('other-repo')).toBeDefined()
  })
})

// ---------------------------------------------------------------------------
// Delete button
// ---------------------------------------------------------------------------

describe('SessionSidebar delete button', () => {
  it('shows delete button on hover for completed session', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_A] })
    )
    render(<SessionSidebar />)
    // Find the session row by its success count
    const successEl = screen.getByText('2✓')
    const sessionRow = successEl.closest('[style]')
    // Simulate hover
    fireEvent.mouseEnter(sessionRow)
    expect(screen.getByLabelText('Delete session')).toBeDefined()
  })

  it('does not show delete button for active session', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        sessions: [SESSION_B],
        currentSessionId: SESSION_B.id,
      })
    )
    render(<SessionSidebar />)
    // SESSION_B is active — no delete button should exist
    expect(screen.queryByLabelText('Delete session')).toBeNull()
  })

  it('calls deleteSession when clicking delete button', () => {
    const deleteSession = vi.fn()
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_A], deleteSession })
    )
    render(<SessionSidebar />)
    // Hover to reveal delete button
    const successEl = screen.getByText('2✓')
    const sessionRow = successEl.closest('[style]')
    fireEvent.mouseEnter(sessionRow)
    const deleteBtn = screen.getByLabelText('Delete session')
    fireEvent.click(deleteBtn)
    expect(deleteSession).toHaveBeenCalledWith(SESSION_A.id)
  })

  it('delete button click does not trigger selectSession', () => {
    const selectSession = vi.fn()
    const deleteSession = vi.fn()
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_A], selectSession, deleteSession })
    )
    render(<SessionSidebar />)
    const successEl = screen.getByText('2✓')
    const sessionRow = successEl.closest('[style]')
    fireEvent.mouseEnter(sessionRow)
    const deleteBtn = screen.getByLabelText('Delete session')
    // Reset selectSession calls (hovering may have triggered mouseEnter)
    selectSession.mockClear()
    fireEvent.click(deleteBtn)
    // selectSession should not have been called by the click on the delete button
    expect(selectSession).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// Add repo button ("+" next to All Repos)
// ---------------------------------------------------------------------------

describe('SessionSidebar add repo button', () => {
  beforeEach(() => {
    global.fetch = vi.fn(async (url) => {
      const rawUrl = String(url || '')
      if (rawUrl.includes('/api/fs/roots')) {
        return {
          ok: true,
          json: async () => ({
            roots: [
              { name: 'Home', path: '/home/user' },
              { name: 'Temp', path: '/tmp' },
            ],
          }),
        }
      }
      if (rawUrl.includes('/api/fs/list')) {
        const path = decodeURIComponent(rawUrl.split('path=')[1] || '/home/user')
        if (path === '/home/user/repos') {
          return {
            ok: true,
            json: async () => ({
              current_path: '/home/user/repos',
              parent_path: '/home/user',
              directories: [{ name: 'insightmesh', path: '/home/user/repos/insightmesh' }],
            }),
          }
        }
        return {
          ok: true,
          json: async () => ({
            current_path: '/home/user',
            parent_path: '/home',
            directories: [{ name: 'repos', path: '/home/user/repos' }],
          }),
        }
      }
      return { ok: false, json: async () => ({ error: `unexpected url: ${rawUrl}` }) }
    })
  })

  it('renders "+" button with aria-label next to All Repos', () => {
    render(<SessionSidebar />)
    expect(screen.getByLabelText('Add repo')).toBeDefined()
  })

  it('loads browsable folders when "+" is clicked', async () => {
    render(<SessionSidebar />)
    fireEvent.click(screen.getByLabelText('Add repo'))
    await vi.waitFor(() => {
      expect(screen.getByRole('dialog', { name: 'Choose repository folder' })).toBeDefined()
      expect(screen.getByText('Use This Folder')).toBeDefined()
      expect(screen.getByText('repos')).toBeDefined()
      expect(screen.getByText('/home/user')).toBeDefined()
    })
  })

  it('navigates into a child directory and adds current folder', async () => {
    const addRepoByPath = vi.fn().mockResolvedValue({ ok: true })
    mockUseHydraFlow.mockReturnValue(defaultContext({ addRepoByPath }))
    render(<SessionSidebar />)
    fireEvent.click(screen.getByLabelText('Add repo'))
    await vi.waitFor(() => {
      expect(screen.getByText('repos')).toBeDefined()
    })
    fireEvent.click(screen.getByText('repos'))
    await vi.waitFor(() => {
      expect(screen.getByText('/home/user/repos')).toBeDefined()
      expect(screen.getByText('insightmesh')).toBeDefined()
    })
    fireEvent.click(screen.getByText('Use This Folder'))
    await vi.waitFor(() => {
      expect(addRepoByPath).toHaveBeenCalledWith('/home/user/repos')
      expect(screen.queryByText('Use This Folder')).toBeNull()
    })
  })

  it('shows error and keeps panel open when addRepoByPath fails', async () => {
    const addRepoByPath = vi.fn().mockResolvedValue({ ok: false, error: 'not a git repository: /home/user' })
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ addRepoByPath })
    )
    render(<SessionSidebar />)
    fireEvent.click(screen.getByLabelText('Add repo'))
    await vi.waitFor(() => {
      expect(screen.getByText('Use This Folder')).toBeDefined()
      expect(screen.getByText('repos')).toBeDefined()
    })
    fireEvent.click(screen.getByText('Use This Folder'))
    await vi.waitFor(() => {
      expect(screen.getByText('not a git repository: /home/user')).toBeDefined()
      expect(screen.getByText('Use This Folder')).toBeDefined()
    })
  })

  it('shows browse error when filesystem API fails', async () => {
    global.fetch = vi.fn(async (url) => {
      const rawUrl = String(url || '')
      if (rawUrl.includes('/api/fs/roots')) {
        return { ok: false, json: async () => ({ error: 'Failed to load folders' }) }
      }
      return { ok: false, json: async () => ({ error: 'Failed to browse folders' }) }
    })
    render(<SessionSidebar />)
    fireEvent.click(screen.getByLabelText('Add repo'))
    await vi.waitFor(() => {
      expect(screen.getByText('Failed to load folders')).toBeDefined()
    })
  })
})

// ---------------------------------------------------------------------------
// Disconnect repo button ("−" per repo row)
// ---------------------------------------------------------------------------

describe('SessionSidebar disconnect repo button', () => {
  it('renders disconnect button only for supervised repos', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        sessions: [SESSION_A, SESSION_OTHER],
        supervisedRepos: [
          { slug: 'repo', path: 'org/repo', running: false },
          { slug: 'other-repo', path: 'other-org/other-repo', running: false },
        ],
      })
    )
    render(<SessionSidebar />)
    const btns = screen.getAllByLabelText('Disconnect repo')
    expect(btns.length).toBe(2)
  })

  it('does not render disconnect button for session-only repos without supervised entry', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        sessions: [SESSION_A, SESSION_OTHER],
      })
    )
    render(<SessionSidebar />)
    expect(screen.queryByLabelText('Disconnect repo')).toBeNull()
  })

  it('calls removeRepoShortcut when disconnect button is clicked on a stopped repo', () => {
    const removeRepoShortcut = vi.fn()
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        supervisedRepos: [{ ...SUPERVISED_REPO, running: false }],
        removeRepoShortcut,
      })
    )
    render(<SessionSidebar />)
    fireEvent.click(screen.getByLabelText('Disconnect repo'))
    expect(removeRepoShortcut).toHaveBeenCalledWith('demo')
  })

  it('shows confirmation before disconnecting a running repo', () => {
    const removeRepoShortcut = vi.fn()
    window.confirm = vi.fn(() => false)
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        supervisedRepos: [SUPERVISED_REPO],
        runtimes: [{ slug: 'demo', running: true }],
        removeRepoShortcut,
      })
    )
    render(<SessionSidebar />)
    fireEvent.click(screen.getByLabelText('Disconnect repo'))
    expect(window.confirm).toHaveBeenCalled()
    // Declined — should not call removeRepoShortcut
    expect(removeRepoShortcut).not.toHaveBeenCalled()
  })

  it('proceeds with disconnect when running repo confirmation is accepted', () => {
    const removeRepoShortcut = vi.fn()
    window.confirm = vi.fn(() => true)
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        supervisedRepos: [SUPERVISED_REPO],
        runtimes: [{ slug: 'demo', running: true }],
        removeRepoShortcut,
      })
    )
    render(<SessionSidebar />)
    fireEvent.click(screen.getByLabelText('Disconnect repo'))
    expect(window.confirm).toHaveBeenCalled()
    expect(removeRepoShortcut).toHaveBeenCalledWith('demo')
  })

  it('disconnect click does not trigger selectRepo', () => {
    const selectRepo = vi.fn()
    const removeRepoShortcut = vi.fn()
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        supervisedRepos: [{ ...SUPERVISED_REPO, running: false }],
        selectRepo,
        removeRepoShortcut,
      })
    )
    render(<SessionSidebar />)
    selectRepo.mockClear()
    fireEvent.click(screen.getByLabelText('Disconnect repo'))
    expect(selectRepo).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// Per-repo Start/Stop always visible
// ---------------------------------------------------------------------------

describe('SessionSidebar per-repo Start/Stop', () => {
  it('shows Start button for a stopped supervised repo without runtime data', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        supervisedRepos: [{ ...SUPERVISED_REPO, running: false }],
      })
    )
    render(<SessionSidebar />)
    expect(screen.getByTitle('Start this repo runtime')).toBeDefined()
    expect(screen.getByText('Start')).toBeDefined()
  })

  it('shows Stop button for a running supervised repo without runtime data', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        supervisedRepos: [SUPERVISED_REPO],
      })
    )
    render(<SessionSidebar />)
    expect(screen.getByTitle('Stop this repo runtime')).toBeDefined()
    expect(screen.getByText('Stop')).toBeDefined()
  })

  it('shows Start button when runtime data exists and repo is stopped', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        supervisedRepos: [{ ...SUPERVISED_REPO, running: false }],
        runtimes: [{ slug: 'demo', running: false }],
      })
    )
    render(<SessionSidebar />)
    expect(screen.getByText('Start')).toBeDefined()
  })

  it('shows Stop button when runtime data exists and repo is running', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        supervisedRepos: [SUPERVISED_REPO],
        runtimes: [{ slug: 'demo', running: true }],
      })
    )
    render(<SessionSidebar />)
    expect(screen.getByText('Stop')).toBeDefined()
  })

  it('calls startRuntime when Start button is clicked', () => {
    const startRuntime = vi.fn()
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        supervisedRepos: [{ ...SUPERVISED_REPO, running: false }],
        startRuntime,
      })
    )
    render(<SessionSidebar />)
    fireEvent.click(screen.getByText('Start'))
    expect(startRuntime).toHaveBeenCalledWith('demo')
  })

  it('calls stopRuntime when Stop button is clicked', () => {
    const stopRuntime = vi.fn()
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        supervisedRepos: [SUPERVISED_REPO],
        runtimes: [{ slug: 'demo', running: true }],
        stopRuntime,
      })
    )
    render(<SessionSidebar />)
    fireEvent.click(screen.getByText('Stop'))
    expect(stopRuntime).toHaveBeenCalledWith('demo')
  })

  it('Start click does not trigger selectRepo', () => {
    const selectRepo = vi.fn()
    const startRuntime = vi.fn()
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        supervisedRepos: [{ ...SUPERVISED_REPO, running: false }],
        selectRepo,
        startRuntime,
      })
    )
    render(<SessionSidebar />)
    selectRepo.mockClear()
    fireEvent.click(screen.getByText('Start'))
    expect(selectRepo).not.toHaveBeenCalled()
  })

  it('Stop click does not trigger selectRepo', () => {
    const selectRepo = vi.fn()
    const stopRuntime = vi.fn()
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        supervisedRepos: [SUPERVISED_REPO],
        runtimes: [{ slug: 'demo', running: true }],
        selectRepo,
        stopRuntime,
      })
    )
    render(<SessionSidebar />)
    selectRepo.mockClear()
    fireEvent.click(screen.getByText('Stop'))
    expect(selectRepo).not.toHaveBeenCalled()
  })

  it('shows Start button for session-only repo (no supervised entry)', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_A] })
    )
    render(<SessionSidebar />)
    expect(screen.getByText('Start')).toBeDefined()
    expect(screen.getByTitle('Start this repo runtime')).toBeDefined()
  })

  it('session-only repo shows Start but no Disconnect button', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_A] })
    )
    render(<SessionSidebar />)
    expect(screen.getByText('Start')).toBeDefined()
    expect(screen.queryByLabelText('Disconnect repo')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// Path-based repo input
// ---------------------------------------------------------------------------
