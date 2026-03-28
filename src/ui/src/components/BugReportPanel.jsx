import React, { useState, useCallback, useMemo } from 'react'
import { theme } from '../theme'
import { useReportPoller } from '../hooks/useReportPoller'

const STATUS_CONFIG = [
  { key: 'all', label: 'All' },
  { key: 'queued', label: 'Queued', color: theme.yellow },
  { key: 'in-progress', label: 'In Progress', color: theme.accent },
  { key: 'filed', label: 'Filed', color: theme.purple },
  { key: 'fixed', label: 'Fixed', color: theme.green },
  { key: 'closed', label: 'Closed', color: theme.textMuted },
  { key: 'reopened', label: 'Reopened', color: theme.orange },
]

function extractIssueNumber(url) {
  if (!url) return null
  const m = url.match(/\/issues\/(\d+)/)
  return m ? m[1] : null
}

/**
 * Self-contained bug report panel — designed for extraction as a standalone widget.
 *
 * Props:
 *   apiBaseUrl  — base URL for the HydraFlow API ('' for same-origin)
 *   reporterId  — unique reporter ID for filtering
 *   onOpenReportModal — callback to open the report submission modal
 *   pollInterval — polling interval in ms (default 10s)
 */
export function BugReportPanel({ apiBaseUrl = '', reporterId, onOpenReportModal, pollInterval = 10_000 }) {
  const { reports, loading, error, refresh, updateReport } = useReportPoller(
    apiBaseUrl, reporterId, { interval: pollInterval }
  )

  const [statusFilter, setStatusFilter] = useState('all')
  const [searchText, setSearchText] = useState('')
  const [expandedId, setExpandedId] = useState(null)
  const [reopenText, setReopenText] = useState('')

  const filtered = useMemo(() => {
    let items = reports
    if (statusFilter !== 'all') {
      items = items.filter(r => r.status === statusFilter)
    }
    if (searchText) {
      const lower = searchText.toLowerCase()
      items = items.filter(r => r.description?.toLowerCase().includes(lower))
    }
    return items
  }, [reports, statusFilter, searchText])

  const statusCounts = useMemo(() => {
    const counts = { all: reports.length }
    for (const r of reports) {
      counts[r.status] = (counts[r.status] || 0) + 1
    }
    return counts
  }, [reports])

  const toggleExpand = useCallback((id) => {
    setExpandedId(prev => prev === id ? null : id)
    setReopenText('')
  }, [])

  const handleAction = useCallback((reportId, action, detail = '') => {
    updateReport(reportId, action, detail)
    setReopenText('')
  }, [updateReport])

  if (loading) {
    return <div style={styles.container} data-testid="report-panel-loading">Loading reports...</div>
  }

  return (
    <div style={styles.container}>
      {/* Filter bar */}
      <div style={styles.filterBar}>
        <div style={styles.pills}>
          {STATUS_CONFIG.map(s => {
            const count = statusCounts[s.key] || 0
            const isActive = statusFilter === s.key
            return (
              <button
                key={s.key}
                data-testid={`filter-${s.key}`}
                style={isActive ? { ...styles.pill, ...styles.pillActive } : styles.pill}
                onClick={() => setStatusFilter(s.key)}
              >
                {s.label}{count > 0 ? ` (${count})` : ''}
              </button>
            )
          })}
        </div>
        <div style={styles.searchRow}>
          <input
            data-testid="report-search"
            style={styles.searchInput}
            placeholder="Search descriptions..."
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
          />
          <button style={styles.refreshBtn} onClick={refresh} data-testid="report-refresh-btn">
            Refresh
          </button>
          {onOpenReportModal && (
            <button style={styles.reportBtn} onClick={onOpenReportModal} data-testid="report-bug-btn">
              Report Bug
            </button>
          )}
        </div>
      </div>

      {error && <div style={styles.errorBar}>Error: {error}</div>}

      {/* Table */}
      {filtered.length === 0 ? (
        <div style={styles.empty} data-testid="report-panel-empty">
          <div style={styles.emptyText}>No bug reports{statusFilter !== 'all' ? ` with status "${statusFilter}"` : ''} yet.</div>
          {onOpenReportModal && (
            <button style={styles.reportBtn} onClick={onOpenReportModal}>
              Submit a Bug Report
            </button>
          )}
        </div>
      ) : (
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Status</th>
              <th style={{ ...styles.th, ...styles.thDesc }}>Description</th>
              <th style={styles.th}>Created</th>
              <th style={styles.th}>Issue</th>
              <th style={styles.th} />
            </tr>
          </thead>
          <tbody>
            {filtered.map(report => (
              <ReportRow
                key={report.id}
                report={report}
                expanded={expandedId === report.id}
                onToggle={() => toggleExpand(report.id)}
                onAction={handleAction}
                reopenText={expandedId === report.id ? reopenText : ''}
                onReopenTextChange={setReopenText}
              />
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function ReportRow({ report, expanded, onToggle, onAction, reopenText, onReopenTextChange }) {
  const issueNum = extractIssueNumber(report.linked_issue_url)
  const statusColor = STATUS_CONFIG.find(s => s.key === report.status)?.color || theme.textMuted

  return (
    <>
      <tr style={styles.row}>
        <td style={styles.td}>
          <span style={{ ...styles.statusBadge, color: statusColor, borderColor: statusColor }}>
            {STATUS_CONFIG.find(s => s.key === report.status)?.label || report.status}
          </span>
        </td>
        <td style={{ ...styles.td, ...styles.tdDesc }}>{report.description}</td>
        <td style={styles.td}>
          <span style={styles.dateText}>{new Date(report.created_at).toLocaleDateString()}</span>
        </td>
        <td style={styles.td}>
          {issueNum ? (
            <a href={report.linked_issue_url} target="_blank" rel="noreferrer" style={styles.link}>
              #{issueNum}
            </a>
          ) : (
            <span style={styles.dimText}>—</span>
          )}
        </td>
        <td style={styles.td}>
          <button style={styles.expandBtn} onClick={onToggle} data-testid={`expand-${report.id}`}>
            {expanded ? '▴' : '▾'}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr data-testid={`detail-${report.id}`}>
          <td colSpan={5} style={styles.detailCell}>
            {report.progress_summary && (
              <div style={styles.detailRow}>
                <span style={styles.detailLabel}>Progress:</span> {report.progress_summary}
              </div>
            )}
            {report.linked_issue_url && (
              <div style={styles.detailRow}>
                <span style={styles.detailLabel}>Issue:</span>{' '}
                <a href={report.linked_issue_url} target="_blank" rel="noreferrer" style={styles.link}>
                  {report.linked_issue_url}
                </a>
              </div>
            )}
            {report.linked_pr_url && (
              <div style={styles.detailRow}>
                <span style={styles.detailLabel}>PR:</span>{' '}
                <a href={report.linked_pr_url} target="_blank" rel="noreferrer" style={styles.link}>
                  {report.linked_pr_url}
                </a>
              </div>
            )}

            {/* Timeline */}
            {report.history?.length > 0 && (
              <div style={styles.timeline}>
                <div style={styles.timelineTitle}>Timeline</div>
                {report.history.map((entry, i) => (
                  <div key={i} style={styles.timelineEntry}>
                    <span style={styles.timelineDot} />
                    <span style={styles.timelineAction}>{entry.action}</span>
                    {entry.detail && <span style={styles.timelineDetail}> — {entry.detail}</span>}
                    <span style={styles.timelineTime}>{new Date(entry.timestamp).toLocaleString()}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Actions */}
            {report.status !== 'closed' && (
              <div style={styles.actions}>
                {report.status === 'fixed' && (
                  <button
                    style={styles.confirmBtn}
                    onClick={() => onAction(report.id, 'confirm_fixed', '')}
                    data-testid={`action-confirm-${report.id}`}
                  >
                    Confirm Fixed
                  </button>
                )}
                {report.status !== 'queued' && (
                  <div style={styles.reopenRow}>
                    <input
                      style={styles.reopenInput}
                      value={reopenText}
                      onChange={e => onReopenTextChange(e.target.value)}
                      placeholder="Additional context..."
                      data-testid={`action-reopen-input-${report.id}`}
                    />
                    <button
                      style={styles.reopenBtn}
                      onClick={() => onAction(report.id, 'reopen', reopenText)}
                      data-testid={`action-reopen-${report.id}`}
                    >
                      Reopen
                    </button>
                  </div>
                )}
                <button
                  style={styles.cancelBtn}
                  onClick={() => onAction(report.id, 'cancel', '')}
                  data-testid={`action-cancel-${report.id}`}
                >
                  Cancel
                </button>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

const styles = {
  container: {
    padding: 16,
    color: theme.text,
    fontSize: 12,
  },
  filterBar: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    marginBottom: 16,
  },
  pills: {
    display: 'flex',
    gap: 4,
    flexWrap: 'wrap',
  },
  pill: {
    padding: '4px 10px',
    borderRadius: 12,
    border: `1px solid ${theme.border}`,
    background: 'transparent',
    color: theme.textMuted,
    fontSize: 11,
    fontWeight: 500,
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  pillActive: {
    background: theme.accentSubtle,
    borderColor: theme.accent,
    color: theme.accent,
    fontWeight: 600,
  },
  searchRow: {
    display: 'flex',
    gap: 8,
    alignItems: 'center',
  },
  searchInput: {
    flex: 1,
    padding: '6px 10px',
    borderRadius: 6,
    border: `1px solid ${theme.border}`,
    background: theme.bg,
    color: theme.text,
    fontSize: 12,
  },
  refreshBtn: {
    padding: '6px 12px',
    borderRadius: 6,
    border: `1px solid ${theme.border}`,
    background: 'transparent',
    color: theme.textMuted,
    fontSize: 11,
    fontWeight: 600,
    cursor: 'pointer',
  },
  reportBtn: {
    padding: '6px 14px',
    borderRadius: 6,
    border: 'none',
    background: theme.accent,
    color: theme.white,
    fontSize: 11,
    fontWeight: 600,
    cursor: 'pointer',
  },
  errorBar: {
    padding: '6px 12px',
    background: theme.redSubtle,
    color: theme.red,
    borderRadius: 6,
    fontSize: 11,
    marginBottom: 12,
  },
  empty: {
    textAlign: 'center',
    padding: '40px 0',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 16,
  },
  emptyText: {
    color: theme.textMuted,
    fontSize: 13,
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
  },
  th: {
    textAlign: 'left',
    padding: '8px 12px',
    borderBottom: `1px solid ${theme.border}`,
    color: theme.textMuted,
    fontSize: 10,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  thDesc: {
    width: '50%',
  },
  row: {
    borderBottom: `1px solid ${theme.border}`,
  },
  td: {
    padding: '8px 12px',
    verticalAlign: 'middle',
  },
  tdDesc: {
    maxWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  statusBadge: {
    fontSize: 10,
    fontWeight: 600,
    padding: '2px 8px',
    borderRadius: 999,
    border: '1px solid',
    whiteSpace: 'nowrap',
  },
  dateText: {
    fontSize: 11,
    color: theme.textMuted,
  },
  dimText: {
    color: theme.textMuted,
  },
  link: {
    color: theme.accent,
    textDecoration: 'none',
    fontSize: 11,
  },
  expandBtn: {
    background: 'none',
    border: 'none',
    color: theme.textMuted,
    cursor: 'pointer',
    fontSize: 12,
    padding: '2px 6px',
  },
  detailCell: {
    padding: '8px 12px 16px 24px',
    borderBottom: `1px solid ${theme.border}`,
    background: theme.surfaceInset || theme.bg,
  },
  detailRow: {
    fontSize: 11,
    color: theme.text,
    marginBottom: 4,
  },
  detailLabel: {
    color: theme.textMuted,
    fontWeight: 600,
  },
  timeline: {
    marginTop: 12,
    marginBottom: 12,
  },
  timelineTitle: {
    fontSize: 10,
    fontWeight: 700,
    color: theme.textMuted,
    textTransform: 'uppercase',
    marginBottom: 6,
  },
  timelineEntry: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 6,
    marginBottom: 4,
    fontSize: 11,
  },
  timelineDot: {
    width: 5,
    height: 5,
    borderRadius: '50%',
    background: theme.accent,
    flexShrink: 0,
    marginTop: 4,
  },
  timelineAction: {
    fontWeight: 600,
    color: theme.textBright,
  },
  timelineDetail: {
    color: theme.text,
  },
  timelineTime: {
    color: theme.textMuted,
    fontSize: 9,
    marginLeft: 'auto',
  },
  actions: {
    display: 'flex',
    gap: 8,
    alignItems: 'center',
    flexWrap: 'wrap',
    marginTop: 8,
  },
  confirmBtn: {
    padding: '4px 10px',
    borderRadius: 6,
    border: `1px solid ${theme.green}`,
    background: theme.greenSubtle,
    color: theme.green,
    fontSize: 11,
    fontWeight: 600,
    cursor: 'pointer',
  },
  reopenRow: {
    display: 'flex',
    gap: 4,
    alignItems: 'center',
  },
  reopenInput: {
    padding: '4px 8px',
    borderRadius: 6,
    border: `1px solid ${theme.border}`,
    background: theme.bg,
    color: theme.text,
    fontSize: 11,
    width: 160,
  },
  reopenBtn: {
    padding: '4px 10px',
    borderRadius: 6,
    border: `1px solid ${theme.orange}`,
    background: theme.orangeSubtle,
    color: theme.orange,
    fontSize: 11,
    fontWeight: 600,
    cursor: 'pointer',
  },
  cancelBtn: {
    padding: '4px 10px',
    borderRadius: 6,
    border: `1px solid ${theme.red}`,
    background: theme.redSubtle,
    color: theme.red,
    fontSize: 11,
    fontWeight: 600,
    cursor: 'pointer',
  },
}
