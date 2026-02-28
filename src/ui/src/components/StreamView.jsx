import React, { useMemo, useCallback } from 'react'
import { theme } from '../theme'
import { useHydraFlow } from '../context/HydraFlowContext'
import { StreamCard } from './StreamCard'
import { PIPELINE_STAGES, PULSE_ANIMATION } from '../constants'
import { STAGE_KEYS } from '../hooks/useTimeline'
import {
  sectionHeaderStyles,
  sectionLabelStyles,
  sectionCountStyles,
  sectionLabelBase,
  WORKSTREAM_SIDE_INSET_PX,
} from '../styles/sectionStyles'

function PendingIntentCard({ intent }) {
  return (
    <div style={styles.pendingCard}>
      <span style={styles.pendingDot} />
      <span style={styles.pendingText}>{intent.text}</span>
      <span style={styles.pendingStatus}>
        {intent.status === 'pending' ? 'Creating issue...' : 'Failed'}
      </span>
    </div>
  )
}

function PipelineFlow({ stageGroups }) {
  const { mergedCount, failedCount } = useMemo(() => {
    const merged = stageGroups.find(g => g.stage.key === 'merged')?.issues.length || 0
    const failed = stageGroups.reduce(
      (sum, g) => sum + g.issues.filter(i => i.overallStatus === 'failed').length, 0
    )
    return { mergedCount: merged, failedCount: failed }
  }, [stageGroups])

  return (
    <div style={styles.flowContainer} data-testid="pipeline-flow">
      <span style={styles.flowTitle}>Pipeline Flow</span>
      <div style={styles.flowConnector} />
      {stageGroups.map((group, idx) => (
        <React.Fragment key={group.stage.key}>
          <div style={styles.flowStage}>
            <span style={flowLabelStyles[group.stage.key]}>{group.stage.label}</span>
            {group.issues.length > 0 && (
              <div style={styles.flowDots}>
                {group.issues.map(issue => (
                  <span
                    key={issue.issueNumber}
                    style={
                      issue.overallStatus === 'active' ? flowDotActiveStyles[group.stage.key]
                      : issue.overallStatus === 'failed' ? flowDotFailedStyles[group.stage.key]
                      : issue.overallStatus === 'hitl' ? flowDotHitlStyles[group.stage.key]
                      : issue.overallStatus === 'queued' ? flowDotQueuedStyles[group.stage.key]
                      : flowDotStyles[group.stage.key]
                    }
                    title={`#${issue.issueNumber}`}
                    data-testid={`flow-dot-${issue.issueNumber}`}
                  />
                ))}
              </div>
            )}
          </div>
          {idx < stageGroups.length - 1 && <div style={styles.flowConnector} />}
        </React.Fragment>
      ))}
      {(mergedCount > 0 || failedCount > 0) && (
        <span style={styles.flowSummary} data-testid="flow-summary">
          {mergedCount > 0 && <span style={flowSummaryMergedStyle}>{mergedCount} merged</span>}
          {mergedCount > 0 && failedCount > 0 && <span style={flowSummaryDividerStyle}> · </span>}
          {failedCount > 0 && <span style={flowSummaryFailedStyle}>{failedCount} failed</span>}
        </span>
      )}
    </div>
  )
}

