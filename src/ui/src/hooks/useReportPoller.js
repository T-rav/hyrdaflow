import { useState, useEffect, useCallback, useRef } from 'react'

/**
 * Self-contained hook for polling bug report status from a HydraFlow API.
 *
 * Designed for extraction — no dependency on HydraFlowContext or any
 * app-specific provider. Pass `apiBaseUrl` and `reporterId` and it handles
 * all fetching, polling, submission, and action dispatch.
 *
 * @param {string} apiBaseUrl - Base URL for the API ('' for same-origin)
 * @param {string} reporterId - Unique reporter ID for filtering
 * @param {Object} [options]
 * @param {number} [options.interval=10000] - Polling interval in ms
 * @returns {{ reports, loading, error, refresh, submitReport, updateReport }}
 */
export function useReportPoller(apiBaseUrl, reporterId, { interval = 10_000 } = {}) {
  const [reports, setReports] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const intervalRef = useRef(null)

  const fetchReports = useCallback(async () => {
    if (!reporterId) {
      setLoading(false)
      return
    }
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/reports?reporter_id=${encodeURIComponent(reporterId)}`
      )
      if (res.ok) {
        const data = await res.json()
        setReports(Array.isArray(data) ? data : [])
        setError(null)
      }
    } catch (err) {
      setError(err.message || 'Failed to fetch reports')
    } finally {
      setLoading(false)
    }
  }, [apiBaseUrl, reporterId])

  // Fetch on mount + poll on interval
  useEffect(() => {
    fetchReports()
    intervalRef.current = setInterval(fetchReports, interval)
    return () => clearInterval(intervalRef.current)
  }, [fetchReports, interval])

  const refresh = useCallback(async () => {
    if (!reporterId) return
    try {
      await fetch(
        `${apiBaseUrl}/api/reports/refresh?reporter_id=${encodeURIComponent(reporterId)}`,
        { method: 'POST' }
      )
    } catch {
      // Best-effort refresh
    }
    await fetchReports()
  }, [apiBaseUrl, reporterId, fetchReports])

  const submitReport = useCallback(async (data) => {
    const body = { ...data, reporter_id: reporterId }
    try {
      await fetch(`${apiBaseUrl}/api/report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
    } catch {
      // Submission error — will show up on next poll
    }
    await fetchReports()
  }, [apiBaseUrl, reporterId, fetchReports])

  const updateReport = useCallback(async (reportId, action, detail = '') => {
    try {
      await fetch(`${apiBaseUrl}/api/reports/${reportId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, detail, reporter_id: reporterId }),
      })
    } catch {
      // Action error — will show up on next poll
    }
    await fetchReports()
  }, [apiBaseUrl, reporterId, fetchReports])

  return { reports, loading, error, refresh, submitReport, updateReport }
}
