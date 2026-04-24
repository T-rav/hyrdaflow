import { useCallback } from 'react'

export function useHITLCorrection() {
  const submitCorrection = useCallback(async (issueNumber, correction) => {
    const resp = await fetch(`/api/hitl/${issueNumber}/correct`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ correction }),
    })
    return resp.ok
  }, [])

  const skipIssue = useCallback(async (issueNumber, reason) => {
    const resp = await fetch(`/api/hitl/${issueNumber}/skip`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason || 'Skipped by operator' }),
    })
    return resp.ok
  }, [])

  const closeIssue = useCallback(async (issueNumber, reason) => {
    const resp = await fetch(`/api/hitl/${issueNumber}/close`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason || 'Closed by operator' }),
    })
    return resp.ok
  }, [])

  const approveProcess = useCallback(async (issueNumber) => {
    const resp = await fetch(`/api/hitl/${issueNumber}/approve-process`, {
      method: 'POST',
    })
    return resp.ok
  }, [])

  return { submitCorrection, skipIssue, closeIssue, approveProcess }
}
