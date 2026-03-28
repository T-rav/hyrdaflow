import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useReportPoller } from '../useReportPoller'

const API_BASE = ''
const REPORTER_ID = 'test-user-123'

function makeReport(overrides = {}) {
  return {
    id: 'r1',
    reporter_id: REPORTER_ID,
    description: 'Test bug',
    status: 'queued',
    linked_issue_url: '',
    linked_pr_url: '',
    progress_summary: '',
    created_at: '2026-03-28T00:00:00Z',
    updated_at: '2026-03-28T00:00:00Z',
    history: [],
    ...overrides,
  }
}

describe('useReportPoller', () => {
  let fetchMock

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    })
    global.fetch = fetchMock
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches reports on mount', async () => {
    const reports = [makeReport()]
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(reports),
    })

    const { result } = renderHook(() =>
      useReportPoller(API_BASE, REPORTER_ID, { interval: 600_000 })
    )

    await waitFor(() => {
      expect(result.current.reports).toEqual(reports)
    })

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining(`/api/reports?reporter_id=${REPORTER_ID}`)
    )
  })

  it('returns loading=false after fetch completes', async () => {
    const { result } = renderHook(() =>
      useReportPoller(API_BASE, REPORTER_ID, { interval: 600_000 })
    )

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })
  })

  it('polls on interval', async () => {
    const { result } = renderHook(() =>
      useReportPoller(API_BASE, REPORTER_ID, { interval: 50 })
    )

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    // Wait for at least one poll cycle
    await waitFor(
      () => {
        expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(2)
      },
      { timeout: 500 }
    )
  })

  it('refresh() calls refresh endpoint then re-fetches', async () => {
    const { result } = renderHook(() =>
      useReportPoller(API_BASE, REPORTER_ID, { interval: 600_000 })
    )

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    await act(async () => {
      await result.current.refresh()
    })

    const refreshCalls = fetchMock.mock.calls.filter(([url, opts]) =>
      url.includes('/api/reports/refresh') && opts?.method === 'POST'
    )
    expect(refreshCalls.length).toBe(1)
  })

  it('submitReport() posts to /api/report then re-fetches', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: 'queued' }),
    })

    const { result } = renderHook(() =>
      useReportPoller(API_BASE, REPORTER_ID, { interval: 600_000 })
    )

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    await act(async () => {
      await result.current.submitReport({
        description: 'New bug',
        screenshot_base64: '',
        environment: {},
      })
    })

    const submitCalls = fetchMock.mock.calls.filter(([url, opts]) =>
      url.includes('/api/report') && !url.includes('/reports') && opts?.method === 'POST'
    )
    expect(submitCalls.length).toBe(1)
    const body = JSON.parse(submitCalls[0][1].body)
    expect(body.description).toBe('New bug')
    expect(body.reporter_id).toBe(REPORTER_ID)
  })

  it('updateReport() patches and re-fetches', async () => {
    const { result } = renderHook(() =>
      useReportPoller(API_BASE, REPORTER_ID, { interval: 600_000 })
    )

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    await act(async () => {
      await result.current.updateReport('r1', 'cancel', 'no longer needed')
    })

    const patchCalls = fetchMock.mock.calls.filter(([url, opts]) =>
      url.includes('/api/reports/r1') && opts?.method === 'PATCH'
    )
    expect(patchCalls.length).toBe(1)
    const body = JSON.parse(patchCalls[0][1].body)
    expect(body.action).toBe('cancel')
    expect(body.detail).toBe('no longer needed')
    expect(body.reporter_id).toBe(REPORTER_ID)
  })

  it('handles fetch errors gracefully', async () => {
    fetchMock.mockRejectedValue(new Error('Network error'))

    const { result } = renderHook(() =>
      useReportPoller(API_BASE, REPORTER_ID, { interval: 600_000 })
    )

    await waitFor(() => {
      expect(result.current.error).toBeTruthy()
      expect(result.current.loading).toBe(false)
    })
  })

  it('cleans up interval on unmount', async () => {
    const clearSpy = vi.spyOn(global, 'clearInterval')

    const { unmount } = renderHook(() =>
      useReportPoller(API_BASE, REPORTER_ID, { interval: 600_000 })
    )

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })

    unmount()

    expect(clearSpy).toHaveBeenCalled()
    clearSpy.mockRestore()
  })
})
