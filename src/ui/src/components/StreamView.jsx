import React, { useMemo, useCallback, useState } from 'react'
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
                {group.issues.map(issue => {
                  const isEpic = issue.isEpicChild || issue.epicNumber > 0
                  const dotStyles = isEpic ? epicFlowDotStyleMap : regularFlowDotStyleMap
                  const dotStyle =
                    issue.overallStatus === 'active' ? dotStyles.active[group.stage.key]
                    : issue.overallStatus === 'failed' ? dotStyles.failed[group.stage.key]
                    : issue.overallStatus === 'hitl' ? dotStyles.hitl[group.stage.key]
                    : issue.overallStatus === 'queued' ? dotStyles.queued[group.stage.key]
                    : dotStyles.base[group.stage.key]
                  return (
                    <span
                      key={issue.issueNumber}
                      style={dotStyle}
                      title={`#${issue.issueNumber}${isEpic ? ` (Epic #${issue.epicNumber})` : ''}`}
                      data-testid={`flow-dot-${issue.issueNumber}`}
                    >
                      {isEpic ? 'e' : null}
                    </span>
                  )
                })}
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

function EpicContainer({ epicNumber, issues, children }) {
  const activeCount = issues.filter(i => i.overallStatus === 'active').length
  return (
    <div style={epicContainerStyles.wrapper}>
      <div style={epicContainerStyles.header}>
        <span style={epicContainerStyles.badge}>Epic #{epicNumber}</span>
        <span style={epicContainerStyles.progress}>
          {activeCount} / {issues.length} active
        </span>
        {activeCount > 0 && <span style={epicContainerStyles.pulse} />}
      </div>
      <div style={epicContainerStyles.children}>
        {children}
      </div>
    </div>
  )
}

function StageSection({ stage, issues, workerCount, workerCap, intentMap, onRequestChanges, open, onToggle, enabled, dotColor, workers, prs }) {
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
              <span>{queuedCount} queued</span>
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
      {open && (() => {
        // Group epic children by epicNumber, keep standalone separate
        const epicGroups = {}
        const standalone = []
        for (const issue of issues) {
          if (issue.isEpicChild && issue.epicNumber > 0) {
            if (!epicGroups[issue.epicNumber]) epicGroups[issue.epicNumber] = []
            epicGroups[issue.epicNumber].push(issue)
          } else {
            standalone.push(issue)
          }
        }
        return (
          <>
            {standalone.map(issue => (
              <StreamCard
                key={issue.issueNumber}
                issue={issue}
                intent={intentMap.get(issue.issueNumber)}
                defaultExpanded={issue.overallStatus === 'active'}
                onRequestChanges={onRequestChanges}
                transcript={findWorkerTranscript(workers, prs, stage.key, issue.issueNumber)}
              />
            ))}
            {Object.entries(epicGroups).map(([epicNum, epicIssues]) => (
              <EpicContainer key={`epic-${epicNum}`} epicNumber={Number(epicNum)} issues={epicIssues}>
                {epicIssues.map(issue => (
                  <StreamCard
                    key={issue.issueNumber}
                    issue={issue}
                    intent={intentMap.get(issue.issueNumber)}
                    defaultExpanded={issue.overallStatus === 'active'}
                    onRequestChanges={onRequestChanges}
                    transcript={findWorkerTranscript(workers, prs, stage.key, issue.issueNumber)}
                  />
                ))}
              </EpicContainer>
            ))}
          </>
        )
      })()}
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
    epicNumber: pipeIssue.epic_number || 0,
    isEpicChild: pipeIssue.is_epic_child || false,
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

function EpicChildRow({ child }) {
  const dotColor = child.is_completed ? theme.green : child.is_failed ? theme.red : theme.textMuted
  return (
    <div style={epicPanelStyles.childRow}>
      <span style={{ ...epicPanelStyles.childDot, background: dotColor }} />
      <a
        href={child.url}
        target="_blank"
        rel="noopener noreferrer"
        style={epicPanelStyles.childLink}
      >
        #{child.issue_number}
      </a>
      <span style={epicPanelStyles.childTitle}>{child.title || `Issue #${child.issue_number}`}</span>
      {child.is_completed && <span style={epicPanelStyles.childBadgeDone}>done</span>}
      {child.is_failed && <span style={epicPanelStyles.childBadgeFailed}>failed</span>}
    </div>
  )
}

function EpicRow({ epic, config }) {
  const [expanded, setExpanded] = useState(false)
  const [children, setChildren] = useState(null)
  const [loading, setLoading] = useState(false)

  const pct = epic.percent_complete || 0
  const statusStyle = epicStatusStyles[epic.status] || epicStatusStyles.active
  const repo = config?.repo || ''
  const epicUrl = repo ? `https://github.com/${repo}/issues/${epic.epic_number}` : ''

  const handleToggle = useCallback(async () => {
    if (!expanded && children === null) {
      setLoading(true)
      try {
        const res = await fetch(`/api/epics/${epic.epic_number}`)
        if (res.ok) {
          const detail = await res.json()
          setChildren(detail.children || [])
        }
      } catch { /* ignore */ }
      setLoading(false)
    }
    setExpanded(prev => !prev)
  }, [expanded, children, epic.epic_number])

  return (
    <div style={epicPanelStyles.row}>
      <div
        style={epicPanelStyles.rowTop}
        onClick={handleToggle}
        role="button"
        tabIndex={0}
      >
        <span style={epicPanelStyles.chevron}>{expanded ? '\u25BE' : '\u25B8'}</span>
        {epicUrl ? (
          <a
            href={epicUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={epicPanelStyles.epicLink}
            onClick={e => e.stopPropagation()}
          >
            #{epic.epic_number}
          </a>
        ) : (
          <span style={epicPanelStyles.epicLabel}>#{epic.epic_number}</span>
        )}
        <span style={epicPanelStyles.epicTitle}>{epic.title}</span>
        {epic.auto_decomposed && <span style={epicPanelStyles.autoBadge}>auto</span>}
        <span style={statusStyle}>{epic.status}</span>
      </div>
      <div style={epicPanelStyles.barTrack}>
        {epic.completed > 0 && (
          <div style={{ ...epicPanelStyles.barGreen, width: `${(epic.completed / epic.total_children) * 100}%` }} />
        )}
        {epic.failed > 0 && (
          <div style={{ ...epicPanelStyles.barRed, width: `${(epic.failed / epic.total_children) * 100}%` }} />
        )}
      </div>
      <span style={epicPanelStyles.progress}>
        {epic.completed}/{epic.total_children} done
        {epic.failed > 0 && ` \u00B7 ${epic.failed} failed`}
        {` \u00B7 ${Math.round(pct)}%`}
        {epic.child_issues?.length > 0 && ` \u00B7 ${epic.child_issues.length} issues`}
      </span>
      {expanded && (
        <div style={epicPanelStyles.childList}>
          {loading && <span style={epicPanelStyles.childLoading}>Loading...</span>}
          {children && children.length > 0 && children.map(child => (
            <EpicChildRow key={child.issue_number} child={child} />
          ))}
          {children && children.length === 0 && !loading && (
            <span style={epicPanelStyles.childLoading}>No child issues found</span>
          )}
        </div>
      )}
    </div>
  )
}

function EpicOverviewPanel({ epics, config }) {
  if (!epics || epics.length === 0) return null

  const active = epics.filter(e => e.status !== 'completed')
  const completed = epics.filter(e => e.status === 'completed')

  return (
    <div style={epicPanelStyles.wrapper}>
      <div style={epicPanelStyles.header}>
        <span style={epicPanelStyles.title}>Epics</span>
        <span style={epicPanelStyles.count}>{epics.length}</span>
        {active.length > 0 && active.length !== epics.length && (
          <span style={epicPanelStyles.activeCount}>{active.length} active</span>
        )}
      </div>
      {active.map(epic => (
        <EpicRow key={epic.epic_number} epic={epic} config={config} />
      ))}
      {completed.length > 0 && (
        <>
          <div style={epicPanelStyles.completedDivider}>
            <span style={epicPanelStyles.completedLabel}>Completed ({completed.length})</span>
          </div>
          {completed.map(epic => (
            <EpicRow key={epic.epic_number} epic={epic} config={config} />
          ))}
        </>
      )}
    </div>
  )
}

export function StreamView({ intents, expandedStages, onToggleStage, onRequestChanges }) {
  const { pipelineIssues, prs, stageStatus, workers, epics, config } = useHydraFlow()

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

      <EpicOverviewPanel epics={epics} config={config} />

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

// Epic dot styles — 12px circles with centered "e" text
const epicDotBase = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: 12,
  height: 12,
  borderRadius: '50%',
  flexShrink: 0,
  fontSize: 7,
  fontWeight: 700,
  color: theme.bg,
  transition: 'all 0.3s ease',
}

const epicFlowDotStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...epicDotBase, background: s.color }])
)
const epicFlowDotQueuedStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...epicDotBase, background: s.subtleColor }])
)
const epicFlowDotActiveStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, {
    ...epicDotBase,
    background: s.color,
    animation: PULSE_ANIMATION,
  }])
)
const epicFlowDotFailedStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...epicDotBase, background: theme.red }])
)
const epicFlowDotHitlStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...epicDotBase, background: theme.yellow }])
)

