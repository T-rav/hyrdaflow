import React from 'react'
import { theme } from '../../theme'

export function WikiEntryDetail({ entry, selectedRepo, onAdminAction }) {
  const styles = {
    empty: {
      color: theme.textMuted,
      fontSize: 13,
      padding: '24px 0',
    },
    heading: {
      fontSize: 15,
      color: theme.textBright,
      margin: 0,
      marginBottom: 8,
      wordBreak: 'break-all',
    },
    metaTable: {
      borderCollapse: 'collapse',
      fontSize: 12,
      marginBottom: 12,
    },
    metaKey: {
      color: theme.textMuted,
      padding: '2px 12px 2px 0',
      verticalAlign: 'top',
      width: 120,
    },
    metaVal: {
      color: theme.text,
      padding: '2px 0',
      fontFamily:
        'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
    },
    body: {
      fontSize: 13,
      lineHeight: 1.5,
      whiteSpace: 'pre-wrap',
      wordBreak: 'break-word',
      color: theme.text,
      background: theme.surfaceInset,
      border: `1px solid ${theme.border}`,
      borderRadius: 4,
      padding: 12,
    },
    actions: {
      display: 'flex',
      gap: 8,
      marginTop: 12,
    },
    actionBtn: {
      fontSize: 12,
      padding: '4px 10px',
      borderRadius: 4,
      border: `1px solid ${theme.border}`,
      background: theme.surface,
      color: theme.text,
      cursor: 'pointer',
    },
  }

  if (!entry) {
    return <div style={styles.empty}>Select an entry to see its contents.</div>
  }

  const frontmatter = entry.frontmatter || {}

  const handleMarkStale = () => {
    if (!selectedRepo || !entry) return
    onAdminAction('mark-stale', {
      owner: selectedRepo.owner,
      repo: selectedRepo.repo,
      entry_id: entry.id,
      reason: 'manual via console',
    })
  }

  return (
    <div>
      <h3 style={styles.heading}>{entry.filename}</h3>
      <table style={styles.metaTable}>
        <tbody>
          {Object.entries(frontmatter).map(([key, value]) => (
            <tr key={key}>
              <td style={styles.metaKey}>{key}</td>
              <td style={styles.metaVal}>{String(value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <pre style={styles.body}>{entry.body || ''}</pre>
      <div style={styles.actions}>
        <button
          type="button"
          style={styles.actionBtn}
          onClick={handleMarkStale}
          disabled={!selectedRepo}
        >
          Mark stale
        </button>
      </div>
    </div>
  )
}

export default WikiEntryDetail
