import React from 'react'
import { theme } from '../../theme'

function formatTokens(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`
  return String(n)
}

function formatDuration(seconds) {
  if (seconds < 60) return `${Math.round(seconds)}s`
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  return `${mins}m ${secs}s`
}

export function IssueTable({ rows, onRowClick }) {
  if (!rows || rows.length === 0) {
    return <div style={styles.empty}>No data</div>
  }

  return (
    <div style={styles.container}>
      <div style={styles.title}>Per-Issue</div>
      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>#</th>
            <th style={styles.th}>Phase</th>
            <th style={styles.th}>Run</th>
            <th style={styles.thRight}>Tokens</th>
            <th style={styles.thRight}>Duration</th>
            <th style={styles.thRight}>Tools</th>
            <th style={styles.thRight}>Skills</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={`${row.issue}-${row.phase}-${row.run_id}-${i}`}
              style={{
                ...styles.tr,
                ...(row.crashed ? styles.trCrashed : {}),
              }}
              onClick={() => onRowClick(row)}
            >
              <td style={styles.td}>{row.issue}</td>
              <td style={styles.td}>{row.phase}</td>
              <td style={styles.td}>{row.run_id}</td>
              <td style={styles.tdRight}>{formatTokens(row.tokens)}</td>
              <td style={styles.tdRight}>{formatDuration(row.duration_seconds)}</td>
              <td style={styles.tdRight}>{row.tool_count}</td>
              <td style={styles.tdRight}>
                {row.skill_pass_count}/{row.skill_total}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const styles = {
  container: {
    background: theme.surfaceInset,
    borderRadius: 8,
    padding: 16,
  },
  title: {
    fontSize: 13,
    fontWeight: 600,
    color: theme.textBright,
    marginBottom: 8,
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: 12,
  },
  th: {
    textAlign: 'left',
    padding: '6px 8px',
    color: theme.textMuted,
    fontSize: 10,
    fontWeight: 600,
    textTransform: 'uppercase',
    borderBottom: `1px solid ${theme.border}`,
  },
  thRight: {
    textAlign: 'right',
    padding: '6px 8px',
    color: theme.textMuted,
    fontSize: 10,
    fontWeight: 600,
    textTransform: 'uppercase',
    borderBottom: `1px solid ${theme.border}`,
  },
  tr: {
    cursor: 'pointer',
    transition: 'background 0.15s',
  },
  trCrashed: {
    color: theme.red,
  },
  td: {
    padding: '8px',
    color: theme.text,
    borderBottom: `1px solid ${theme.border}`,
  },
  tdRight: {
    padding: '8px',
    color: theme.text,
    textAlign: 'right',
    borderBottom: `1px solid ${theme.border}`,
  },
  empty: {
    padding: 40,
    textAlign: 'center',
    color: theme.textMuted,
    fontSize: 11,
  },
}
