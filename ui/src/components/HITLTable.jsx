import React, { useState } from 'react'
import { theme } from '../theme'
import { PIPELINE_STAGES } from '../constants'
import { useHITLCorrection } from '../hooks/useHITLCorrection'

export function HITLTable({ items, onRefresh }) {
  const [expandedIssue, setExpandedIssue] = useState(null)
  const [corrections, setCorrections] = useState({})
  const [actionLoading, setActionLoading] = useState(null)
  const { submitCorrection, skipIssue, closeIssue, approveAsMemory } = useHITLCorrection()

  const toggleExpand = (issueNum) => {
    setExpandedIssue(prev => prev === issueNum ? null : issueNum)
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
    await skipIssue(issueNum)
    setActionLoading(null)
    setExpandedIssue(null)
    onRefresh()
  }

  const handleClose = async (issueNum) => {
    if (!window.confirm(`Close issue #${issueNum}? This cannot be undone from the dashboard.`)) return
    setActionLoading({ issue: issueNum, action: 'close' })
    await closeIssue(issueNum)
    setActionLoading(null)
    setExpandedIssue(null)
    onRefresh()
  }

  const handleApproveMemory = async (issueNum) => {
    setActionLoading({ issue: issueNum, action: 'approve' })
    await approveAsMemory(issueNum)
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
        <span style={items.length === 0
          ? { ...styles.headerText, color: theme.textMuted }
          : styles.headerText}>
          {items.length === 0
            ? 'HITL'
            : `${items.length} item${items.length !== 1 ? 's' : ''} awaiting action`}
        </span>
        <button onClick={onRefresh} style={styles.refresh}>Refresh</button>
      </div>
      {items.length === 0 ? (
        <div style={styles.empty}>No stuck PRs</div>
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
          {items.map((item) => {
            const isExpanded = expandedIssue === item.issue
            const status = item.status || 'pending'
            return (
              <React.Fragment key={item.issue}>
                <tr
                  onClick={() => toggleExpand(item.issue)}
                  style={{ ...styles.row, ...(isExpanded ? styles.rowExpanded : {}) }}
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
                        </div>
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
  return { bg: theme.orangeSubtle, fg: theme.orange }
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
  refresh: {
    background: theme.surfaceInset, border: `1px solid ${theme.border}`, color: theme.text,
    padding: '4px 12px', borderRadius: 6, cursor: 'pointer', fontSize: 11,
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
  rowExpanded: { background: theme.surfaceInset },
  link: { color: theme.accent, textDecoration: 'none' },
  noPr: { color: theme.textMuted, fontStyle: 'italic' },
  causeText: { fontSize: 11, color: theme.orange, fontWeight: 500 },
  causePlaceholder: { color: theme.textMuted, fontStyle: 'italic' },
  detailCell: { padding: 0, borderBottom: `1px solid ${theme.border}` },
  detailPanel: {
    padding: '12px 16px', background: theme.surface,
    borderTop: `1px solid ${theme.border}`,
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
  approveMemoryBtn: { ...btnBase, background: theme.purple, color: theme.white },
  memoryCauseBadge: { ...badgeBase, background: theme.purpleSubtle, color: theme.purple },
}
