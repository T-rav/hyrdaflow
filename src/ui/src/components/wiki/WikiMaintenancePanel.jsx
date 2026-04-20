import React, { useCallback, useEffect, useState } from 'react'
import { theme } from '../../theme'

export function WikiMaintenancePanel({ onAdminAction }) {
  const [status, setStatus] = useState(null)

  const refresh = useCallback(() => {
    fetch('/api/wiki/maintenance/status')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => setStatus(data))
      .catch(() => setStatus(null))
  }, [])

  useEffect(() => {
    refresh()
    const iv = setInterval(refresh, 30_000)
    return () => clearInterval(iv)
  }, [refresh])

  const handleRunNow = async () => {
    await onAdminAction('run-now', {})
    refresh()
  }

  const styles = {
    root: {
      display: 'flex',
      alignItems: 'center',
      gap: 16,
      padding: '8px 16px',
      background: theme.surfaceInset,
      borderTop: `1px solid ${theme.border}`,
      color: theme.text,
      fontSize: 12,
      flexWrap: 'wrap',
    },
    label: {
      color: theme.textMuted,
      textTransform: 'uppercase',
      fontSize: 10,
      letterSpacing: 0.5,
    },
    value: {
      color: theme.textBright,
      fontFamily:
        'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
    },
    prLink: {
      color: theme.accent,
      textDecoration: 'none',
    },
    runBtn: {
      marginLeft: 'auto',
      fontSize: 12,
      padding: '4px 10px',
      borderRadius: 4,
      border: `1px solid ${theme.border}`,
      background: theme.surface,
      color: theme.text,
      cursor: 'pointer',
    },
  }

  const prUrl = status?.open_pr_url
  const queueDepth = status?.queue_depth ?? 0
  const intervalSeconds = status?.interval_seconds ?? '—'

  return (
    <div style={styles.root}>
      <span style={styles.label}>Queue</span>
      <span style={styles.value}>{queueDepth}</span>

      <span style={styles.label}>Open PR</span>
      <span style={styles.value}>
        {prUrl ? (
          <a href={prUrl} target="_blank" rel="noreferrer" style={styles.prLink}>
            {prUrl.split('/').slice(-2).join('/')}
          </a>
        ) : (
          '—'
        )}
      </span>

      <span style={styles.label}>Interval</span>
      <span style={styles.value}>{intervalSeconds}s</span>

      <button type="button" onClick={handleRunNow} style={styles.runBtn}>
        Run now
      </button>
    </div>
  )
}

export default WikiMaintenancePanel