function StageSection({ stage, issues, workerCount, workerCap, intentMap, onRequestChanges, open, onToggle, enabled, dotColor, workers, prs }) {
  const activeCount = issues.filter(i => i.overallStatus === 'active').length
  const failedCount = issues.filter(i => i.overallStatus === 'failed').length
  const hitlCount = issues.filter(i => i.overallStatus === 'hitl').length
  const queuedCount = issues.filter(i => i.overallStatus === 'queued').length
  const hasRole = !!stage.role

  return (
    <div
      style={hasRole ? (enabled ? sectionEnabledStyle : sectionDisabledStyle) : styles.section}
      data-testid={`stage-section-${stage.key}`}
    >
      <div
        style={sectionHeaderStyles[stage.key]}
        onClick={onToggle}
        data-testid={`stage-header-${stage.key}`}
      >
        <span style={{ fontSize: 10 }}>{open ? '▾' : '▸'}</span>
        <span style={sectionLabelStyles[stage.key]}>{stage.label}</span>
        {hasRole && !enabled && (
          <span style={styles.disabledBadge} data-testid={`stage-disabled-${stage.key}`}>Disabled</span>
        )}
        <span style={sectionCountStyles[stage.key]}>
          {hasRole ? (
            <>
              <span style={activeCount > 0 ? styles.activeBadge : undefined}>{activeCount} active</span>
              <span> · {queuedCount} queued</span>
              {failedCount > 0 && <span style={styles.failedBadge}> · {failedCount} failed</span>}
              {hitlCount > 0 && <span style={styles.hitlBadge}> · {hitlCount} hitl</span>}
              <span>
                {workerCap != null
                  ? ` · ${workerCount}/${workerCap} workers`
                  : ` · ${workerCount} ${workerCount === 1 ? 'worker' : 'workers'}`}
              </span>
            </>
          ) : (
            <span>{issues.length} merged</span>
          )}
        </span>
        <span
          style={{ ...styles.statusDot, background: dotColor }}
          data-testid={`stage-dot-${stage.key}`}
        />
      </div>
      {open && issues.map(issue => (
        <StreamCard
          key={issue.issueNumber}
          issue={issue}
          intent={intentMap.get(issue.issueNumber)}
          defaultExpanded={issue.overallStatus === 'active'}
          onRequestChanges={onRequestChanges}
          transcript={findWorkerTranscript(workers, prs, stage.key, issue.issueNumber)}
        />
      ))}
    </div>
  )
}

/** Map pipeline stage key to its index in STAGE_KEYS for building synthetic stages. */
const STAGE_INDEX = Object.fromEntries(STAGE_KEYS.map((k, i) => [k, i]))

/**
 * Convert a PipelineIssue from the server into a StreamCard-compatible shape.
 * Builds a synthetic `stages` object based on current pipeline position.
 */
export function toStreamIssue(pipeIssue, stageKey, prs) {
  const currentIdx = STAGE_INDEX[stageKey] ?? 0
  const isActive = pipeIssue.status === 'active'
  const isDone = pipeIssue.status === 'done'
  const stages = {}
  for (let i = 0; i < STAGE_KEYS.length; i++) {
    const k = STAGE_KEYS[i]
    if (i < currentIdx) {
      stages[k] = { status: 'done', startTime: null, endTime: null, transcript: [] }
    } else if (i === currentIdx) {
      const currentStageStatus = isDone ? 'done'
        : isActive ? 'active'
        : pipeIssue.status === 'failed' ? 'failed'
        : pipeIssue.status === 'hitl' ? 'hitl'
        : 'queued'
      stages[k] = { status: currentStageStatus, startTime: null, endTime: null, transcript: [] }
    } else {
      stages[k] = { status: 'pending', startTime: null, endTime: null, transcript: [] }
    }
  }

  // Match PR from prs array
  const matchedPr = (prs || []).find(p => p.issue === pipeIssue.issue_number)
  const pr = matchedPr ? { number: matchedPr.pr, url: matchedPr.url || null } : null

  return {
    issueNumber: pipeIssue.issue_number,
    title: pipeIssue.title || `Issue #${pipeIssue.issue_number}`,
    issueUrl: pipeIssue.url || null,
    currentStage: stageKey,
    overallStatus: pipeIssue.status === 'hitl' ? 'hitl'
      : pipeIssue.status === 'failed' || pipeIssue.status === 'error' ? 'failed'
      : isDone ? 'done'
      : pipeIssue.status === 'active' ? 'active'
      : 'queued',
    startTime: null,
    endTime: null,
    pr,
    branch: `agent/issue-${pipeIssue.issue_number}`,
    stages,
  }
}