// Grouped style maps for quick lookup in render
const regularFlowDotStyleMap = {
  base: flowDotStyles,
  queued: flowDotQueuedStyles,
  active: flowDotActiveStyles,
  failed: flowDotFailedStyles,
  hitl: flowDotHitlStyles,
}
const epicFlowDotStyleMap = {
  base: epicFlowDotStyles,
  queued: epicFlowDotQueuedStyles,
  active: epicFlowDotActiveStyles,
  failed: epicFlowDotFailedStyles,
  hitl: epicFlowDotHitlStyles,
}

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

const epicContainerStyles = {
  wrapper: {
    borderLeft: `3px solid ${theme.purple}`,
    background: theme.surfaceInset,
    borderRadius: 8,
    marginBottom: 4,
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '4px 12px',
    background: theme.purpleSubtle,
  },
  badge: {
    fontSize: 10,
    fontWeight: 700,
    color: theme.purple,
  },
  progress: {
    fontSize: 10,
    color: theme.textMuted,
  },
  pulse: {
    ...dotBase,
    width: 6,
    height: 6,
    background: theme.purple,
    animation: PULSE_ANIMATION,
  },
  children: {
    padding: 4,
  },
}

const epicPanelStyles = {
  wrapper: {
    background: theme.surfaceInset,
    borderRadius: 8,
    padding: '8px 12px',
    marginBottom: 8,
    borderLeft: `3px solid ${theme.purple}`,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  title: {
    fontSize: 12,
    fontWeight: 700,
    color: theme.textBright,
  },
  count: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.purple,
    background: theme.purpleSubtle,
    borderRadius: 8,
    padding: '1px 6px',
  },
  activeCount: {
    fontSize: 10,
    color: theme.textMuted,
  },
  row: {
    marginBottom: 8,
  },
  rowTop: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4,
    cursor: 'pointer',
  },
  chevron: {
    fontSize: 10,
    color: theme.textMuted,
    flexShrink: 0,
    width: 10,
  },
  epicLabel: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.purple,
    flexShrink: 0,
  },
  epicLink: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.purple,
    flexShrink: 0,
    textDecoration: 'none',
    cursor: 'pointer',
  },
  epicTitle: {
    fontSize: 11,
    color: theme.text,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    flex: 1,
  },
  autoBadge: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.accent,
    background: theme.accentSubtle,
    borderRadius: 4,
    padding: '1px 4px',
    flexShrink: 0,
  },
  barTrack: {
    display: 'flex',
    height: 4,
    background: theme.border,
    borderRadius: 2,
    overflow: 'hidden',
    marginBottom: 2,
    marginLeft: 18,
  },
  barGreen: {
    height: '100%',
    background: theme.green,
    transition: 'width 0.3s ease',
  },
  barRed: {
    height: '100%',
    background: theme.red,
    transition: 'width 0.3s ease',
  },
  progress: {
    fontSize: 10,
    color: theme.textMuted,
    marginLeft: 18,
  },
  childList: {
    marginLeft: 18,
    marginTop: 4,
    paddingLeft: 8,
    borderLeft: `1px solid ${theme.border}`,
  },
  childRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '2px 0',
  },
  childDot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    flexShrink: 0,
  },
  childLink: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.accent,
    textDecoration: 'none',
    flexShrink: 0,
  },
  childTitle: {
    fontSize: 10,
    color: theme.text,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    flex: 1,
  },
  childBadgeDone: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.green,
    background: theme.greenSubtle,
    borderRadius: 4,
    padding: '0 4px',
    flexShrink: 0,
  },
  childBadgeFailed: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.red,
    background: theme.redSubtle,
    borderRadius: 4,
    padding: '0 4px',
    flexShrink: 0,
  },
  childLoading: {
    fontSize: 10,
    color: theme.textMuted,
    fontStyle: 'italic',
  },
  completedDivider: {
    borderTop: `1px solid ${theme.border}`,
    marginTop: 4,
    paddingTop: 4,
    marginBottom: 4,
  },
  completedLabel: {
    fontSize: 10,
    color: theme.textMuted,
    fontWeight: 600,
  },
}

const epicStatusBase = {
  fontSize: 9,
  fontWeight: 600,
  padding: '1px 6px',
  borderRadius: 4,
  flexShrink: 0,
}

const epicStatusStyles = {
  active: { ...epicStatusBase, color: theme.green, background: theme.greenSubtle },
  completed: { ...epicStatusBase, color: theme.textMuted, background: theme.mutedSubtle },
  stale: { ...epicStatusBase, color: theme.yellow, background: theme.yellowSubtle },
  blocked: { ...epicStatusBase, color: theme.red, background: theme.redSubtle },
}


// Pre-computed section opacity variants (avoids object spread in StageSection render)
const sectionEnabledStyle = { ...styles.section, opacity: 1, transition: 'opacity 0.2s' }
const sectionDisabledStyle = { ...styles.section, opacity: 0.5, transition: 'opacity 0.2s' }
