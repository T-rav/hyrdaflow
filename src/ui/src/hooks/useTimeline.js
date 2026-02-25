import { useMemo, useState } from 'react'
import { PIPELINE_STAGES } from '../constants'

/** Canonical stage keys in lifecycle order. */
export const STAGE_KEYS = PIPELINE_STAGES.map(s => s.key)

/** Map stage key → { color, subtleColor, label }. */
export const STAGE_META = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { color: s.color, subtleColor: s.subtleColor, label: s.label }])
)

/**
 * Map event types to pipeline stage keys.
 * transcript_line is handled separately via its `source` field.
 */
const EVENT_TO_STAGE = {
  triage_update: 'triage',
  planner_update: 'plan',
  worker_update: 'implement',
  review_update: 'review',
  merge_update: 'merged',
}

/** Map worker `source` field (from transcript_line) to stage key. */
const SOURCE_TO_STAGE = {
  triage: 'triage',
  planner: 'plan',
  implementer: 'implement',
  reviewer: 'review',
}

/** Max transcript lines to keep per stage for preview. */
const MAX_TRANSCRIPT_LINES = 10

/**
 * Extract issue number from an event's data payload.
 * Returns null if not determinable.
 */
function extractIssueNumber(event) {
  const d = event.data
  if (!d) return null
  if (d.issue != null) return Number(d.issue)
  if (d.number != null) return Number(d.number)
  return null
}

/**
 * Format a duration in milliseconds to a human-readable string.
 * Returns "< 1s" for very short durations, "Xs", "Xm Ys", or "Xh Ym".
 */
export function formatDuration(ms) {
  if (ms == null || ms < 0) return ''
  if (ms < 1000) return '< 1s'
  const totalSeconds = Math.floor(ms / 1000)
  if (totalSeconds < 60) return `${totalSeconds}s`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes < 60) return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const remainMinutes = minutes % 60
  return remainMinutes > 0 ? `${hours}h ${remainMinutes}m` : `${hours}h`
}

/**
 * Create a fresh stage entry.
 */
function freshStage() {
  return { status: 'pending', startTime: null, endTime: null, transcript: [] }
}

/**
 * Derive per-issue timeline objects from raw events and workers state.
 *
 * @param {Array} events  — event array (newest first, from useHydraFlowSocket)
 * @param {Object} workers — workers map from useHydraFlowSocket
 * @param {Array} prs — PRs array from useHydraFlowSocket
 * @returns {Array} array of issue timeline objects
 */