/**
 * Find the transcript array for a given issue in a pipeline stage.
 * Worker keys vary by stage: triage-{issue}, plan-{issue}, {issue} (implement), review-{pr}.
 */
export function findWorkerTranscript(workers, prs, stageKey, issueNumber) {
  if (!workers) return []
  let key
  switch (stageKey) {
    case 'triage':
      key = `triage-${issueNumber}`
      break
    case 'plan':
      key = `plan-${issueNumber}`
      break
    case 'implement':
      key = String(issueNumber)
      break
    case 'review': {
      const pr = (prs || []).find(p => p.issue === issueNumber)
      if (!pr) return []
      key = `review-${pr.pr}`
      break
    }
    default:
      return []
  }
  return workers[key]?.transcript || []
}

export function StreamView({ intents, expandedStages, onToggleStage, onRequestChanges }) {
  const { pipelineIssues, prs, stageStatus, workers } = useHydraFlow()

  // Match intents to issues by issueNumber
  const intentMap = useMemo(() => {
    const map = new Map()
    for (const intent of (intents || [])) {
      if (intent.issueNumber != null) {
        map.set(intent.issueNumber, intent)
      }
    }
    return map
  }, [intents])

  // Pending intents (not yet matched to an issue)
  const pendingIntents = useMemo(
    () => (intents || []).filter(i => i.status === 'pending' || (i.status === 'failed' && i.issueNumber == null)),
    [intents]
  )

  // Build stage groups from pipelineIssues
  const stageGroups = useMemo(() => {
    // Build merged issues from PRs that are merged
    const mergedFromPrs = (prs || [])
      .filter(p => p.merged && p.issue)
      .map(p => toStreamIssue(
        { issue_number: p.issue, title: p.title || `Issue #${p.issue}`, url: null, status: 'done' },
        'merged',
        prs,
      ))
    return PIPELINE_STAGES.map(stage => {
      let stageIssues
      if (stage.key === 'merged') {
        // Combine pipelineIssues.merged (if any) + merged PRs
        const pipelineMerged = (pipelineIssues.merged || []).map(pi => toStreamIssue(pi, 'merged', prs))
        const combined = [...pipelineMerged]
        for (const m of mergedFromPrs) {
          if (!combined.some(i => i.issueNumber === m.issueNumber)) {
            combined.push(m)
          }
        }
        stageIssues = combined
      } else {
        stageIssues = (pipelineIssues[stage.key] || []).map(pi => toStreamIssue(pi, stage.key, prs))
      }
      // Sort active-first
      stageIssues.sort((a, b) => {
        const aActive = a.overallStatus === 'active' ? 1 : 0
        const bActive = b.overallStatus === 'active' ? 1 : 0
        return bActive - aActive
      })
      return { stage, issues: stageIssues }
    })
  }, [pipelineIssues, prs])

  const handleToggleStage = useCallback((key) => {
    onToggleStage(prev => ({ ...prev, [key]: !prev[key] }))
  }, [onToggleStage])

  const totalIssues = stageGroups.reduce((sum, g) => sum + g.issues.length, 0)
  const hasAnyIssues = totalIssues > 0 || pendingIntents.length > 0

  return (
    <div style={styles.container}>
      {pendingIntents.map((intent, i) => (
        <PendingIntentCard key={`pending-${i}`} intent={intent} />
      ))}

      <PipelineFlow stageGroups={stageGroups} />

      {stageGroups.map(({ stage, issues: stageIssues }) => {
        const status = stageStatus[stage.key] || {}
        const enabled = status.enabled !== false
        const workerCount = status.workerCount || 0
        const workerCap = stage.role ? (stageStatus.workerCaps?.[stage.key] ?? null) : null
        let dotColor
        if (!stage.role) {
          dotColor = theme.green
        } else if (!enabled) {
          dotColor = theme.red
        } else if (workerCount > 0) {
          dotColor = theme.green
        } else {
          dotColor = theme.yellow
        }
        return (
          <StageSection
            key={stage.key}
            stage={stage}
            issues={stageIssues}
            workerCount={workerCount}
            workerCap={workerCap}
            intentMap={intentMap}
            onRequestChanges={stage.role ? onRequestChanges : undefined}
            open={!!expandedStages[stage.key]}
            onToggle={() => handleToggleStage(stage.key)}
            enabled={enabled}
            dotColor={dotColor}
            workers={workers}
            prs={prs}
          />
        )
      })}

      {!hasAnyIssues && (
        <div style={styles.empty}>
          No active work.
        </div>
      )}
    </div>
  )
}

