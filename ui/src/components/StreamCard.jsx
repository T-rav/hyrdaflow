import React, { useState, useCallback } from 'react'
import { theme } from '../theme'
import { PIPELINE_STAGES } from '../constants'
import { formatDuration, STAGE_META, STAGE_KEYS } from '../hooks/useTimeline'
import { TranscriptPreview } from './TranscriptPreview'

export function StatusDot({ status }) {
  if (status === 'active') return <span style={dotStyles.active} />
  if (status === 'done') return <span style={dotStyles.done}>&#10003;</span>
  if (status === 'failed') return <span style={dotStyles.failed}>&#10007;</span>
  if (status === 'hitl') return <span style={dotStyles.hitl}>!</span>
  if (status === 'queued') return <span style={dotStyles.queued} />
  return <span style={dotStyles.pending} />
}

function StageRow({ stageKey, stageData, isLast }) {
  const meta = STAGE_META[stageKey]
  if (!meta) return null

  const duration = stageData.startTime && stageData.endTime
    ? formatDuration(new Date(stageData.endTime) - new Date(stageData.startTime))
    : stageData.startTime && stageData.status === 'active'
      ? 'running...'
      : null

  const nodeStyle = stageData.status === 'pending'
    ? { ...stageNodeBase, background: 'transparent', borderColor: theme.border }
    : stageData.status === 'active'
      ? { ...stageNodeBase, background: meta.color, borderColor: meta.color, animation: 'stream-pulse 1.5s ease-in-out infinite' }
      : stageData.status === 'failed'
        ? { ...stageNodeBase, background: theme.red, borderColor: theme.red }
        : stageData.status === 'hitl'
          ? { ...stageNodeBase, background: theme.yellow, borderColor: theme.yellow }
          : stageData.status === 'queued'
            ? { ...stageNodeBase, background: theme.yellow, borderColor: theme.yellow }
            : { ...stageNodeBase, background: meta.color, borderColor: meta.color }

  const connectorColor = stageData.status !== 'pending' ? meta.color : theme.border
  const connectorDashed = stageData.status === 'pending'

  return (
    <div style={styles.stageRow}>
      <div style={styles.stageLeft}>
        <div style={nodeStyle} />
        {!isLast && (
          <div style={{
            ...styles.connector,
            ...(connectorDashed
              ? { borderLeft: `2px dashed ${connectorColor}`, background: 'transparent', width: 0 }
              : { background: connectorColor }),
          }} />
        )}
      </div>
      <div style={styles.stageContent}>
        <span style={styles.stageLabel}>{meta.label}</span>
        <span style={badgeStyleMap[stageData.status] || badgeStyleMap.pending}>
          {stageData.status}
        </span>
        {duration && <span style={styles.duration}>{duration}</span>}
      </div>
    </div>
  )
}

