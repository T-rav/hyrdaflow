import React, { useEffect, useRef, useState } from 'react'
import { theme } from '../theme'
import { PIPELINE_STAGES } from '../constants'
import { useHITLCorrection } from '../hooks/useHITLCorrection'

export function HITLTable({ items, onRefresh }) {
  const [expandedIssue, setExpandedIssue] = useState(null)
  const [summaryExpandedIssue, setSummaryExpandedIssue] = useState(null)
  const [summaries, setSummaries] = useState(() =>
    Object.fromEntries(
      (items || []).map(item => [
        item.issue,
        {
          text: item.llmSummary || '',
          updatedAt: item.llmSummaryUpdatedAt || null,
          loading: false,
          error: '',
        },
      ])
    )
  )
  const [corrections, setCorrections] = useState({})
  const [actionLoading, setActionLoading] = useState(null)
  const [actionError, setActionError] = useState({})
  const [closedIssues, setClosedIssues] = useState(() => new Set())
  const [refreshing, setRefreshing] = useState(false)
  const [countdown, setCountdown] = useState(30)
  const onRefreshRef = useRef(onRefresh)
  const { submitCorrection, skipIssue, closeIssue, approveAsMemory, approveProcess } = useHITLCorrection()

  useEffect(() => { onRefreshRef.current = onRefresh }, [onRefresh])

  useEffect(() => {
    const timer = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) {
          onRefreshRef.current()
          return 30
        }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    setRefreshing(false)
    setCountdown(30)
  }, [items])

  useEffect(() => {
    setSummaries(prev => {
      const next = { ...prev }
      for (const item of items || []) {
        if (item.llmSummary) {
          next[item.issue] = {
            text: item.llmSummary,
            updatedAt: item.llmSummaryUpdatedAt || null,
            loading: false,
            error: '',
          }
        } else if (!next[item.issue]) {
          next[item.issue] = {
            text: '',
            updatedAt: null,
            loading: false,
            error: '',
          }
        }
      }
      return next
    })
  }, [items])

  const visibleItems = items.filter(item => !closedIssues.has(item.issue))

  const toggleExpand = (issueNum) => {
    setExpandedIssue(prev => prev === issueNum ? null : issueNum)
  }

  const toggleSummaryExpand = (issueNum) => {
    setSummaryExpandedIssue(prev => prev === issueNum ? null : issueNum)
  }

  const ensureSummary = async (issueNum) => {
    const existing = summaries[issueNum]
    if (existing?.text || existing?.loading) return
    setSummaries(prev => ({
      ...prev,
      [issueNum]: { ...(prev[issueNum] || {}), loading: true, error: '' },
    }))
    try {
      const resp = await fetch(`/api/hitl/${issueNum}/summary`)
      if (!resp.ok) throw new Error(`status ${resp.status}`)
      const payload = await resp.json()
      setSummaries(prev => ({
        ...prev,
        [issueNum]: {
          text: payload.summary || '',
          updatedAt: payload.updated_at || null,
          loading: false,
          error: '',
        },
      }))
    } catch {
      setSummaries(prev => ({
        ...prev,
        [issueNum]: {
          ...(prev[issueNum] || {}),
          loading: false,
          error: 'Could not generate context summary yet.',
        },
      }))
    }
  }

  const toggleExpandAndLoadSummary = (issueNum) => {
    toggleExpand(issueNum)
    setSummaryExpandedIssue(null)
    void ensureSummary(issueNum)
  }

  const handleCorrectionChange = (issueNum, value) => {
    setCorrections(prev => ({ ...prev, [issueNum]: value }))
  }

  const handleRetry = async (issueNum) => {
    const text = (corrections[issueNum] || '').trim()
    if (!text) return
    setActionLoading({ issue: issueNum, action: 'retry' })
    await submitCorrection(issueNum, text)
    setCorrections(prev => ({ ...prev, [issueNum]: '' }))
    setActionLoading(null)
    onRefresh()
  }

  const handleSkip = async (issueNum) => {
    setActionLoading({ issue: issueNum, action: 'skip' })
    setActionError(prev => ({ ...prev, [issueNum]: null }))
    const reason = corrections[issueNum] || ''
    const ok = await skipIssue(issueNum, reason)
    if (!ok) {
      setActionError(prev => ({ ...prev, [issueNum]: 'Skip failed. Try again.' }))
    }
    setActionLoading(null)
    if (ok) setExpandedIssue(null)
    onRefresh()
  }

  const handleClose = async (issueNum) => {
    setActionLoading({ issue: issueNum, action: 'close' })
    setActionError(prev => ({ ...prev, [issueNum]: null }))
    const reason = corrections[issueNum] || ''
    const ok = await closeIssue(issueNum, reason)
    if (ok) {
      setClosedIssues(prev => {
        const next = new Set(prev)
        next.add(issueNum)
        return next
      })
      setExpandedIssue(null)
    } else {
      setActionError(prev => ({ ...prev, [issueNum]: 'Close failed. Try again.' }))
    }
    setActionLoading(null)
    onRefresh()
  }

  const handleApproveMemory = async (issueNum) => {
    setActionLoading({ issue: issueNum, action: 'approve' })
    await approveAsMemory(issueNum)
    setActionLoading(null)
    setExpandedIssue(null)
    onRefresh()
  }

  const handleApproveProcess = async (issueNum) => {
    setActionLoading({ issue: issueNum, action: 'approve-process' })
    await approveProcess(issueNum)
    setActionLoading(null)
    setExpandedIssue(null)
    onRefresh()
  }

  const isActionLoading = (issueNum, action) =>
    actionLoading && actionLoading.issue === issueNum && actionLoading.action === action

  const isAnyActionLoading = (issueNum) =>
    actionLoading && actionLoading.issue === issueNum

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={visibleItems.length === 0
          ? { ...styles.headerText, color: theme.textMuted }
          : styles.headerText}>
          {visibleItems.length === 0
            ? 'HITL'
            : `${visibleItems.length} item${visibleItems.length !== 1 ? 's' : ''} awaiting action`}
        </span>
        <div style={styles.refreshGroup}>
          <button
            onClick={() => { setRefreshing(true); setCountdown(30); onRefresh() }}
            style={styles.refresh}
            disabled={refreshing}
          >
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>
          <span style={styles.countdownHint}>
            {refreshing ? '' : `auto in ${countdown}s`}
          </span>
        </div>
      </div>
      {visibleItems.length === 0 ? (
        <div style={styles.empty}>No stuck issues</div>
      ) : (
      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>Issue</th>
            <th style={styles.th}>Title</th>
            <th style={styles.th}>Cause</th>
            <th style={styles.th}>PR</th>
            <th style={styles.th}>Branch</th>
            <th style={styles.th}>Status</th>
          </tr>
        </thead>
        <tbody>
          {visibleItems.map((item) => {
            const isExpanded = expandedIssue === item.issue
            const status = item.status || 'pending'
            return (
              <React.Fragment key={item.issue}>
                <tr
                  onClick={() => toggleExpandAndLoadSummary(item.issue)}
                  style={isExpanded ? styles.rowActive : styles.row}
                  data-testid={`hitl-row-${item.issue}`}
                >
                  <td style={styles.td}>
                    <a href={item.issueUrl || '#'} target="_blank" rel="noreferrer" style={styles.link}
                       onClick={e => e.stopPropagation()}>
                      #{item.issue}
                    </a>
                  </td>
                  <td style={styles.td}>{item.title}</td>
                  <td style={styles.td}>
                    {item.cause
                      ? <span style={{ ...styles.causeText, color: causeColors(item.cause).fg }}>{item.cause}</span>
                      : <span style={styles.causePlaceholder}>—</span>}
                  </td>
                  <td style={styles.td}>
                    {item.pr > 0 ? (
                      <a href={item.prUrl || '#'} target="_blank" rel="noreferrer" style={styles.link}
                         onClick={e => e.stopPropagation()}>
                        #{item.pr}
                      </a>
                    ) : (
                      <span style={styles.noPr}>No PR</span>
                    )}
                  </td>
                  <td style={styles.td}>{item.branch}</td>
                  <td style={styles.td}>
                    <span style={statusBadgeStyle(status)}>{status}</span>
                  </td>
                </tr>
                {isExpanded && (
                  <tr data-testid={`hitl-detail-${item.issue}`}>
                    <td colSpan={6} style={styles.detailCell}>
                      <div style={styles.detailPanel}>
                        <div style={styles.summarySection}>
                          <div style={styles.summaryHeader}>
                            <span style={styles.summaryTitle}>LLM Context Summary</span>
                            <button
                              style={styles.summaryToggle}
                              onClick={e => { e.stopPropagation(); toggleSummaryExpand(item.issue) }}
                              disabled={!summaries[item.issue]?.text}
                              data-testid={`hitl-summary-toggle-${item.issue}`}
                            >
                              {summaryExpandedIssue === item.issue ? 'Show less' : 'Show more'}
                            </button>
                          </div>
                          <div
                            style={
                              summaryExpandedIssue === item.issue
                                ? styles.summaryExpanded
                                : styles.summaryCollapsed
                            }
                            data-testid={`hitl-summary-${item.issue}`}
                          >
                            {summaries[item.issue]?.loading
                              ? 'Generating summary...'
                              : summaries[item.issue]?.text || summaries[item.issue]?.error || 'Summary pending. Refresh in a few seconds.'}
                          </div>
                        </div>
                        {item.visualEvidence && item.visualEvidence.items && item.visualEvidence.items.length > 0 && (
                          <div style={styles.visualSection} data-testid={`hitl-visual-${item.issue}`}>
                            <div style={styles.visualHeader}>
                              <span style={styles.visualTitle}>Visual Evidence</span>
                              {item.visualEvidence.run_url && (
                                <a
                                  href={item.visualEvidence.run_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  style={styles.link}
                                  onClick={e => e.stopPropagation()}
                                >
                                  Run #{item.visualEvidence.attempt || 1}
                                </a>
                              )}
                            </div>
                            {item.visualEvidence.summary && (
                              <div style={styles.visualSummary}>{item.visualEvidence.summary}</div>
                            )}
                            <div style={styles.visualGrid}>
                              {item.visualEvidence.items.map((ev, idx) => (
                                <div key={`${ev.screen_name}-${idx}`} style={styles.visualCard} data-testid={`hitl-visual-item-${item.issue}-${idx}`}>
                                  <div style={styles.visualCardHeader}>
                                    <span style={styles.visualScreenName}>{ev.screen_name}</span>
                                    <span style={visualStatusStyle(ev.status)}>
                                      {ev.status === 'fail' ? 'FAIL' : ev.status === 'warn' ? 'WARN' : 'PASS'}
                                    </span>
                                  </div>
                                  <div style={styles.visualDiffBar}>
                                    <div style={diffFillStyle(ev.status, ev.diff_percent)} />
                                  </div>
                                  <span style={styles.visualDiffLabel}>{ev.diff_percent.toFixed(1)}% diff</span>
                                  <div style={styles.visualLinks}>
                                    {ev.baseline_url && <a href={ev.baseline_url} target="_blank" rel="noreferrer" style={styles.link} onClick={e => e.stopPropagation()}>Baseline</a>}
                                    {ev.actual_url && <a href={ev.actual_url} target="_blank" rel="noreferrer" style={styles.link} onClick={e => e.stopPropagation()}>Actual</a>}
                                    {ev.diff_url && <a href={ev.diff_url} target="_blank" rel="noreferrer" style={styles.link} onClick={e => e.stopPropagation()}>Diff</a>}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                        {item.cause && (
                          <div style={causeBadgeStyle(item)} data-testid={`hitl-cause-${item.issue}`}>
                            Cause: {item.cause}
                          </div>
                        )}
                        <textarea
                          style={styles.textarea}
                          placeholder="Provide correction guidance..."
                          value={corrections[item.issue] || ''}
                          onChange={e => handleCorrectionChange(item.issue, e.target.value)}
                          onClick={e => e.stopPropagation()}
                          data-testid={`hitl-textarea-${item.issue}`}
                        />
                        <div style={styles.actions}>
                          <button
                            style={styles.retryBtn}
                            disabled={!(corrections[item.issue] || '').trim() || isAnyActionLoading(item.issue)}
                            onClick={e => { e.stopPropagation(); handleRetry(item.issue) }}
                            data-testid={`hitl-retry-${item.issue}`}
                          >
                            {isActionLoading(item.issue, 'retry') ? 'Processing...' : 'Retry with guidance'}
                          </button>
                          <button
                            style={styles.skipBtn}
                            disabled={isAnyActionLoading(item.issue)}
                            onClick={e => { e.stopPropagation(); handleSkip(item.issue) }}
                            data-testid={`hitl-skip-${item.issue}`}
                          >
                            {isActionLoading(item.issue, 'skip') ? 'Skipping...' : 'Skip'}
                          </button>
                          <button
                            style={styles.closeBtn}
                            disabled={isAnyActionLoading(item.issue)}
                            onClick={e => { e.stopPropagation(); handleClose(item.issue) }}
                            data-testid={`hitl-close-${item.issue}`}
                          >
                            {isActionLoading(item.issue, 'close') ? 'Closing...' : 'Close issue'}
                          </button>
                          {item.isMemorySuggestion && (
                            <button
                              style={styles.approveMemoryBtn}
                              disabled={isAnyActionLoading(item.issue)}
                              onClick={e => { e.stopPropagation(); handleApproveMemory(item.issue) }}
                              data-testid={`hitl-approve-memory-${item.issue}`}
                            >
                              {isActionLoading(item.issue, 'approve') ? 'Approving...' : 'Approve as Memory'}
                            </button>
                          )}
                          {item.issueTypeReview && (
                            <button
                              style={styles.approveProcessBtn}
                              disabled={isAnyActionLoading(item.issue)}
                              onClick={e => { e.stopPropagation(); handleApproveProcess(item.issue) }}
                              data-testid={`hitl-approve-process-${item.issue}`}
                            >
                              {isActionLoading(item.issue, 'approve-process') ? 'Approving...' : 'Approve'}
                            </button>
                          )}
                        </div>
                        {actionError[item.issue] && (
                          <div style={styles.actionError}>{actionError[item.issue]}</div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            )
          })}
        </tbody>
      </table>
      )}
    </div>
  )
}

const originColors = Object.fromEntries(
  PIPELINE_STAGES
    .filter(s => s.key !== 'merged')
    .map(s => [`from ${s.key}`, { bg: s.subtleColor, fg: s.color }])
)

function statusBadgeStyle(status) {
  const colors = {
    pending: { bg: theme.yellowSubtle, fg: theme.yellow },
    processing: { bg: theme.accentSubtle, fg: theme.accent },
    resolved: { bg: theme.greenSubtle, fg: theme.green },
    approval: { bg: theme.purpleSubtle, fg: theme.purple },
    ...originColors,
  }
  const { bg, fg } = colors[status] || colors.pending
  return {
    fontSize: 11, padding: '2px 8px', borderRadius: 8, fontWeight: 600,
    background: bg, color: fg,
  }
}

function causeColors(cause) {
  if (!cause) return { bg: theme.orangeSubtle, fg: theme.orange }
  const lower = cause.toLowerCase()
  if (lower.includes('proposal') || lower.includes('improve')) {
    return { bg: theme.purpleSubtle, fg: theme.purple }
  }
  if (lower.includes('triage') || lower.includes('insufficient')) {
    return { bg: theme.yellowSubtle, fg: theme.yellow }
  }
  if (lower.includes('visual') || lower.includes('screenshot')) {
    return { bg: theme.redSubtle, fg: theme.red }
  }
  return { bg: theme.orangeSubtle, fg: theme.orange }
}

function visualStatusStyle(status) {
  const colors = {
    fail: { bg: theme.redSubtle, fg: theme.red },
    warn: { bg: theme.yellowSubtle, fg: theme.yellow },
    pass: { bg: theme.greenSubtle, fg: theme.green },
  }
  const { bg, fg } = colors[status] || colors.fail
  return {
    fontSize: 10, padding: '1px 6px', borderRadius: 4, fontWeight: 700,
    background: bg, color: fg,
  }
}

const diffFillBg = { fail: theme.red, warn: theme.yellow, pass: theme.green }

function diffFillStyle(status, diffPercent) {
  return {
    height: '100%', borderRadius: 2, transition: 'width 0.3s',
    width: `${Math.min(diffPercent, 100)}%`,
    background: diffFillBg[status] || theme.red,
  }
}

function causeBadgeStyle(item) {
  if (item.isMemorySuggestion) return styles.memoryCauseBadge
  const colors = causeColors(item.cause)
  return { ...badgeBase, background: colors.bg, color: colors.fg }
}

const badgeBase = {
  display: 'inline-block', marginBottom: 8,
  padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600,
}

const btnBase = {
  padding: '6px 14px', border: 'none', borderRadius: 6,
  fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', fontSize: 12,
}

const styles = {
  container: { padding: 12, overflowX: 'auto' },
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    marginBottom: 12,
  },
  headerText: { color: theme.red, fontWeight: 600, fontSize: 13 },
  refreshGroup: {
    display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2,
  },
  refresh: {
    background: theme.surfaceInset, border: `1px solid ${theme.border}`, color: theme.text,
    padding: '4px 12px', borderRadius: 6, cursor: 'pointer', fontSize: 11,
  },
  countdownHint: {
    fontSize: 10, color: theme.textMuted, lineHeight: 1,
  },
  empty: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    height: 200, color: theme.textMuted, fontSize: 13,
  },
  table: { width: '100%', minWidth: 600, borderCollapse: 'collapse', fontSize: 12 },
  th: {
    textAlign: 'left', padding: 8, borderBottom: `1px solid ${theme.border}`,
    color: theme.textMuted, fontSize: 11,
  },
  td: { padding: 8, borderBottom: `1px solid ${theme.border}` },
  row: { cursor: 'pointer' },
  rowActive: { cursor: 'pointer', background: theme.surfaceInset },
  link: { color: theme.accent, textDecoration: 'none' },
  noPr: { color: theme.textMuted, fontStyle: 'italic' },
  causeText: { fontSize: 11, color: theme.orange, fontWeight: 500 },
  causePlaceholder: { color: theme.textMuted, fontStyle: 'italic' },
  detailCell: { padding: 0, borderBottom: `1px solid ${theme.border}` },
  detailPanel: {
    padding: '12px 16px', background: theme.surface,
    borderTop: `1px solid ${theme.border}`,
  },
  summarySection: {
    marginBottom: 10,
    padding: '8px 10px',
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    background: theme.surfaceInset,
  },
  summaryHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  summaryTitle: {
    fontSize: 11,
    fontWeight: 700,
    color: theme.textMuted,
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
  },
  summaryToggle: {
    border: `1px solid ${theme.border}`,
    background: theme.surface,
    color: theme.accent,
    borderRadius: 6,
    padding: '2px 8px',
    fontSize: 11,
    cursor: 'pointer',
  },
  summaryCollapsed: {
    whiteSpace: 'pre-wrap',
    lineHeight: '18px',
    maxHeight: '36px',
    overflow: 'hidden',
    color: theme.text,
    fontSize: 12,
  },
  summaryExpanded: {
    whiteSpace: 'pre-wrap',
    lineHeight: '18px',
    maxHeight: '90px',
    overflowY: 'auto',
    color: theme.text,
    fontSize: 12,
    paddingRight: 4,
  },
  causeBadge: { ...badgeBase, background: theme.orangeSubtle, color: theme.orange },
  textarea: {
    width: '100%', minHeight: 60, padding: 8,
    background: theme.bg, border: `1px solid ${theme.border}`,
    borderRadius: 6, color: theme.text, fontFamily: 'inherit', fontSize: 12,
    resize: 'vertical', boxSizing: 'border-box',
  },
  actions: { display: 'flex', gap: 8, marginTop: 8 },
  retryBtn: { ...btnBase, background: theme.btnGreen, color: theme.white },
  skipBtn: { ...btnBase, background: theme.surfaceInset, color: theme.text, border: `1px solid ${theme.border}` },
  closeBtn: { ...btnBase, background: theme.btnRed, color: theme.white },
  actionError: { marginTop: 6, fontSize: 12, color: theme.red || '#c0392b' },
  approveMemoryBtn: { ...btnBase, background: theme.purple, color: theme.white },
  approveProcessBtn: { ...btnBase, background: theme.btnGreen, color: theme.white },
  memoryCauseBadge: { ...badgeBase, background: theme.purpleSubtle, color: theme.purple },
  visualSection: {
    marginBottom: 10, padding: '8px 10px',
    border: `1px solid ${theme.border}`, borderRadius: 6,
    background: theme.surfaceInset,
  },
  visualHeader: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    marginBottom: 6,
  },
  visualTitle: {
    fontSize: 11, fontWeight: 700, color: theme.textMuted,
    letterSpacing: '0.04em', textTransform: 'uppercase',
  },
  visualSummary: {
    fontSize: 12, color: theme.text, marginBottom: 8,
    lineHeight: '18px',
  },
  visualGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
    gap: 8,
  },
  visualCard: {
    padding: 8, border: `1px solid ${theme.border}`, borderRadius: 6,
    background: theme.surface,
  },
  visualCardHeader: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    marginBottom: 4,
  },
  visualScreenName: { fontSize: 11, fontWeight: 600, color: theme.text },
  visualDiffBar: {
    height: 4, borderRadius: 2, background: theme.surfaceInset,
    marginBottom: 4, overflow: 'hidden',
  },
  visualDiffLabel: { fontSize: 10, color: theme.textMuted },
  visualLinks: { display: 'flex', gap: 8, marginTop: 4, fontSize: 11 },
}