// Pre-computed per-stage flow label/dot styles (avoids object spread in .map())
const flowLabelBase = { ...sectionLabelBase, flexShrink: 0 }

const dotBase = {
  display: 'inline-block',
  width: 8,
  height: 8,
  borderRadius: '50%',
  flexShrink: 0,
}

const flowDotBase = { ...dotBase, transition: 'all 0.3s ease' }


const flowLabelStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...flowLabelBase, color: s.color }])
)

const flowDotStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...flowDotBase, background: s.color }])
)

const flowDotQueuedStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...flowDotBase, background: s.subtleColor }])
)

const flowDotActiveStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, {
    ...flowDotBase,
    background: s.color,
    animation: PULSE_ANIMATION,
  }])
)

const flowDotFailedStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...flowDotBase, background: theme.red }])
)

const flowDotHitlStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...flowDotBase, background: theme.yellow }])
)

const flowSummaryMergedStyle = { color: theme.green }
const flowSummaryDividerStyle = { color: theme.textMuted }
const flowSummaryFailedStyle = { color: theme.red }

const styles = {
  container: {
    flex: 1,
    overflowY: 'auto',
    padding: 8,
  },
  flowContainer: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '8px 12px',
    margin: `0 ${WORKSTREAM_SIDE_INSET_PX}px 8px`,
    background: theme.surfaceInset,
    borderRadius: 8,
    border: `1px solid ${theme.border}`,
    overflowX: 'auto',
    flexWrap: 'nowrap',
  },
  flowStage: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    flexShrink: 0,
  },
  flowDots: {
    display: 'flex',
    gap: 4,
    alignItems: 'center',
  },
  flowConnector: {
    width: 16,
    height: 1,
    background: theme.border,
    flexShrink: 0,
  },
  flowTitle: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.textMuted,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    flexShrink: 0,
    whiteSpace: 'nowrap',
  },
  flowSummary: {
    fontSize: 10,
    color: theme.textMuted,
    flexShrink: 0,
    marginLeft: 4,
    display: 'flex',
    alignItems: 'center',
  },
  empty: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: 200,
    color: theme.textMuted,
    fontSize: 13,
  },
  section: {
    marginBottom: 4,
  },
  activeBadge: {
    fontWeight: 700,
  },
  failedBadge: {
    fontWeight: 700,
    color: theme.red,
  },
  hitlBadge: {
    fontWeight: 700,
    color: theme.yellow,
  },
  statusDot: dotBase,
  disabledBadge: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.red,
    background: theme.redSubtle,
    border: `1px solid ${theme.red}`,
    borderRadius: 10,
    padding: '1px 6px',
    textTransform: 'uppercase',
  },
  pendingCard: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '10px 12px',
    background: theme.intentBg,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    margin: `0 ${WORKSTREAM_SIDE_INSET_PX}px 8px`,
  },
  pendingDot: {
    ...dotBase,
    background: theme.accent,
    animation: PULSE_ANIMATION,
  },
  pendingText: {
    flex: 1,
    fontSize: 12,
    color: theme.text,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  pendingStatus: {
    fontSize: 10,
    color: theme.textMuted,
    flexShrink: 0,
  },
}

// Pre-computed section opacity variants (avoids object spread in StageSection render)
const sectionEnabledStyle = { ...styles.section, opacity: 1, transition: 'opacity 0.2s' }
const sectionDisabledStyle = { ...styles.section, opacity: 0.5, transition: 'opacity 0.2s' }