export function StreamCard({ issue, intent, defaultExpanded, onViewTranscript, onRequestChanges, transcript = [] }) {
  const [expanded, setExpanded] = useState(defaultExpanded || false)
  const [showFeedback, setShowFeedback] = useState(false)
  const [feedbackText, setFeedbackText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const toggle = useCallback(() => setExpanded(v => !v), [])

  const handleSubmitFeedback = useCallback(async () => {
    if (!feedbackText.trim() || submitting) return
    setSubmitting(true)
    setSubmitError(null)
    const ok = await onRequestChanges(issue.issueNumber, feedbackText.trim(), issue.currentStage)
    setSubmitting(false)
    if (ok) {
      setShowFeedback(false)
      setFeedbackText('')
    } else {
      setSubmitError('Failed to submit. Please try again.')
    }
  }, [feedbackText, submitting, onRequestChanges, issue.issueNumber, issue.currentStage])

  const meta = STAGE_META[issue.currentStage]
  const isActive = issue.overallStatus === 'active'

  const totalDuration = issue.startTime
    ? formatDuration(
        (issue.endTime ? new Date(issue.endTime) : new Date()) - new Date(issue.startTime)
      )
    : null

  const cardBorder = isActive
    ? `1px solid ${theme.cardActiveBorder}`
    : `1px solid ${theme.border}`

  return (
    <div style={{ ...styles.card, border: cardBorder }}>
      <style>{pulseKeyframes}</style>
      <div style={styles.header} onClick={toggle}>
        <div style={styles.headerLeft}>
          {issue.issueUrl ? (
            <a
              style={styles.issueLink}
              href={issue.issueUrl}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
            >
              #{issue.issueNumber}
            </a>
          ) : (
            <span style={styles.issueNum}>#{issue.issueNumber}</span>
          )}
          <span style={styles.title}>{intent?.text || issue.title}</span>
        </div>
        <div style={styles.headerRight}>
          {meta && (
            <span style={{
              ...styles.stageBadge,
              background: meta.subtleColor,
              color: meta.color,
              borderColor: meta.color,
            }}>
              {meta.label}
            </span>
          )}
          {totalDuration && <span style={styles.duration}>{totalDuration}</span>}
          <StatusDot status={issue.overallStatus} />
          {issue.pr && (
            <a
              style={styles.prLink}
              href={issue.pr.url || '#'}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
            >
              PR #{issue.pr.number}
            </a>
          )}
          <span style={styles.arrow}>{expanded ? '\u25BE' : '\u25B8'}</span>
        </div>
      </div>

      {expanded && (
        <div style={styles.body}>
          {intent && (
            <div style={styles.intentRow}>
              <span style={styles.intentLabel}>Intent:</span>
              <span style={styles.intentText}>{intent.text}</span>
            </div>
          )}
          <div style={styles.stagesContainer}>
            {STAGE_KEYS.map((key, idx) => (
              <StageRow
                key={key}
                stageKey={key}
                stageData={issue.stages[key]}
                isLast={idx === STAGE_KEYS.length - 1}
              />
            ))}
          </div>
          {isActive && transcript.length > 0 && (
            <TranscriptPreview transcript={transcript} />
          )}
          <div style={styles.actions}>
            {onViewTranscript && (
              <span
                style={styles.actionBtn}
                onClick={() => onViewTranscript(issue.issueNumber)}
              >
                View Transcript
              </span>
            )}
            {issue.pr?.url && (
              <a
                style={styles.actionBtn}
                href={issue.pr.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                View PR
              </a>
            )}
            {onRequestChanges && (
              <span
                style={submitting ? requestChangesBtnDisabled : styles.actionBtn}
                onClick={() => {
                  if (submitting) return
                  if (showFeedback) {
                    setFeedbackText('')
                    setSubmitError(null)
                  }
                  setShowFeedback(v => !v)
                }}
                data-testid={`request-changes-btn-${issue.issueNumber}`}
              >
                Request Changes
              </span>
            )}
          </div>
          {showFeedback && (
            <div style={styles.feedbackPanel}>
              <textarea
                style={styles.feedbackTextarea}
                placeholder="What needs to change?"
                value={feedbackText}
                onChange={(e) => setFeedbackText(e.target.value)}
                data-testid={`request-changes-textarea-${issue.issueNumber}`}
              />
              <div style={styles.feedbackActions}>
                <button
                  style={(!feedbackText.trim() || submitting) ? feedbackSubmitBtnDisabled : styles.feedbackSubmitBtn}
                  disabled={!feedbackText.trim() || submitting}
                  onClick={handleSubmitFeedback}
                  data-testid={`request-changes-submit-${issue.issueNumber}`}
                >
                  {submitting ? 'Submitting...' : 'Submit'}
                </button>
                <button
                  style={submitting ? feedbackCancelBtnDisabled : styles.feedbackCancelBtn}
                  disabled={submitting}
                  onClick={() => { setShowFeedback(false); setFeedbackText(''); setSubmitError(null) }}
                  data-testid={`request-changes-cancel-${issue.issueNumber}`}
                >
                  Cancel
                </button>
              </div>
              {submitError && (
                <div style={styles.feedbackError} data-testid={`request-changes-error-${issue.issueNumber}`}>
                  {submitError}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const pulseKeyframes = `
  @keyframes stream-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
`

const stageNodeBase = {
  width: 10,
  height: 10,
  borderRadius: '50%',
  border: '2px solid',
  flexShrink: 0,
}

export const dotStyles = {
  active: {
    display: 'inline-block',
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.accent,
    animation: 'stream-pulse 1.5s ease-in-out infinite',
  },
  done: { fontSize: 11, fontWeight: 700, color: theme.green },
  failed: { fontSize: 11, fontWeight: 700, color: theme.red },
  hitl: { fontSize: 11, fontWeight: 700, color: theme.yellow },
  queued: {
    display: 'inline-block',
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.yellow,
  },
  pending: {
    display: 'inline-block',
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.border,
  },
}

const badgeBase = {
  padding: '1px 6px',
  borderRadius: 8,
  fontSize: 9,
  fontWeight: 600,
  textTransform: 'uppercase',
}

export const badgeStyleMap = {
  active: { ...badgeBase, background: theme.accentSubtle, color: theme.accent },
  done: { ...badgeBase, background: theme.greenSubtle, color: theme.green },
  failed: { ...badgeBase, background: theme.redSubtle, color: theme.red },
  hitl: { ...badgeBase, background: theme.yellowSubtle, color: theme.yellow },
  queued: { ...badgeBase, background: theme.yellowSubtle, color: theme.yellow },
  pending: { ...badgeBase, background: theme.mutedSubtle, color: theme.textMuted },
}

const styles = {
  card: {
    background: theme.surface,
    borderRadius: 8,
    marginBottom: 8,
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 12px',
    cursor: 'pointer',
    transition: 'background 0.15s',
  },
  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    minWidth: 0,
    flex: 1,
  },
  issueNum: {
    fontSize: 12,
    fontWeight: 700,
    color: theme.textBright,
    flexShrink: 0,
    whiteSpace: 'nowrap',
  },
  title: {
    fontSize: 12,
    color: theme.text,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  headerRight: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    flexShrink: 0,
  },
  stageBadge: {
    padding: '2px 8px',
    borderRadius: 10,
    fontSize: 10,
    fontWeight: 600,
    textTransform: 'uppercase',
    border: '1px solid',
    whiteSpace: 'nowrap',
  },
  duration: {
    fontSize: 10,
    color: theme.textMuted,
    whiteSpace: 'nowrap',
  },
  prLink: {
    fontSize: 10,
    color: theme.accent,
    textDecoration: 'none',
    whiteSpace: 'nowrap',
  },
  issueLink: {
    fontSize: 12,
    fontWeight: 700,
    color: theme.accent,
    textDecoration: 'none',
    flexShrink: 0,
    whiteSpace: 'nowrap',
  },
  arrow: {
    fontSize: 10,
    color: theme.textMuted,
    width: 12,
    textAlign: 'center',
  },
  body: {
    padding: '4px 12px 12px 12px',
    borderTop: `1px solid ${theme.border}`,
  },
  intentRow: {
    display: 'flex',
    gap: 8,
    padding: '6px 0',
    borderBottom: `1px solid ${theme.border}`,
    marginBottom: 4,
  },
  intentLabel: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.accent,
    flexShrink: 0,
  },
  intentText: {
    fontSize: 11,
    color: theme.text,
    lineHeight: 1.4,
  },
  stagesContainer: {
    padding: '4px 0',
  },
  stageRow: {
    display: 'flex',
    gap: 8,
  },
  stageLeft: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    width: 16,
    flexShrink: 0,
  },
  connector: {
    width: 2,
    flex: 1,
    minHeight: 8,
  },
  stageContent: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '4px 0',
    flex: 1,
  },
  stageLabel: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.text,
    width: 72,
  },
  actions: {
    display: 'flex',
    gap: 8,
    paddingTop: 8,
    borderTop: `1px solid ${theme.border}`,
    marginTop: 4,
  },
  actionBtn: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.accent,
    cursor: 'pointer',
    padding: '3px 8px',
    borderRadius: 4,
    border: `1px solid ${theme.border}`,
    background: 'transparent',
    textDecoration: 'none',
    transition: 'background 0.15s',
  },
  feedbackPanel: {
    marginTop: 8,
    borderTop: `1px solid ${theme.border}`,
    paddingTop: 8,
  },
  feedbackTextarea: {
    width: '100%',
    minHeight: 60,
    padding: 8,
    background: theme.bg,
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    color: theme.text,
    fontFamily: 'inherit',
    fontSize: 12,
    resize: 'vertical',
    boxSizing: 'border-box',
  },
  feedbackActions: {
    display: 'flex',
    gap: 8,
    marginTop: 8,
  },
  feedbackSubmitBtn: {
    padding: '6px 14px',
    border: 'none',
    borderRadius: 6,
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: 'inherit',
    fontSize: 12,
    background: theme.btnGreen,
    color: theme.white,
  },
  feedbackCancelBtn: {
    padding: '6px 14px',
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: 'inherit',
    fontSize: 12,
    background: theme.surfaceInset,
    color: theme.text,
  },
  feedbackError: {
    marginTop: 6,
    fontSize: 11,
    color: theme.red,
  },
}

// Pre-computed disabled variants — avoids object spread in render
const feedbackSubmitBtnDisabled = { ...styles.feedbackSubmitBtn, cursor: 'not-allowed', opacity: 0.5 }
const feedbackCancelBtnDisabled = { ...styles.feedbackCancelBtn, cursor: 'not-allowed', opacity: 0.5 }
const requestChangesBtnDisabled = { ...styles.actionBtn, cursor: 'not-allowed', opacity: 0.5 }
