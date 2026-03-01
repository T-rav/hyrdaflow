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

  it('does not render add/remove repo action buttons', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({ sessions: [SESSION_A] })
    )
    render(<SessionSidebar />)
    expect(screen.queryByLabelText(/Add repo/)).toBeNull()
    expect(screen.queryByLabelText(/Remove repo/)).toBeNull()
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
    expect(screen.getByText('RUNNING')).toBeDefined()
  })

  it('shows STOPPED status for non-running supervised repo', () => {
    mockUseHydraFlow.mockReturnValue(
      defaultContext({
        supervisedRepos: [{ ...SUPERVISED_REPO, running: false }],
      })
    )
    render(<SessionSidebar />)
    expect(screen.getByText('STOPPED')).toBeDefined()
    expect(screen.queryByLabelText(/Add repo/)).toBeNull()
    expect(screen.queryByLabelText(/Remove repo/)).toBeNull()
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
