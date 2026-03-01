import React from 'react'
import { theme } from '../theme'
import { EVENT_PROCESS_MAP } from '../constants'

export const typeColors = {
  worker_update: theme.accent,
  phase_change: theme.yellow,
  pr_created: theme.green,
  review_update: theme.orange,
  merge_update: theme.green,
  error: theme.red,
  transcript_line: theme.textMuted,
  triage_update: theme.triageGreen,
  planner_update: theme.purple,
  orchestrator_status: theme.accent,
  hitl_escalation: theme.red,
  hitl_update: theme.orange,
  ci_check: theme.yellow,
  issue_created: theme.green,
  background_worker_status: theme.accent,
}

/**
 * Returns a bracketed process label for an event type, e.g. "[triage]".
 * Falls back to "[unknown]" when the event type has no mapping.
 */
export function processLabel(type) {
  const name = EVENT_PROCESS_MAP[type] || 'unknown'
  return `[${name}]`
}

export function eventSummary(type, data) {
  switch (type) {
    case 'phase_change': return data.phase
    case 'worker_update': return `#${data.issue} \u2192 ${data.status}`
    case 'transcript_line': return `#${data.issue || data.pr} ${data.line || ''}`
    case 'pr_created': return `PR #${data.pr} for #${data.issue}${data.draft ? ' (draft)' : ''}`
    case 'review_update': return `PR #${data.pr} \u2192 ${data.verdict || data.status}`
    case 'merge_update': return `PR #${data.pr} ${data.status}`
    case 'error': return data.message || 'Error'
    case 'triage_update': return `#${data.issue} → ${data.status}`
    case 'planner_update': return `#${data.issue} → ${data.status}`
    case 'orchestrator_status': return `${data.status}`
    case 'hitl_escalation': return data.pr ? `PR #${data.pr} escalated to HITL` : `Issue #${data.issue} escalated to HITL`
    case 'hitl_update': return `#${data.issue} ${data.action || data.status || 'awaiting_retry'}`
    case 'ci_check': return `PR #${data.pr} CI ${data.status}`
    case 'issue_created': return `#${data.issue} created`
    case 'background_worker_status': return `${data.worker} → ${data.status}`
    default: return JSON.stringify(data).slice(0, 80)
  }
}

const ISSUE_PREFIX_PATTERN = /^#\d+\s*/
const ISSUE_WORD_PREFIX_PATTERN = /^Issue #\d+\s*/

export function eventMessage(type, data) {
  const summary = eventSummary(type, data)
  if (summary.startsWith('#')) return summary.replace(ISSUE_PREFIX_PATTERN, '')
  if (summary.startsWith('Issue #')) return summary.replace(ISSUE_WORD_PREFIX_PATTERN, '')
  return summary
}

export function EventLog({ events = [] }) {
  // Filter out noisy transcript_line events from the log
  const filtered = events.filter(e => e.type !== 'transcript_line')

  return (
    <div style={styles.panel} data-testid="event-log-panel">
      <div style={styles.title}>Event Log</div>
      <div style={styles.log}>
        {filtered.length === 0 && (
          <div style={styles.empty}>Waiting for events...</div>
        )}
        {filtered.map((e, i) => (
          <div key={i} style={styles.item}>
            <span style={styles.time}>
              {new Date(e.timestamp).toLocaleTimeString()}
            </span>
            <span style={typeSpanStyles[e.type] || defaultTypeStyle}>
              {processLabel(e.type)}
            </span>
            <span>{eventSummary(e.type, e.data)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

const styles = {
  panel: {
    borderLeft: `1px solid ${theme.border}`,
    background: theme.surface,
    display: 'flex',
    flexDirection: 'column',
    flex: 1,
    minHeight: 0,
    overflow: 'hidden',
  },
  title: {
    padding: '12px 16px 8px',
    fontSize: 11,
    fontWeight: 600,
    textTransform: 'uppercase',
    color: theme.textMuted,
    letterSpacing: 0.5,
  },
  log: { padding: 8, flex: 1, minHeight: 0, overflowY: 'auto' },
  empty: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    height: 200, color: theme.textMuted, fontSize: 13,
  },
  item: {
    padding: '6px 8px',
    borderBottom: `1px solid ${theme.border}`,
    fontSize: 11,
  },
  time: { color: theme.textMuted, marginRight: 8 },
  type: { fontWeight: 600, marginRight: 6 },
}

// Pre-computed style for each event type (avoids object spread in .map())
export const typeSpanStyles = Object.fromEntries(
  Object.entries(typeColors).map(([k, v]) => [k, { ...styles.type, color: v }])
)
export const defaultTypeStyle = { ...styles.type, color: theme.textMuted }
