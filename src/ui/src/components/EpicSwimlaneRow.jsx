import React, { useState } from 'react'
import { theme } from '../theme'
import { PIPELINE_STAGES, PULSE_ANIMATION } from '../constants'
import { EpicWorkDetail } from './EpicWorkDetail'

/**
 * Computes how long ago a timestamp was, as a human-readable string.
 */
function timeAgo(timestamp) {
  if (!timestamp) return ''
  const diff = Date.now() - new Date(timestamp).getTime()
  if (diff < 0) return ''
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h`
  const days = Math.floor(hrs / 24)
  return `${days}d`
}

/**
 * Returns a theme color based on time-in-stage duration.
 * <1h = green, 1-4h = yellow, >4h = red
 */
function timeColor(timestamp) {
  if (!timestamp) return theme.textMuted
  const hrs = (Date.now() - new Date(timestamp).getTime()) / 3600000
  if (hrs < 1) return theme.green
  if (hrs <= 4) return theme.yellow
  return theme.red
}

/**
 * Maps a sub-issue's current_stage to the index within PIPELINE_STAGES.
 */
function stageIndex(stageKey) {
  return PIPELINE_STAGES.findIndex(s => s.key === stageKey)
}

/**
 * Determines the node type for a given stage index relative to the issue's progress.
 * Returns 'done' | 'active' | 'queued' | 'pending'
 */
function nodeType(idx, currentIdx, status) {
  if (idx < currentIdx) return 'done'
  if (idx === currentIdx) {
    if (status === 'merged' || status === 'done') return 'done'
    if (status === 'queued') return 'queued'
    return 'active'
  }
  return 'pending'
}

/**
 * EpicSwimlaneRow — renders a single sub-issue as a horizontal row of pipeline stage nodes.
 * Clicking the expand chevron reveals the EpicWorkDetail panel.
 *
 * Props:
 *   issue: { issue_number, title, url, current_stage, status, stage_entered_at, ... }
 *   onRequestChanges: (issueNumber) => void (optional)
 */
export function EpicSwimlaneRow({ issue, onRequestChanges }) {
  const [expanded, setExpanded] = useState(false)
  const currentIdx = stageIndex(issue.current_stage)

  return (
    <div data-testid={`swimlane-row-${issue.issue_number}`}>
      <div style={styles.row}>
        <span
          role="button"
          tabIndex={0}
          style={styles.expandIcon}
          onClick={() => setExpanded(!expanded)}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(!expanded) } }}
          aria-expanded={expanded}
          aria-label={`Expand details for #${issue.issue_number}`}
          data-testid={`expand-${issue.issue_number}`}
        >
          {expanded ? '▾' : '▸'}
        </span>

        <a
          href={issue.url || `#${issue.issue_number}`}
          target="_blank"
          rel="noopener noreferrer"
          style={styles.issueLink}
          title={issue.title}
        >
          #{issue.issue_number}
        </a>

        <div style={styles.nodes}>
          {PIPELINE_STAGES.map((stage, idx) => {
            const type = nodeType(idx, currentIdx, issue.status)
            const isLast = idx === PIPELINE_STAGES.length - 1

            return (
              <React.Fragment key={stage.key}>
                <span
                  style={nodeStyles[type][stage.key]}
                  title={`${stage.label}: ${type}`}
                  data-testid={`node-${issue.issue_number}-${stage.key}`}
                >
                  {type === 'done' && '✓'}
                </span>
                {!isLast && (
                  <span style={type === 'done' ? connectorSolidStyle : connectorDashedStyle} />
                )}
              </React.Fragment>
            )
          })}
        </div>

        <span style={styles.stageLabel}>
          {PIPELINE_STAGES[currentIdx]?.label || issue.current_stage || '—'}
        </span>

        <span style={{ ...styles.timeInStage, color: timeColor(issue.stage_entered_at) }}>
          {timeAgo(issue.stage_entered_at)}
        </span>
      </div>

      {expanded && (
        <EpicWorkDetail issue={issue} onRequestChanges={onRequestChanges} />
      )}
    </div>
  )
}

// Pre-computed node styles per type per stage (avoids object spread in render)
const nodeBase = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: 20,
  height: 20,
  borderRadius: '50%',
  fontSize: 10,
  fontWeight: 700,
  flexShrink: 0,
  transition: 'all 0.15s',
}

const nodeStyles = {
  done: Object.fromEntries(
    PIPELINE_STAGES.map(s => [s.key, { ...nodeBase, background: s.color, color: theme.white }])
  ),
  active: Object.fromEntries(
    PIPELINE_STAGES.map(s => [s.key, { ...nodeBase, background: s.color, color: theme.white, animation: PULSE_ANIMATION }])
  ),
  queued: Object.fromEntries(
    PIPELINE_STAGES.map(s => [s.key, { ...nodeBase, background: s.subtleColor, color: s.color, border: `1px solid ${s.color}` }])
  ),
  pending: Object.fromEntries(
    PIPELINE_STAGES.map(s => [s.key, { ...nodeBase, background: 'transparent', color: theme.textMuted, border: `1px solid ${theme.border}` }])
  ),
}

const connectorBase = {
  flex: 1,
  height: 2,
  minWidth: 12,
}

const connectorSolidStyle = { ...connectorBase, background: theme.textMuted }
const connectorDashedStyle = {
  ...connectorBase,
  background: 'transparent',
  borderTop: `2px dashed ${theme.border}`,
  height: 0,
}

const styles = {
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '6px 0',
    borderBottom: `1px solid ${theme.border}`,
  },
  expandIcon: {
    fontSize: 10,
    color: theme.textMuted,
    cursor: 'pointer',
    flexShrink: 0,
    width: 12,
    textAlign: 'center',
    userSelect: 'none',
  },
  issueLink: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.accent,
    textDecoration: 'none',
    minWidth: 48,
    flexShrink: 0,
  },
  nodes: {
    display: 'flex',
    alignItems: 'center',
    flex: 1,
    gap: 0,
    minWidth: 0,
  },
  stageLabel: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.text,
    minWidth: 64,
    textAlign: 'right',
    flexShrink: 0,
  },
  timeInStage: {
    fontSize: 10,
    fontWeight: 600,
    minWidth: 28,
    textAlign: 'right',
    flexShrink: 0,
  },
}
