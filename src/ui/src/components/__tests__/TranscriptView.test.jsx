import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ACTIVE_STATUSES } from '../../constants'

const mockUseHydraFlow = vi.fn()

vi.mock('../../context/HydraFlowContext', () => ({
  useHydraFlow: (...args) => mockUseHydraFlow(...args),
}))

const { TranscriptView } = await import('../TranscriptView')

beforeEach(() => {
  mockUseHydraFlow.mockReturnValue({ backgroundWorkers: [], events: [] })
})

describe('TranscriptView', () => {
  describe('single worker selected', () => {
    it('renders transcript lines for the selected worker', () => {
      const workers = {
        1: { status: 'running', role: 'implementer', branch: 'feat-1', transcript: ['line one', 'line two'] },
      }
      render(<TranscriptView workers={workers} selectedWorker={1} />)
      expect(screen.getByText('line one')).toBeInTheDocument()
      expect(screen.getByText('line two')).toBeInTheDocument()
    })

    it('shows waiting message when selected worker has empty transcript', () => {
      const workers = {
        1: { status: 'running', role: 'implementer', branch: 'feat-1', transcript: [] },
      }
      render(<TranscriptView workers={workers} selectedWorker={1} />)
      expect(screen.getByText('Waiting for output...')).toBeInTheDocument()
    })

    it('shows selected worker header with issue number, role, and branch', () => {
      const workers = {
        1: { status: 'running', role: 'implementer', branch: 'feat-1', transcript: ['hello'] },
      }
      render(<TranscriptView workers={workers} selectedWorker={1} />)
      expect(screen.getByText('#1')).toBeInTheDocument()
      expect(screen.getByText('implementer')).toBeInTheDocument()
      expect(screen.getByText('feat-1')).toBeInTheDocument()
    })

    it('shows line count for selected worker', () => {
      const workers = {
        1: { status: 'running', role: 'implementer', branch: 'feat-1', transcript: ['a', 'b', 'c'] },
      }
      render(<TranscriptView workers={workers} selectedWorker={1} />)
      expect(screen.getByText('3 lines')).toBeInTheDocument()
    })
  })

  describe('combined feed (no worker selected)', () => {
    it('shows waiting message when no workers have transcripts', () => {
      render(<TranscriptView workers={{}} selectedWorker={null} />)
      expect(screen.getByText('Waiting for transcript output...')).toBeInTheDocument()
    })

    it('shows combined feed header with "All Workers" label', () => {
      const workers = {
        1: { status: 'running', role: 'implementer', branch: 'feat-1', transcript: ['hello'] },
      }
      render(<TranscriptView workers={workers} selectedWorker={null} />)
      expect(screen.getByText('All Workers')).toBeInTheDocument()
    })

    it('only shows transcript lines from workers with active statuses', () => {
      const workers = {
        1: { status: 'running', role: 'implementer', branch: 'feat-1', transcript: ['active line'] },
        2: { status: 'done', role: 'implementer', branch: 'feat-2', transcript: ['done line'] },
        3: { status: 'failed', role: 'implementer', branch: 'feat-3', transcript: ['failed line'] },
      }
      render(<TranscriptView workers={workers} selectedWorker={null} />)
      expect(screen.getByText('active line')).toBeInTheDocument()
      expect(screen.queryByText('done line')).toBeNull()
      expect(screen.queryByText('failed line')).toBeNull()
    })

    it('includes all ACTIVE_STATUSES in the combined feed', () => {
      const workers = {}
      ACTIVE_STATUSES.forEach((status, i) => {
        workers[i] = { status, role: 'implementer', branch: `branch-${i}`, transcript: [`line from ${status}`] }
      })
      render(<TranscriptView workers={workers} selectedWorker={null} />)
      ACTIVE_STATUSES.forEach((status) => {
        expect(screen.getByText(`line from ${status}`)).toBeInTheDocument()
      })
    })

    it('excludes queued workers from combined feed', () => {
      const workers = {
        1: { status: 'queued', role: 'implementer', branch: '', transcript: ['queued line'] },
        2: { status: 'running', role: 'implementer', branch: 'feat-2', transcript: ['running line'] },
      }
      render(<TranscriptView workers={workers} selectedWorker={null} />)
      expect(screen.queryByText('queued line')).toBeNull()
      expect(screen.getByText('running line')).toBeInTheDocument()
    })

    it('shows correct line count for filtered active workers only', () => {
      const workers = {
        1: { status: 'running', role: 'implementer', branch: 'feat-1', transcript: ['a', 'b'] },
        2: { status: 'done', role: 'implementer', branch: 'feat-2', transcript: ['c', 'd', 'e'] },
      }
      render(<TranscriptView workers={workers} selectedWorker={null} />)
      // Only 2 lines from the active worker, not 5
      expect(screen.getByText('2 lines')).toBeInTheDocument()
    })

    it('shows waiting message when only inactive workers have transcripts', () => {
      const workers = {
        1: { status: 'done', role: 'implementer', branch: 'feat-1', transcript: ['done line'] },
        2: { status: 'failed', role: 'implementer', branch: 'feat-2', transcript: ['failed line'] },
      }
      render(<TranscriptView workers={workers} selectedWorker={null} />)
      expect(screen.getByText('Waiting for transcript output...')).toBeInTheDocument()
    })

    it('shows role prefix in combined feed lines', () => {
      const workers = {
        1: { status: 'running', role: 'implementer', branch: 'feat-1', transcript: ['hello world'] },
      }
      render(<TranscriptView workers={workers} selectedWorker={null} />)
      expect(screen.getByText('[implementer #1]')).toBeInTheDocument()
    })
  })

  describe('background worker view', () => {
    it('renders bg worker name and status when bg- key selected', () => {
      mockUseHydraFlow.mockReturnValue({
        backgroundWorkers: [
          { name: 'memory_sync', status: 'ok', last_run: '2026-02-20T10:00:00Z', details: {} },
        ],
        events: [],
      })
      render(<TranscriptView workers={{}} selectedWorker="bg-memory_sync" />)
      expect(screen.getByText('Memory Manager')).toBeInTheDocument()
      expect(screen.getByText('ok')).toBeInTheDocument()
    })

    it('renders details dict as key-value pairs', () => {
      mockUseHydraFlow.mockReturnValue({
        backgroundWorkers: [
          { name: 'memory_sync', status: 'ok', last_run: '2026-02-20T10:00:00Z', details: { item_count: 12, digest_chars: 2400 } },
        ],
        events: [],
      })
      render(<TranscriptView workers={{}} selectedWorker="bg-memory_sync" />)
      expect(screen.getByText('item count')).toBeInTheDocument()
      expect(screen.getByText('12')).toBeInTheDocument()
      expect(screen.getByText('digest chars')).toBeInTheDocument()
      expect(screen.getByText('2400')).toBeInTheDocument()
    })

    it('renders last run timestamp', () => {
      mockUseHydraFlow.mockReturnValue({
        backgroundWorkers: [
          { name: 'memory_sync', status: 'ok', last_run: '2026-02-20T10:00:00Z', details: {} },
        ],
        events: [],
      })
      render(<TranscriptView workers={{}} selectedWorker="bg-memory_sync" />)
      // Should show a formatted date, not "never"
      expect(screen.queryByText('never')).not.toBeInTheDocument()
      expect(screen.getByText('Last Run')).toBeInTheDocument()
    })

    it('shows "never" when last_run is null', () => {
      mockUseHydraFlow.mockReturnValue({
        backgroundWorkers: [
          { name: 'memory_sync', status: 'ok', last_run: null, details: {} },
        ],
        events: [],
      })
      render(<TranscriptView workers={{}} selectedWorker="bg-memory_sync" />)
      expect(screen.getByText('never')).toBeInTheDocument()
    })

    it('renders recent background_worker_status events', () => {
      mockUseHydraFlow.mockReturnValue({
        backgroundWorkers: [
          { name: 'memory_sync', status: 'ok', last_run: '2026-02-20T10:00:00Z', details: {} },
        ],
        events: [
          { type: 'background_worker_status', timestamp: '2026-02-20T10:00:00Z', data: { worker: 'memory_sync', status: 'ok', details: { synced: 5 } } },
        ],
      })
      render(<TranscriptView workers={{}} selectedWorker="bg-memory_sync" />)
      expect(screen.getByText('Recent Events')).toBeInTheDocument()
      expect(screen.getByText('synced: 5')).toBeInTheDocument()
    })

    it('shows "No log data available" when worker has no data and no events', () => {
      mockUseHydraFlow.mockReturnValue({
        backgroundWorkers: [],
        events: [],
      })
      render(<TranscriptView workers={{}} selectedWorker="bg-memory_sync" />)
      expect(screen.getByText('No log data available')).toBeInTheDocument()
    })

    it('filters events to only show events for the selected worker', () => {
      mockUseHydraFlow.mockReturnValue({
        backgroundWorkers: [
          { name: 'memory_sync', status: 'ok', last_run: null, details: {} },
        ],
        events: [
          { type: 'background_worker_status', timestamp: '2026-02-20T10:00:00Z', data: { worker: 'memory_sync', status: 'ok', details: { synced: 5 } } },
          { type: 'background_worker_status', timestamp: '2026-02-20T10:01:00Z', data: { worker: 'metrics', status: 'ok', details: { count: 10 } } },
        ],
      })
      render(<TranscriptView workers={{}} selectedWorker="bg-memory_sync" />)
      expect(screen.getByText('synced: 5')).toBeInTheDocument()
      expect(screen.queryByText('count: 10')).not.toBeInTheDocument()
    })
  })
})
