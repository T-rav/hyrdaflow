import React from 'react'
import { theme } from '../theme'

/**
 * Computes a human-readable "X ago" string from a timestamp.
 */
function relativeTime(timestamp) {
  if (!timestamp) return ''
  const diff = Date.now() - new Date(timestamp).getTime()
  if (diff < 0) return 'just now'
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days} day${days !== 1 ? 's' : ''} ago`
}

/**
 * EpicReleasedCard — collapsed card shown after an epic has been released.
 *
 * Props:
 *   epic: {
 *     epic_number, title, url, version, released_at,
 *     total_children, merged_children, release_url, changelog_url
 *   }
 */
export function EpicReleasedCard({ epic }) {
  const prCount = epic.merged_children || epic.total_children || 0
  const version = epic.version || ''

  return (
    <div style={styles.card} data-testid={`released-card-${epic.epic_number}`}>
      <div style={styles.row}>
        <span style={styles.check}>✓</span>
        <span style={styles.label}>[Epic]</span>
        <span style={styles.title}>{epic.title}</span>
        <a
          href={epic.url || '#'}
          target="_blank"
          rel="noopener noreferrer"
          style={styles.link}
        >
          #{epic.epic_number}
        </a>
      </div>
      <div style={styles.meta}>
        {version && <span>Released {version}</span>}
        {epic.released_at && <span> · {relativeTime(epic.released_at)}</span>}
        <span> · {prCount} PR{prCount !== 1 ? 's' : ''} merged</span>
      </div>
      <div style={styles.actions}>
        {epic.release_url && (
          <a
            href={epic.release_url}
            target="_blank"
            rel="noopener noreferrer"
            style={styles.actionLink}
            data-testid="view-release"
          >
            View Release ↗
          </a>
        )}
        {epic.changelog_url && (
          <a
            href={epic.changelog_url}
            target="_blank"
            rel="noopener noreferrer"
            style={styles.actionLink}
            data-testid="view-changelog"
          >
            View Changelog ↗
          </a>
        )}
      </div>
    </div>
  )
}

const styles = {
  card: {
    background: theme.surface,
    border: `1px solid ${theme.border}`,
    borderLeft: `3px solid ${theme.green}`,
    borderRadius: 8,
    padding: '12px 16px',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  check: {
    fontSize: 14,
    fontWeight: 700,
    color: theme.green,
    flexShrink: 0,
  },
  label: {
    fontSize: 11,
    fontWeight: 700,
    color: theme.textMuted,
    flexShrink: 0,
  },
  title: {
    fontSize: 13,
    fontWeight: 600,
    color: theme.text,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    flex: 1,
    minWidth: 0,
  },
  link: {
    fontSize: 12,
    fontWeight: 700,
    color: theme.accent,
    textDecoration: 'none',
    flexShrink: 0,
  },
  meta: {
    fontSize: 11,
    color: theme.textMuted,
    paddingLeft: 24,
    marginTop: 4,
  },
  actions: {
    display: 'flex',
    gap: 12,
    paddingLeft: 24,
    marginTop: 8,
  },
  actionLink: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.accent,
    textDecoration: 'none',
  },
}
