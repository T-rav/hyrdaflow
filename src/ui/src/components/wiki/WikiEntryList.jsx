import React from 'react'
import { theme } from '../../theme'

const STATUS_COLORS = {
  active: theme.green,
  stale: theme.orange,
  superseded: theme.textMuted,
}

export function WikiEntryList({ entries, selectedId, onSelect }) {
  const styles = {
    root: {
      display: 'flex',
      flexDirection: 'column',
      padding: '4px 0',
    },
    empty: {
      padding: '24px 16px',
      color: theme.textMuted,
      fontSize: 13,
      textAlign: 'center',
    },
    item: (isSelected) => ({
      padding: '8px 16px',
      cursor: 'pointer',
      borderLeft: `3px solid ${isSelected ? theme.accent : 'transparent'}`,
      background: isSelected ? theme.surfaceInset : 'transparent',
      color: theme.text,
    }),
    row: {
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      fontSize: 13,
    },
    topicChip: {
      fontSize: 10,
      textTransform: 'uppercase',
      letterSpacing: 0.5,
      padding: '1px 6px',
      borderRadius: 3,
      background: theme.surface,
      color: theme.textMuted,
      border: `1px solid ${theme.border}`,
    },
    filename: {
      flex: 1,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
      color: theme.textBright,
    },
    statusDot: (status) => ({
      width: 8,
      height: 8,
      borderRadius: '50%',
      background: STATUS_COLORS[status] || theme.textMuted,
      flexShrink: 0,
    }),
    meta: {
      marginTop: 2,
      fontSize: 11,
      color: theme.textMuted,
    },
  }

  if (!entries || entries.length === 0) {
    return (
      <div style={styles.root}>
        <div style={styles.empty}>No entries</div>
      </div>
    )
  }

  return (
    <div style={styles.root}>
      {entries.map((entry) => {
        const isSelected = entry.id === selectedId
        return (
          <div
            key={`${entry.topic}-${entry.id}`}
            style={styles.item(isSelected)}
            onClick={() => onSelect(entry)}
            role="button"
            tabIndex={0}
          >
            <div style={styles.row}>
              <span
                style={styles.statusDot(entry.status)}
                aria-label={`status ${entry.status}`}
              />
              <span style={styles.topicChip}>{entry.topic}</span>
              <span style={styles.filename}>{entry.filename}</span>
            </div>
            <div style={styles.meta}>
              #{entry.source_issue ?? 'unknown'} · {entry.source_phase || '—'} ·{' '}
              {entry.status}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export default WikiEntryList
