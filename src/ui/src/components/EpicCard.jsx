import React, { useState, useMemo } from 'react'
import { theme } from '../theme'
import { MERGE_STRATEGIES } from '../constants'
import { EpicSwimlane } from './EpicSwimlane'
import { EpicReadinessChecklist } from './EpicReadinessChecklist'
import { EpicReleaseButton } from './EpicReleaseButton'
import { EpicReleasedCard } from './EpicReleasedCard'

/**
 * Looks up strategy metadata by key.
 */
function getStrategy(key) {
  return MERGE_STRATEGIES.find(s => s.key === key) || MERGE_STRATEGIES[0]
}

/**
 * Formats a date string to a short locale date.
 */
function shortDate(dateStr) {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString()
}

/**
 * EpicCard — renders a single epic with overview info and expandable swimlane.
 * For released epics, shows a collapsed EpicReleasedCard instead.
 * For bundled/bundled_hitl epics, shows readiness checklist + release button when expanded.
 *
 * Props:
 *   epic: {
 *     epic_number, title, url, status, merge_strategy,
 *     created_at, children: [...sub-issues],
 *     total_children, merged_children, active_children, queued_children,
 *     readiness, version, released_at, release_url, changelog_url
 *   }
 *   onRelease: (epicNumber) => Promise<{ ok, version?, error? }>
 *   releasing: { epicNumber, progress, total } | null
 */
export function EpicCard({ epic, onRelease, releasing }) {
  const [expanded, setExpanded] = useState(false)
  const strategy = getStrategy(epic.merge_strategy)

  const counts = useMemo(() => {
    const total = epic.total_children || epic.children?.length || 0
    const merged = epic.merged_children || 0
    const active = epic.active_children || 0
    const queued = epic.queued_children ?? Math.max(0, total - merged - active)
    const pct = total > 0 ? Math.round((merged / total) * 100) : 0
    return { total, merged, active, queued, pct }
  }, [epic])

  // Released/completed epics show the collapsed released card
  if (epic.status === 'released' || epic.status === 'completed') {
    return <EpicReleasedCard epic={epic} />
  }

  const isBundled = epic.merge_strategy === 'bundled' || epic.merge_strategy === 'bundled_hitl'

  return (
    <div style={styles.card} data-testid={`epic-card-${epic.epic_number}`}>
      <div
        style={styles.header}
        onClick={() => setExpanded(!expanded)}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(!expanded) } }}
      >
        <span style={styles.expandIcon}>{expanded ? '▾' : '▸'}</span>

        <div style={styles.titleGroup}>
          <div style={styles.titleRow}>
            <a
              href={epic.url || '#'}
              target="_blank"
              rel="noopener noreferrer"
              style={styles.epicLink}
              onClick={e => e.stopPropagation()}
            >
              #{epic.epic_number}
            </a>
            <span style={styles.title}>{epic.title}</span>
          </div>

          <div style={styles.metaRow}>
            <span style={strategyBadgeStyles[strategy.key] || strategyBadgeStyles.independent}>
              {strategy.label}
            </span>
            <span style={styles.counts}>
              {counts.merged} merged · {counts.active} active · {counts.queued} queued
            </span>
            <span style={styles.date}>Created {shortDate(epic.created_at)}</span>
          </div>
        </div>

        <div style={styles.progressGroup}>
          <span style={styles.pctLabel}>{counts.pct}%</span>
          <div style={styles.progressTrack}>
            <div
              style={{ ...styles.progressFill, width: `${counts.pct}%` }}
              data-testid={`progress-bar-${epic.epic_number}`}
            />
          </div>
        </div>
      </div>

      {expanded && (
        <div style={styles.expandedContent}>
          <div style={styles.swimlaneWrapper}>
            <EpicSwimlane issues={epic.children || []} />
          </div>

          {isBundled && (
            <div style={styles.readinessSection} data-testid="readiness-section">
              <EpicReadinessChecklist epic={epic} />
              <EpicReleaseButton epic={epic} onRelease={onRelease} releasing={releasing} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Pre-computed strategy badge styles
const strategyBadgeBase = {
  fontSize: 10,
  fontWeight: 700,
  padding: '1px 8px',
  borderRadius: 10,
  flexShrink: 0,
}

const strategyBadgeStyles = Object.fromEntries(
  MERGE_STRATEGIES.map(s => [s.key, {
    ...strategyBadgeBase,
    background: s.subtleColor,
    color: s.color,
  }])
)

const styles = {
  card: {
    background: theme.surface,
    border: `1px solid ${theme.border}`,
    borderLeft: `3px solid ${theme.purple}`,
    borderRadius: 8,
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 12,
    padding: '12px 16px',
    cursor: 'pointer',
    transition: 'background 0.15s',
  },
  expandIcon: {
    fontSize: 12,
    color: theme.textMuted,
    marginTop: 2,
    flexShrink: 0,
  },
  titleGroup: {
    flex: 1,
    minWidth: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  titleRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  epicLink: {
    fontSize: 13,
    fontWeight: 700,
    color: theme.accent,
    textDecoration: 'none',
    flexShrink: 0,
  },
  title: {
    fontSize: 13,
    fontWeight: 600,
    color: theme.text,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  metaRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    flexWrap: 'wrap',
  },
  counts: {
    fontSize: 11,
    color: theme.textMuted,
  },
  date: {
    fontSize: 10,
    color: theme.textMuted,
  },
  progressGroup: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    flexShrink: 0,
    minWidth: 120,
  },
  pctLabel: {
    fontSize: 12,
    fontWeight: 700,
    color: theme.green,
    minWidth: 32,
    textAlign: 'right',
  },
  progressTrack: {
    flex: 1,
    height: 6,
    borderRadius: 3,
    background: theme.border,
    overflow: 'hidden',
    minWidth: 60,
  },
  progressFill: {
    height: '100%',
    borderRadius: 3,
    background: theme.green,
    transition: 'width 0.3s ease',
  },
  expandedContent: {
    borderTop: `1px solid ${theme.border}`,
  },
  swimlaneWrapper: {
    padding: '0 16px 12px 40px',
  },
  readinessSection: {
    padding: '0 16px 12px 40px',
    borderTop: `1px solid ${theme.border}`,
  },
}
