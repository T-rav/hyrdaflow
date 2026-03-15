import React, { useState, useCallback } from 'react'
import { theme } from '../theme'

const STATUS_COLORS = {
  'queued': theme.yellow,
  'in-progress': theme.accent,
  'filed': theme.purple,
  'fixed': theme.green,
  'closed': theme.textMuted,
  'reopened': theme.orange,
}

const STATUS_LABELS = {
  'queued': 'Queued',
  'in-progress': 'In Progress',
  'filed': 'Issue Filed',
  'fixed': 'Fixed',
  'closed': 'Closed',
  'reopened': 'Reopened',
}

export function BugReportTracker({ isOpen, onClose, reports, onAction, onRefresh }) {
  const [expandedId, setExpandedId] = useState(null)
  const [reopenText, setReopenText] = useState('')

  const toggleExpand = useCallback((id) => {
    setExpandedId((prev) => (prev === id ? null : id))
    setReopenText('')
  }, [])

  const handleAction = useCallback((reportId, action, detail) => {
    if (onAction) onAction(reportId, action, detail)
    setReopenText('')
  }, [onAction])

  if (!isOpen) return null

  return (
    <div style={styles.overlay} onClick={onClose} data-testid="tracker-overlay">
      <div style={styles.modal} onClick={(e) => e.stopPropagation()} data-testid="tracker-modal">
        <div style={styles.header}>
          <span style={styles.title}>Bug Report Tracker</span>
          <div style={styles.headerActions}>
            {onRefresh && (
              <button
                style={styles.refreshBtn}
                onClick={onRefresh}
                aria-label="Refresh statuses"
                data-testid="tracker-refresh"
              >
                Refresh
              </button>
            )}
            <button
              style={styles.closeBtn}
              onClick={onClose}
              aria-label="Close tracker"
              data-testid="tracker-close"
            >
              ×
            </button>
          </div>
        </div>
        <div style={styles.body}>
          {reports.length === 0 ? (
            <div style={styles.empty} data-testid="tracker-empty">
              No bug reports submitted yet.
            </div>
          ) : (
            reports.map((report) => (
              <div key={report.id} style={styles.reportCard} data-testid={`tracker-report-${report.id}`}>
                <div style={styles.reportHeader} onClick={() => toggleExpand(report.id)}>
                  <div style={styles.reportInfo}>
                    <span
                      style={{
                        ...styles.statusBadge,
                        color: STATUS_COLORS[report.status] || theme.textMuted,
                        borderColor: STATUS_COLORS[report.status] || theme.border,
                      }}
                      data-testid={`tracker-status-${report.id}`}
                    >
                      {STATUS_LABELS[report.status] || report.status}
                    </span>
                    <span style={styles.reportDesc}>{report.description}</span>
                  </div>
                  <span style={styles.reportTime}>
                    {new Date(report.created_at).toLocaleDateString()}
                  </span>
                </div>

                {expandedId === report.id && (
                  <div style={styles.expandedSection} data-testid={`tracker-expanded-${report.id}`}>
                    {report.progress_summary && (
                      <div style={styles.progressRow}>
                        <span style={styles.progressLabel}>Progress:</span>
                        <span style={styles.progressText}>{report.progress_summary}</span>
                      </div>
                    )}

                    {report.linked_issue_url && (
                      <div style={styles.linkRow}>
                        <span style={styles.progressLabel}>Issue:</span>
                        <a href={report.linked_issue_url} target="_blank" rel="noopener noreferrer" style={styles.link}>
                          {report.linked_issue_url}
                        </a>
                      </div>
                    )}

                    {report.linked_pr_url && (
                      <div style={styles.linkRow}>
                        <span style={styles.progressLabel}>PR:</span>
                        <a href={report.linked_pr_url} target="_blank" rel="noopener noreferrer" style={styles.link}>
                          {report.linked_pr_url}
                        </a>
                      </div>
                    )}

                    {/* Timeline */}
                    {report.history && report.history.length > 0 && (
                      <div style={styles.timeline} data-testid={`tracker-history-${report.id}`}>
                        <span style={styles.timelineTitle}>History</span>
                        {report.history.map((entry, idx) => (
                          <div key={idx} style={styles.timelineEntry}>
                            <span style={styles.timelineDot} />
                            <div style={styles.timelineContent}>
                              <span style={styles.timelineAction}>{entry.action}</span>
                              {entry.detail && (
                                <span style={styles.timelineDetail}>{entry.detail}</span>
                              )}
                              <span style={styles.timelineTime}>
                                {new Date(entry.timestamp).toLocaleString()}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Actions */}
                    {report.status !== 'closed' && (
                      <div style={styles.actions} data-testid={`tracker-actions-${report.id}`}>
                        {report.status === 'fixed' && (
                          <button
                            style={styles.confirmBtn}
                            onClick={() => handleAction(report.id, 'confirm_fixed', '')}
                            data-testid={`tracker-confirm-${report.id}`}
                          >
                            Confirm Fixed
                          </button>
                        )}
                        {report.status !== 'queued' && (
                          <>
                            <div style={styles.reopenRow}>
                              <input
                                style={styles.reopenInput}
                                value={reopenText}
                                onChange={(e) => setReopenText(e.target.value)}
                                placeholder="Additional context..."
                                data-testid={`tracker-reopen-input-${report.id}`}
                              />
                              <button
                                style={styles.reopenBtn}
                                onClick={() => handleAction(report.id, 'reopen', reopenText)}
                                data-testid={`tracker-reopen-${report.id}`}
                              >
                                Reopen
                              </button>
                            </div>
                          </>
                        )}
                        <button
                          style={styles.cancelBtn}
                          onClick={() => handleAction(report.id, 'cancel', '')}
                          data-testid={`tracker-cancel-${report.id}`}
                        >
                          Cancel Report
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

const styles = {
  overlay: {
    position: 'fixed',
    inset: 0,
    background: theme.overlay,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
  },
  modal: {
    background: theme.surface,
    border: `1px solid ${theme.border}`,
    borderRadius: 12,
    width: 560,
    maxWidth: '90vw',
    maxHeight: '80vh',
    display: 'flex',
    flexDirection: 'column',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '16px 20px',
    borderBottom: `1px solid ${theme.border}`,
  },
  title: {
    fontSize: 14,
    fontWeight: 700,
    color: theme.textBright,
  },
  headerActions: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  refreshBtn: {
    padding: '4px 10px',
    borderRadius: 6,
    border: `1px solid ${theme.accent}`,
    background: theme.accentSubtle,
    color: theme.accent,
    fontSize: 11,
    fontWeight: 600,
    cursor: 'pointer',
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    color: theme.textMuted,
    fontSize: 18,
    cursor: 'pointer',
    padding: 4,
  },
  body: {
    padding: 16,
    overflowY: 'auto',
    flex: 1,
  },
  empty: {
    color: theme.textMuted,
    fontSize: 13,
    textAlign: 'center',
    padding: '32px 0',
  },
  reportCard: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    marginBottom: 8,
    background: theme.bg,
  },
  reportHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 12px',
    cursor: 'pointer',
  },
  reportInfo: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    flex: 1,
    minWidth: 0,
  },
  statusBadge: {
    fontSize: 10,
    fontWeight: 600,
    padding: '2px 8px',
    borderRadius: 999,
    border: '1px solid',
    whiteSpace: 'nowrap',
    flexShrink: 0,
  },
  reportDesc: {
    fontSize: 12,
    color: theme.text,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  reportTime: {
    fontSize: 10,
    color: theme.textMuted,
    whiteSpace: 'nowrap',
    marginLeft: 8,
    flexShrink: 0,
  },
  expandedSection: {
    padding: '0 12px 12px',
    borderTop: `1px solid ${theme.border}`,
  },
  progressRow: {
    display: 'flex',
    gap: 8,
    marginTop: 8,
    fontSize: 11,
  },
  progressLabel: {
    color: theme.textMuted,
    fontWeight: 600,
    flexShrink: 0,
  },
  progressText: {
    color: theme.text,
  },
  linkRow: {
    display: 'flex',
    gap: 8,
    marginTop: 4,
    fontSize: 11,
  },
  link: {
    color: theme.accent,
    textDecoration: 'none',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  timeline: {
    marginTop: 12,
  },
  timelineTitle: {
    fontSize: 11,
    fontWeight: 700,
    color: theme.textMuted,
    marginBottom: 6,
    display: 'block',
  },
  timelineEntry: {
    display: 'flex',
    gap: 8,
    alignItems: 'flex-start',
    marginBottom: 6,
  },
  timelineDot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    background: theme.accent,
    marginTop: 5,
    flexShrink: 0,
  },
  timelineContent: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
  },
  timelineAction: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.textBright,
  },
  timelineDetail: {
    fontSize: 10,
    color: theme.text,
  },
  timelineTime: {
    fontSize: 9,
    color: theme.textMuted,
  },
  actions: {
    marginTop: 12,
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
    alignItems: 'center',
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
