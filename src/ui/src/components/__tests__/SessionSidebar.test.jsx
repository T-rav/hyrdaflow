import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'

const mockContext = {
  sessions: [],
  currentSessionId: null,
  selectedRepoSlug: null,
  stageStatus: null,
  orchestratorStatus: 'stopped',
  selectRepo: vi.fn(),
  supervisedRepos: [],
  runtimes: [],
  startRuntime: vi.fn(),
  stopRuntime: vi.fn(),
  removeRepoShortcut: vi.fn(),
}

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: () => mockContext,
}))

const { SessionSidebar } = await import('../SessionSidebar')

describe('SessionSidebar last-run summary', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-22T12:00:00Z'))
    mockContext.sessions = []
    mockContext.supervisedRepos = []
    mockContext.runtimes = []
    mockContext.orchestratorStatus = 'stopped'
    mockContext.stageStatus = null
    mockContext.currentSessionId = null
  })
  afterEach(() => { vi.useRealTimers() })

  it('shows "never run" for a repo with no sessions', () => {
    mockContext.supervisedRepos = [{ slug: 'owner/alpha', path: '/p/alpha', running: false }]
    render(<SessionSidebar />)
    expect(screen.getByText(/never run/i)).toBeInTheDocument()
  })

  it('shows "ran Xago · Yduration · N ✓ M ✗" for a completed session with failures', () => {
    mockContext.supervisedRepos = [{ slug: 'owner/beta', path: '/p/beta', running: false }]
    mockContext.sessions = [{
      id: 'owner-beta-20260422T090000',
      repo: 'owner/beta',
      started_at: '2026-04-22T09:00:00Z',
      ended_at: '2026-04-22T09:42:00Z',
      status: 'completed',
      issues_succeeded: 12,
      issues_failed: 2,
      issues_processed: [],
    }]
    render(<SessionSidebar />)
    expect(screen.getByText(/ran 2h ago · 42min · 12 ✓ 2 ✗/)).toBeInTheDocument()
  })

  it('omits zero counts for a clean completed session', () => {
    mockContext.supervisedRepos = [{ slug: 'owner/gamma', path: '/p/gamma', running: false }]
    mockContext.sessions = [{
      id: 'owner-gamma-20260422T103000',
      repo: 'owner/gamma',
      started_at: '2026-04-22T10:30:00Z',
      ended_at: '2026-04-22T11:00:00Z',
      status: 'completed',
      issues_succeeded: 0,
      issues_failed: 0,
      issues_processed: [],
    }]
    render(<SessionSidebar />)
    expect(screen.getByText(/ran 1h ago · 30min$/)).toBeInTheDocument()
    expect(screen.queryByText(/✓|✗/)).toBeNull()
  })

  it('shows "running · duration · N ✓" when session is active and runtime is running', () => {
    mockContext.orchestratorStatus = 'running'
    mockContext.supervisedRepos = [{ slug: 'owner/delta', path: '/p/delta', running: true }]
    mockContext.runtimes = [{ slug: 'owner/delta', running: true }]
    mockContext.currentSessionId = 'owner-delta-20260422T115200'
    mockContext.stageStatus = { workload: { done: 5, failed: 0 } }
    mockContext.sessions = [{
      id: 'owner-delta-20260422T115200',
      repo: 'owner/delta',
      started_at: '2026-04-22T11:52:00Z',
      ended_at: null,
      status: 'active',
      issues_succeeded: 0,
      issues_failed: 0,
      issues_processed: [],
    }]
    render(<SessionSidebar />)
    expect(screen.getByText(/running · 8min · 5 ✓/)).toBeInTheDocument()
  })

  it('shows "last run ended" for an ACTIVE session whose runtime is stopped', () => {
    mockContext.orchestratorStatus = 'stopped'
    mockContext.supervisedRepos = [{ slug: 'owner/eps', path: '/p/eps', running: false }]
    mockContext.runtimes = [{ slug: 'owner/eps', running: false }]
    mockContext.sessions = [{
      id: 'owner-eps-20260422T080000',
      repo: 'owner/eps',
      started_at: '2026-04-22T08:00:00Z',
      ended_at: null,
      status: 'active',
      issues_succeeded: 0,
      issues_failed: 0,
      issues_processed: [],
    }]
    render(<SessionSidebar />)
    expect(screen.getByText(/last run ended — 4h ago/)).toBeInTheDocument()
  })

  it('picks the latest session when the repo has multiple', () => {
    mockContext.supervisedRepos = [{ slug: 'owner/zeta', path: '/p/zeta', running: false }]
    mockContext.sessions = [
      {
        id: 'old',
        repo: 'owner/zeta',
        started_at: '2026-04-20T09:00:00Z',
        ended_at: '2026-04-20T09:05:00Z',
        status: 'completed',
        issues_succeeded: 1,
        issues_failed: 0,
        issues_processed: [],
      },
      {
        id: 'new',
        repo: 'owner/zeta',
        started_at: '2026-04-22T11:00:00Z',
        ended_at: '2026-04-22T11:10:00Z',
        status: 'completed',
        issues_succeeded: 4,
        issues_failed: 0,
        issues_processed: [],
      },
    ]
    render(<SessionSidebar />)
    expect(screen.getByText(/ran 50m ago · 10min · 4 ✓/)).toBeInTheDocument()
    expect(screen.queryByText(/· 1 ✓/)).toBeNull()
  })
})