export function deriveIssueTimelines(events, workers, prs) {
  const issueMap = new Map()

  function getOrCreate(issueNum) {
    if (issueMap.has(issueNum)) return issueMap.get(issueNum)
    const entry = {
      issueNumber: issueNum,
      title: `Issue #${issueNum}`,
      currentStage: null,
      overallStatus: 'pending',
      startTime: null,
      endTime: null,
      pr: null,
      branch: `agent/issue-${issueNum}`,
      stages: Object.fromEntries(STAGE_KEYS.map(k => [k, freshStage()])),
    }
    issueMap.set(issueNum, entry)
    return entry
  }

  // Process events oldest-first for correct chronological ordering
  const chronological = [...events].reverse()

  for (const event of chronological) {
    const stage = EVENT_TO_STAGE[event.type]
    const issueNum = extractIssueNumber(event)

    if (event.type === 'issue_created' && issueNum != null) {
      const entry = getOrCreate(issueNum)
      if (event.data.title) entry.title = event.data.title
      if (event.timestamp && (!entry.startTime || event.timestamp < entry.startTime)) {
        entry.startTime = event.timestamp
      }
      continue
    }

    if (event.type === 'pr_created' && issueNum != null) {
      const entry = getOrCreate(issueNum)
      entry.pr = { number: event.data.pr, url: event.data.url || null }
      continue
    }

    if (event.type === 'transcript_line') {
      const source = event.data?.source
      const tStage = SOURCE_TO_STAGE[source]
      const tIssue = event.data?.issue != null ? Number(event.data.issue) : null
      if (tStage && tIssue != null) {
        const entry = getOrCreate(tIssue)
        const stageData = entry.stages[tStage]
        if (stageData.transcript.length < MAX_TRANSCRIPT_LINES) {
          stageData.transcript.push(event.data.line)
        }
      }
      continue
    }

    if (!stage || issueNum == null) continue

    const entry = getOrCreate(issueNum)
    const stageData = entry.stages[stage]
    const ts = event.timestamp

    // Track stage start time
    if (!stageData.startTime && ts) {
      stageData.startTime = ts
    }

    // Track overall issue start time
    if (ts && (!entry.startTime || ts < entry.startTime)) {
      entry.startTime = ts
    }

    // Update stage status from event data
    const eventStatus = event.data?.status
    if (eventStatus === 'done' || eventStatus === 'merged') {
      stageData.status = 'done'
      if (ts) stageData.endTime = ts
    } else if (eventStatus === 'failed' || eventStatus === 'error') {
      stageData.status = 'failed'
      if (ts) stageData.endTime = ts
    } else if (eventStatus === 'escalated' || eventStatus === 'hitl') {
      stageData.status = 'hitl'
      if (ts) stageData.endTime = ts
    } else if (eventStatus && stageData.status === 'pending') {
      stageData.status = 'active'
    }

    // Update title from worker/review data
    if (event.data?.title) {
      entry.title = event.data.title
    }
  }

  // Augment from workers state for real-time status
  for (const [key, worker] of Object.entries(workers)) {
    let issueNum = null
    let stage = null

    if (key.startsWith('triage-')) {
      issueNum = Number(key.slice(7))
      stage = 'triage'
    } else if (key.startsWith('plan-')) {
      issueNum = Number(key.slice(5))
      stage = 'plan'
    } else if (key.startsWith('review-')) {
      // Review workers are keyed by PR number; extract issue from title
      const titleMatch = worker.title?.match(/Issue #(\d+)/)
      if (titleMatch) {
        issueNum = Number(titleMatch[1])
        stage = 'review'
      }
    } else if (!isNaN(Number(key))) {
      issueNum = Number(key)
      stage = 'implement'
    }

    if (issueNum == null || stage == null) continue

    const entry = getOrCreate(issueNum)
    const stageData = entry.stages[stage]

    // Update title from worker title
    if (worker.title && entry.title === `Issue #${issueNum}`) {
      entry.title = worker.title
    }

    // Update branch from worker
    if (worker.branch) {
      entry.branch = worker.branch
    }

    // Update PR from worker
    if (worker.pr && !entry.pr) {
      entry.pr = { number: worker.pr, url: null }
    }

    // If stage doesn't have a startTime from events yet, mark it active from workers
    if (stageData.status === 'pending' && worker.status && worker.status !== 'queued') {
      stageData.status = 'active'
    }

    // Override status with live worker status
    if (worker.status === 'done') {
      stageData.status = 'done'
    } else if (worker.status === 'failed') {
      stageData.status = 'failed'
    } else if (worker.status === 'escalated') {
      stageData.status = 'hitl'
    } else if (worker.status && worker.status !== 'queued' && stageData.status !== 'done' && stageData.status !== 'failed' && stageData.status !== 'hitl') {
      stageData.status = 'active'
    }

    // Merge transcript from worker (take latest lines)
    if (worker.transcript?.length > 0 && stageData.transcript.length === 0) {
      stageData.transcript = worker.transcript.slice(-MAX_TRANSCRIPT_LINES)
    }
  }

  // Augment from prs array
  for (const pr of (prs || [])) {
    if (pr.issue == null) continue
    const issueNum = Number(pr.issue)
    if (!issueMap.has(issueNum)) continue
    const entry = issueMap.get(issueNum)
    if (!entry.pr) {
      entry.pr = { number: pr.pr, url: pr.url || null }
    }
    if (pr.merged) {
      entry.stages.merged.status = 'done'
    }
  }

  // Compute currentStage and overallStatus for each issue
  for (const entry of issueMap.values()) {
    let activeStage = null
    let lastDoneIndex = -1
    let hasFailed = false
    let hasHitl = false
    let hasActive = false
    let latestEndTime = null

    for (let i = 0; i < STAGE_KEYS.length; i++) {
      const stageKey = STAGE_KEYS[i]
      const s = entry.stages[stageKey]
      if (s.status === 'active') {
        activeStage = stageKey
        hasActive = true
      }
      if (s.status === 'done') lastDoneIndex = i
      if (s.status === 'failed') hasFailed = true
      if (s.status === 'hitl') hasHitl = true
      if (s.endTime && (!latestEndTime || s.endTime > latestEndTime)) {
        latestEndTime = s.endTime
      }
    }

    // Current stage: prefer the actively running stage, otherwise
    // advance to the next stage after the last completed one
    if (activeStage) {
      entry.currentStage = activeStage
    } else if (lastDoneIndex >= 0 && lastDoneIndex < STAGE_KEYS.length - 1) {
      entry.currentStage = STAGE_KEYS[lastDoneIndex + 1]
    } else if (lastDoneIndex === STAGE_KEYS.length - 1) {
      entry.currentStage = STAGE_KEYS[lastDoneIndex] // merged
    } else {
      entry.currentStage = 'triage'
    }

    if (hasFailed) {
      entry.overallStatus = 'failed'
    } else if (hasHitl) {
      entry.overallStatus = 'hitl'
    } else if (entry.stages.merged.status === 'done') {
      entry.overallStatus = 'done'
      entry.endTime = latestEndTime
    } else if (hasActive) {
      entry.overallStatus = 'active'
    } else {
      entry.overallStatus = 'active'
    }
  }

  return Array.from(issueMap.values())
}

/**
 * Apply filter and sort to an array of issue timelines.
 */
export function applyFiltersAndSort(issues, filterStage, filterStatus, sortBy) {
  let result = issues

  if (filterStage && filterStage !== 'all') {
    result = result.filter(i => i.currentStage === filterStage)
  }
  if (filterStatus && filterStatus !== 'all') {
    result = result.filter(i => i.overallStatus === filterStatus)
  }

  if (sortBy === 'issue') {
    result = [...result].sort((a, b) => b.issueNumber - a.issueNumber)
  } else {
    // Sort by recency — most recently updated first
    result = [...result].sort((a, b) => {
      const aTime = a.endTime || a.startTime || ''
      const bTime = b.endTime || b.startTime || ''
      return bTime.localeCompare(aTime)
    })
  }

  return result
}

/**
 * Custom hook that derives timeline data from WebSocket state.
 *
 * @param {Array} events  — events array from useHydraFlowSocket
 * @param {Object} workers — workers map from useHydraFlowSocket
 * @param {Array} prs — PRs array from useHydraFlowSocket
 * @returns {{ issues, filterStage, setFilterStage, filterStatus, setFilterStatus, sortBy, setSortBy }}
 */
export function useTimeline(events, workers, prs) {
  const [filterStage, setFilterStage] = useState('all')
  const [filterStatus, setFilterStatus] = useState('all')
  const [sortBy, setSortBy] = useState('recency')

  const allIssues = useMemo(
    () => deriveIssueTimelines(events || [], workers || {}, prs || []),
    [events, workers, prs]
  )

  const issues = useMemo(
    () => applyFiltersAndSort(allIssues, filterStage, filterStatus, sortBy),
    [allIssues, filterStage, filterStatus, sortBy]
  )

  return {
    issues,
    filterStage, setFilterStage,
    filterStatus, setFilterStatus,
    sortBy, setSortBy,
  }
}
