import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useHITLCorrection } from '../useHITLCorrection'

describe('useHITLCorrection', () => {
  let fetchMock

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({ ok: true })
    global.fetch = fetchMock
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns all four action callbacks on initial render', () => {
    const { result } = renderHook(() => useHITLCorrection())
    expect(typeof result.current.submitCorrection).toBe('function')
    expect(typeof result.current.skipIssue).toBe('function')
    expect(typeof result.current.closeIssue).toBe('function')
    expect(typeof result.current.approveProcess).toBe('function')
  })

  it('submitCorrection POSTs to /api/hitl/{issueNumber}/correct with correction body', async () => {
    const { result } = renderHook(() => useHITLCorrection())

    await act(async () => {
      await result.current.submitCorrection(42, 'Fix the failing tests')
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/hitl/42/correct', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ correction: 'Fix the failing tests' }),
    })
  })

  it('submitCorrection returns true when response is ok', async () => {
    fetchMock.mockResolvedValue({ ok: true })
    const { result } = renderHook(() => useHITLCorrection())

    let returnValue
    await act(async () => {
      returnValue = await result.current.submitCorrection(42, 'some correction')
    })

    expect(returnValue).toBe(true)
  })

  it('submitCorrection returns false when response is not ok', async () => {
    fetchMock.mockResolvedValue({ ok: false })
    const { result } = renderHook(() => useHITLCorrection())

    let returnValue
    await act(async () => {
      returnValue = await result.current.submitCorrection(42, 'some correction')
    })

    expect(returnValue).toBe(false)
  })

  it('skipIssue POSTs to /api/hitl/{issueNumber}/skip with provided reason', async () => {
    const { result } = renderHook(() => useHITLCorrection())

    await act(async () => {
      await result.current.skipIssue(10, 'Not relevant anymore')
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/hitl/10/skip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'Not relevant anymore' }),
    })
  })

  it('skipIssue defaults to "Skipped by operator" when reason is omitted', async () => {
    const { result } = renderHook(() => useHITLCorrection())

    await act(async () => {
      await result.current.skipIssue(10)
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/hitl/10/skip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'Skipped by operator' }),
    })
  })

  it('closeIssue POSTs to /api/hitl/{issueNumber}/close with provided reason', async () => {
    const { result } = renderHook(() => useHITLCorrection())

    await act(async () => {
      await result.current.closeIssue(7, 'Will not fix')
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/hitl/7/close', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'Will not fix' }),
    })
  })

  it('closeIssue defaults to "Closed by operator" when reason is omitted', async () => {
    const { result } = renderHook(() => useHITLCorrection())

    await act(async () => {
      await result.current.closeIssue(7)
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/hitl/7/close', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'Closed by operator' }),
    })
  })

  it('approveProcess POSTs to /api/hitl/{issueNumber}/approve-process with no body', async () => {
    const { result } = renderHook(() => useHITLCorrection())

    await act(async () => {
      await result.current.approveProcess(55)
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/hitl/55/approve-process', {
      method: 'POST',
    })
  })

  it('approveProcess returns false when response is not ok', async () => {
    fetchMock.mockResolvedValue({ ok: false })
    const { result } = renderHook(() => useHITLCorrection())

    let returnValue
    await act(async () => {
      returnValue = await result.current.approveProcess(55)
    })

    expect(returnValue).toBe(false)
  })

  it('callbacks are stable across re-renders (referential equality)', () => {
    const { result, rerender } = renderHook(() => useHITLCorrection())
    const firstRender = { ...result.current }
    rerender()
    expect(result.current.submitCorrection).toBe(firstRender.submitCorrection)
    expect(result.current.skipIssue).toBe(firstRender.skipIssue)
    expect(result.current.closeIssue).toBe(firstRender.closeIssue)
    expect(result.current.approveProcess).toBe(firstRender.approveProcess)
  })
})
