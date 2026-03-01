import React from 'react'
import { theme } from '../theme'
import { EpicSwimlaneRow } from './EpicSwimlaneRow'
import { PIPELINE_STAGES } from '../constants'

/**
 * EpicSwimlane — renders the stage-map swimlane for all sub-issues of an epic.
 * Shows a header row with stage labels, then one EpicSwimlaneRow per sub-issue.
 *
 * Props:
 *   children: array of sub-issue objects
 *     [{ issue_number, title, url, current_stage, status, stage_entered_at }]
 */
export function EpicSwimlane({ issues }) {
  if (!issues || issues.length === 0) {
    return (
      <div style={styles.empty} data-testid="swimlane-empty">
        No sub-issues
      </div>
    )
  }

  return (
    <div style={styles.container} data-testid="epic-swimlane">
      <div style={styles.headerRow}>
        <span style={styles.headerLabel} />
        <div style={styles.headerStages}>
          {PIPELINE_STAGES.map(stage => (
            <span
              key={stage.key}
              style={{ ...styles.headerStage, color: stage.color }}
            >
              {stage.label}
            </span>
          ))}
        </div>
        <span style={styles.headerRight}>Stage</span>
        <span style={styles.headerTime}>Time</span>
      </div>

      {issues.map(issue => (
        <EpicSwimlaneRow key={issue.issue_number} issue={issue} />
      ))}
    </div>
  )
}

const styles = {
  container: {
    padding: '8px 0',
  },
  headerRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '0 0 4px 0',
    borderBottom: `1px solid ${theme.border}`,
  },
  headerLabel: {
    minWidth: 48,
    flexShrink: 0,
  },
  headerStages: {
    display: 'flex',
    alignItems: 'center',
    flex: 1,
    justifyContent: 'space-between',
    minWidth: 0,
  },
  headerStage: {
    fontSize: 9,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  headerRight: {
    fontSize: 9,
    fontWeight: 700,
    color: theme.textMuted,
    textTransform: 'uppercase',
    minWidth: 64,
    textAlign: 'right',
    flexShrink: 0,
  },
  headerTime: {
    fontSize: 9,
    fontWeight: 700,
    color: theme.textMuted,
    textTransform: 'uppercase',
    minWidth: 28,
    textAlign: 'right',
    flexShrink: 0,
  },
  empty: {
    padding: '12px 0',
    fontSize: 11,
    color: theme.textMuted,
    fontStyle: 'italic',
  },
}
