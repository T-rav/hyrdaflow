import React from 'react'
import { theme } from '../theme'
import { BACKGROUND_WORKERS } from '../constants'
import { useHydraFlow } from '../context/HydraFlowContext'

/**
 * Keys of caretaker workers — maintenance and operational background loops.
 * Descriptions and labels come from BACKGROUND_WORKERS in constants.js (DRY).
 */
const CARETAKER_KEYS = new Set([
  'stale_issue_gc', 'ci_monitor', 'bot_pr', 'worktree_gc',
  'health_monitor', 'epic_sweeper', 'security_patch', 'code_grooming',
])

const CARETAKER_WORKERS = BACKGROUND_WORKERS.filter(w => CARETAKER_KEYS.has(w.key))

function relativeTime(isoString) {
  if (!isoString) return 'never'
  const diff = Date.now() - new Date(isoString).getTime()
  const seconds = Math.floor(diff / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function statusColor(status) {
  if (status === 'ok') return theme.green
  if (status === 'error') return theme.red
  return theme.textInactive
}

export function CaretakerPanel() {
  const { backgroundWorkers = [], toggleBgWorker, triggerBgWorker } = useHydraFlow()

  const workerMap = new Map(backgroundWorkers.map(w => [w.name, w]))
  const caretakerWorkers = CARETAKER_WORKERS.map(def => ({
    ...def,
    worker: workerMap.get(def.key),
  }))

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.title}>Caretaker Workers</span>
        <span style={styles.subtitle}>Proactive maintenance loops</span>
      </div>
      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>Status</th>
            <th style={{ ...styles.th, width: '30%' }}>Worker</th>
            <th style={styles.th}>Last Run</th>
            <th style={styles.th}>Enabled</th>
            <th style={styles.th} />
          </tr>
        </thead>
        <tbody>
          {caretakerWorkers.map(({ key, label, description, worker }) => {
            const status = worker?.status || 'disabled'
            const enabled = worker?.enabled === true
            const lastRun = worker?.last_run

            return (
              <tr key={key} style={styles.row}>
                <td style={styles.td}>
                  <span
                    style={{ ...styles.dot, background: statusColor(status) }}
                    data-testid={`caretaker-status-${key}`}
                    title={status}
                  />
                </td>
                <td style={styles.td}>
                  <div style={styles.workerInfo}>
                    <span style={styles.workerName}>{label}</span>
                    <span style={styles.workerDesc}>{description}</span>
                  </div>
                </td>
                <td style={styles.td}>
                  <span style={styles.timeText}>{relativeTime(lastRun)}</span>
                </td>
                <td style={styles.td}>
                  <button
                    style={enabled ? styles.toggleOn : styles.toggleOff}
                    onClick={() => toggleBgWorker(key)}
                    data-testid={`caretaker-toggle-${key}`}
                    title={enabled ? 'Click to disable' : 'Click to enable'}
                  >
                    {enabled ? 'ON' : 'OFF'}
                  </button>
                </td>
                <td style={styles.td}>
                  <button
                    style={styles.triggerBtn}
                    onClick={() => triggerBgWorker(key)}
                    data-testid={`caretaker-trigger-${key}`}
                    title="Run now"
                  >
                    Run
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

const styles = {
  container: {
    padding: 16,
    color: theme.text,
  },
  header: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 12,
    marginBottom: 16,
  },
  title: {
    fontSize: 14,
    fontWeight: 700,
    color: theme.textBright,
  },
  subtitle: {
    fontSize: 11,
    color: theme.textMuted,
  },
  empty: {
    textAlign: 'center',
    padding: '40px 0',
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
  row: {
    borderBottom: `1px solid ${theme.border}`,
  },
  td: {
    padding: '10px 12px',
    verticalAlign: 'middle',
  },
  dot: {
    display: 'inline-block',
    width: 8,
    height: 8,
    borderRadius: '50%',
  },
  workerInfo: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
  },
  workerName: {
    fontSize: 12,
    fontWeight: 600,
    color: theme.textBright,
  },
  workerDesc: {
    fontSize: 10,
    color: theme.textMuted,
  },
  timeText: {
    fontSize: 11,
    color: theme.textMuted,
  },
  toggleOn: {
    padding: '3px 10px',
    borderRadius: 12,
    border: `1px solid ${theme.green}`,
    background: theme.greenSubtle,
    color: theme.green,
    fontSize: 10,
    fontWeight: 700,
    cursor: 'pointer',
  },
  toggleOff: {
    padding: '3px 10px',
    borderRadius: 12,
    border: `1px solid ${theme.border}`,
    background: 'transparent',
    color: theme.textMuted,
    fontSize: 10,
    fontWeight: 700,
    cursor: 'pointer',
  },
  triggerBtn: {
    padding: '3px 10px',
    borderRadius: 6,
    border: `1px solid ${theme.border}`,
    background: 'transparent',
    color: theme.textMuted,
    fontSize: 10,
    fontWeight: 600,
    cursor: 'pointer',
  },
}
