import React from 'react'
import { theme } from '../theme'
import { TranscriptPreview } from './TranscriptPreview'

/**
 * Returns a badge style based on PR state.
 */
function prStateBadge(state) {
  if (state === 'merged') return prBadgeStyles.merged
  if (state === 'draft') return prBadgeStyles.draft
  return prBadgeStyles.open
}

/**
 * Returns a badge style based on CI status.
 */
function ciBadge(status) {
  if (status === 'passing') return ciBadgeStyles.passing
  if (status === 'failing') return ciBadgeStyles.failing
  return ciBadgeStyles.pending
}

/**
 * Returns a badge style based on review verdict.
 */
function reviewBadge(verdict) {
  if (verdict === 'approved') return reviewBadgeStyles.approved
  if (verdict === 'changes_requested') return reviewBadgeStyles.changes_requested
  return reviewBadgeStyles.pending
}

/**
 * Computes how long ago a timestamp was, as a human-readable string.
 */
function timeAgo(timestamp) {
  if (!timestamp) return '—'
  const diff = Date.now() - new Date(timestamp).getTime()
  if (diff < 0) return '—'
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h`
  const days = Math.floor(hrs / 24)
  return `${days}d`
}

/**
 * EpicWorkDetail — expandable detail panel for a sub-issue within a swimlane row.
 *
 * Props:
 *   issue: {
 *     issue_number, title, url,
 *     pr_number, pr_url, pr_state, approval_state, ci_status,
 *     branch, worker, stage_entered_at, transcript
 *   }
 *   onRequestChanges: (issueNumber) => void (optional)
 */
export function EpicWorkDetail({ issue, onRequestChanges }) {
  const hasPr = issue.pr_number != null
  const transcript = issue.transcript || []

  return (
    <div style={styles.container} data-testid={`work-detail-${issue.issue_number}`}>
      <div style={styles.grid}>
        {/* PR status */}
        <div style={styles.field}>
          <span style={styles.label}>PR</span>
          {hasPr ? (
            <span style={styles.valueRow}>
              <a
                href={issue.pr_url || '#'}
                target="_blank"
                rel="noopener noreferrer"
                style={styles.link}
              >
                #{issue.pr_number}
              </a>
              <span style={prStateBadge(issue.pr_state)}>
                {issue.pr_state || 'open'}
              </span>
            </span>
          ) : (
            <span style={styles.dim}>—</span>
          )}
        </div>

        {/* Approval state */}
        <div style={styles.field}>
          <span style={styles.label}>Review</span>
          <span style={reviewBadge(issue.approval_state)}>
            {formatVerdict(issue.approval_state)}
          </span>
        </div>

        {/* CI status */}
        <div style={styles.field}>
          <span style={styles.label}>CI</span>
          <span style={ciBadge(issue.ci_status)}>
            {issue.ci_status || 'pending'}
          </span>
        </div>

        {/* Branch */}
        <div style={styles.field}>
          <span style={styles.label}>Branch</span>
          <span style={styles.mono}>{issue.branch || '—'}</span>
        </div>

        {/* Worker */}
        <div style={styles.field}>
          <span style={styles.label}>Worker</span>
          <span style={styles.value}>{issue.worker || '—'}</span>
        </div>

        {/* Time in stage */}
        <div style={styles.field}>
          <span style={styles.label}>Time in stage</span>
          <span style={styles.value}>{timeAgo(issue.stage_entered_at)}</span>
        </div>
      </div>

      {/* Transcript preview */}
      {transcript.length > 0 && (
        <TranscriptPreview transcript={transcript} maxCollapsedLines={3} />
      )}

      {/* Action buttons */}
      <div style={styles.actions}>
        {hasPr && issue.pr_url && (
          <a
            href={issue.pr_url}
            target="_blank"
            rel="noopener noreferrer"
            style={styles.actionBtn}
          >
            View PR ↗
          </a>
        )}
        {issue.url && (
          <a
            href={issue.url}
            target="_blank"
            rel="noopener noreferrer"
            style={styles.actionBtn}
          >
            View Issue ↗
          </a>
        )}
        {onRequestChanges && (
          <span
            role="button"
            tabIndex={0}
            style={styles.requestChangesBtn}
            onClick={() => onRequestChanges(issue.issue_number)}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onRequestChanges(issue.issue_number) } }}
            data-testid={`request-changes-${issue.issue_number}`}
          >
            Request Changes
          </span>
        )}
      </div>
    </div>
  )
}

function formatVerdict(verdict) {
  if (verdict === 'changes_requested') return 'changes requested'
  return verdict || 'pending'
}

// Pre-computed badge styles
const badgeBase = {
  fontSize: 10,
  fontWeight: 700,
  padding: '1px 6px',
  borderRadius: 8,
  textTransform: 'capitalize',
}

const prBadgeStyles = {
  open: { ...badgeBase, background: theme.greenSubtle, color: theme.green },
  merged: { ...badgeBase, background: theme.purpleSubtle, color: theme.purple },
  draft: { ...badgeBase, background: theme.mutedSubtle, color: theme.textMuted },
}

const ciBadgeStyles = {
  passing: { ...badgeBase, background: theme.greenSubtle, color: theme.green },
  failing: { ...badgeBase, background: theme.redSubtle, color: theme.red },
  pending: { ...badgeBase, background: theme.yellowSubtle, color: theme.yellow },
}

const reviewBadgeStyles = {
  approved: { ...badgeBase, background: theme.greenSubtle, color: theme.green },
  changes_requested: { ...badgeBase, background: theme.orangeSubtle, color: theme.orange },
  pending: { ...badgeBase, background: theme.yellowSubtle, color: theme.yellow },
}

const styles = {
  container: {
    padding: '8px 0 8px 16px',
    borderBottom: `1px solid ${theme.border}`,
    background: theme.surfaceInset,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(3, 1fr)',
    gap: 8,
    marginBottom: 8,
  },
  field: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
  },
  label: {
    fontSize: 9,
    fontWeight: 700,
    color: theme.textMuted,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  value: {
    fontSize: 11,
    color: theme.text,
  },
  valueRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  dim: {
    fontSize: 11,
    color: theme.textMuted,
  },
  mono: {
    fontSize: 10,
    fontFamily: 'monospace',
    color: theme.text,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  link: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.accent,
    textDecoration: 'none',
  },
  actions: {
    display: 'flex',
    gap: 8,
    marginTop: 8,
  },
  actionBtn: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.accent,
    textDecoration: 'none',
    padding: '3px 8px',
    borderRadius: 6,
    border: `1px solid ${theme.border}`,
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  requestChangesBtn: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.orange,
    padding: '3px 8px',
    borderRadius: 6,
    border: `1px solid ${theme.orange}`,
    cursor: 'pointer',
    transition: 'all 0.15s',
    userSelect: 'none',
  },
}
