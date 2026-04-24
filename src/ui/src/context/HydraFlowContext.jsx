import React, { createContext, useContext, useEffect, useRef, useCallback, useReducer, useMemo } from 'react'
import { MAX_EVENTS, SYSTEM_WORKER_INTERVALS } from '../constants'
import { deriveStageStatus } from '../hooks/useStageStatus'

const emptyPipeline = {
  triage: [],
  plan: [],
  implement: [],
  review: [],
  hitl: [],
  merged: [],
}

export const initialState = {
  connected: false,
  lastSeenId: -1,  // Monotonic event ID for deduplication on reconnect
  phase: 'idle',
  orchestratorStatus: 'idle',
  creditsPausedUntil: null,
  workers: {},
  prs: [],
  reviews: [],
  sessionPrsCount: 0,
  lifetimeStats: null,
  queueStats: null,
  config: null,
  events: [],
  hitlItems: [],
  hitlEscalation: null,
  humanInputRequests: {},
  backgroundWorkers: [],
  adrDrafts: [],
  metrics: null,
  systemAlert: null,
  intents: [],
  epics: [],
  epicReleasing: null, // { epicNumber, progress, total } or null
  githubMetrics: null,
  metricsHistory: null,
  pipelineIssues: { ...emptyPipeline },
  pipelineStats: null,
  pipelinePollerLastRun: null,
  sessions: [],
  currentSessionId: null,
  selectedRepoSlug: null,
  selectedRepoSlugRaw: null,
  canRegisterRepos: false,
  supervisedRepos: [],
  runtimes: [],
  issueHistory: null,
  harnessInsights: null,
  reviewInsights: null,
  retrospectives: null,
  troubleshooting: null,
  trackedReports: [],
}

function normalizeRepoSlug(value) {
  if (value == null) return null
  return String(value).trim().replace(/[\\/]+/g, '-') || null
}

function isDuplicate(state, action) {
  const eventId = action.id ?? -1
  return eventId !== -1 && eventId <= state.lastSeenId
}

function addEvent(state, action) {
  const eventId = action.id ?? -1
  if (isDuplicate(state, action)) return state
  const event = { type: action.type, timestamp: action.timestamp, data: action.data, id: eventId }
  return {
    ...state,
    lastSeenId: eventId !== -1 ? eventId : state.lastSeenId,
    events: [event, ...state.events].slice(0, MAX_EVENTS),
  }
}

function mergeStageIssues(existingIssues, incomingIssues) {
  // Server snapshot is authoritative: items absent from incoming are removed
  // (prevents ghost cards) and incoming fields (including status) override
  // local state for items still present.
  const existingById = new Map(
    (existingIssues || [])
      .filter(item => item?.issue_number != null)
      .map(item => [item.issue_number, item])
  )
  return (incomingIssues || []).map(item => {
    if (item?.issue_number == null) return item
    const existing = existingById.get(item.issue_number)
    return existing ? { ...existing, ...item } : item
  })
}

export function reducer(state, action) {
  switch (action.type) {
    case 'CONNECTED':
      return { ...state, connected: true }
    case 'DISCONNECTED':
      return { ...state, connected: false }

    case 'phase_change': {
      const newPhase = action.data.phase
      const isNewRun = (newPhase === 'plan' || newPhase === 'implement')
        && (state.phase === 'idle' || state.phase === 'done')
      if (isNewRun) {
        return {
          ...addEvent(state, action),
          phase: newPhase,
          workers: {},
          prs: [],
          reviews: [],
          sessionPrsCount: 0,
          hitlItems: [],
          hitlEscalation: null,
          lastSeenId: -1,
        }
      }
      return { ...addEvent(state, action), phase: newPhase }
    }

    case 'orchestrator_status': {
      const newStatus = action.data.status
      const isStopped = newStatus === 'idle' || newStatus === 'done' || newStatus === 'stopping'
      const isSessionStart = newStatus === 'running' && action.data.reset === true
      const creditsPaused = action.data.credits_paused_until || null
      // Clear the system alert banner when credits are no longer paused
      const clearAlert = !creditsPaused && state.systemAlert?.message?.includes('Credit limit')
      return {
        ...addEvent(state, action),
        orchestratorStatus: newStatus,
        creditsPausedUntil: creditsPaused,
        ...(clearAlert ? { systemAlert: null } : {}),
        ...(isStopped ? {
          workers: {},
          sessionPrsCount: 0,
        } : {}),
        ...(isSessionStart ? {
          workers: {},
          prs: [],
          reviews: [],
          sessionPrsCount: 0,
          hitlItems: [],
          hitlEscalation: null,
          lastSeenId: -1,
          sessions: [],
          pipelineIssues: { ...emptyPipeline },
          intents: [],
          humanInputRequests: {},
        } : {}),
      }
    }

    case 'worker_update': {
      const { issue, status, worker, role } = action.data
      const existing = state.workers[issue] || {
        status: 'queued',
        worker,
        role: role || 'implementer',
        title: `Issue #${issue}`,
        branch: `agent/issue-${issue}`,
        transcript: [],
        pr: null,
      }
      return {
        ...state,
        workers: {
          ...state.workers,
          [issue]: { ...existing, status, worker, role: role || existing.role },
        },
      }
    }

    case 'transcript_line': {
      if (isDuplicate(state, action)) return state
      let key = action.data.issue || action.data.pr
      let role = 'implementer'
      if (action.data.source === 'triage') {
        key = `triage-${action.data.issue}`
        role = 'triage'
      } else if (action.data.source === 'planner') {
        key = `plan-${action.data.issue}`
        role = 'planner'
      } else if (action.data.source === 'reviewer') {
        key = `review-${action.data.pr}`
        role = 'reviewer'
      }
      if (!key) return addEvent(state, action)
      const w = state.workers[key] || {
        status: 'active',
        worker: 0,
        role,
        title: `Issue #${action.data.issue || action.data.pr || ''}`,
        branch: '',
        transcript: [],
        pr: action.data.pr || null,
      }
      return {
        ...addEvent(state, action),
        workers: {
          ...state.workers,
          [key]: { ...w, transcript: [...w.transcript, action.data.line] },
        },
      }
    }

    case 'agent_activity': {
      if (isDuplicate(state, action)) return state
      const { source } = action.data
      let actKey = action.data.issue || action.data.pr
      if (source === 'triage') actKey = `triage-${action.data.issue}`
      else if (source === 'planner') actKey = `plan-${action.data.issue}`
      else if (source === 'reviewer') actKey = `review-${action.data.pr}`
      if (!actKey) return addEvent(state, action)
      const actWorker = state.workers[actKey]
      if (!actWorker) return addEvent(state, action)
      return {
        ...addEvent(state, action),
        workers: {
          ...state.workers,
          [actKey]: {
            ...actWorker,
            lastActivity: {
              activityType: action.data.activity_type,
              toolName: action.data.tool_name,
              summary: action.data.summary,
              detail: action.data.detail || null,
              timestamp: action.timestamp,
            },
          },
        },
      }
    }

    case 'pr_created': {
      const exists = state.prs.some(p => p.pr === action.data.pr)
      return {
        ...addEvent(state, action),
        prs: exists ? state.prs : [...state.prs, action.data],
        sessionPrsCount: exists ? state.sessionPrsCount : state.sessionPrsCount + 1,
      }
    }

    case 'triage_update': {
      const triageKey = `triage-${action.data.issue}`
      const triageStatus = action.data.status
      const triageWorker = {
        status: triageStatus,
        worker: action.data.worker,
        role: 'triage',
        title: `Triage Issue #${action.data.issue}`,
        branch: '',
        transcript: [],
        pr: null,
      }
      const existingTriage = state.workers[triageKey]
      return {
        ...addEvent(state, action),
        workers: {
          ...state.workers,
          [triageKey]: existingTriage
            ? { ...existingTriage, status: triageStatus }
            : triageWorker,
        },
      }
    }

    case 'planner_update': {
      const planKey = `plan-${action.data.issue}`
      const planStatus = action.data.status
      const planWorker = {
        status: planStatus,
        worker: action.data.worker,
        role: 'planner',
        title: `Plan Issue #${action.data.issue}`,
        branch: '',
        transcript: [],
        pr: null,
      }
      const existingPlanner = state.workers[planKey]
      return {
        ...addEvent(state, action),
        workers: {
          ...state.workers,
          [planKey]: existingPlanner
            ? { ...existingPlanner, status: planStatus }
            : planWorker,
        },
      }
    }

    case 'review_update': {
      const reviewKey = `review-${action.data.pr}`
      const reviewStatus = action.data.status
      const reviewWorker = {
        status: reviewStatus,
        worker: action.data.worker,
        role: 'reviewer',
        title: `PR #${action.data.pr} (Issue #${action.data.issue})`,
        branch: '',
        transcript: [],
        pr: action.data.pr,
      }
      const existingReviewer = state.workers[reviewKey]
      const updatedWorkers = {
        ...state.workers,
        [reviewKey]: existingReviewer
          ? { ...existingReviewer, status: reviewStatus }
          : reviewWorker,
      }
      if (action.data.status === 'done') {
        return {
          ...addEvent(state, action),
          workers: updatedWorkers,
          reviews: [...state.reviews, action.data],
        }
      }
      return { ...addEvent(state, action), workers: updatedWorkers }
    }

    case 'merge_update': {
      const isMerged = action.data.status === 'merged'
      if (!isMerged || !action.data.pr) {
        return { ...addEvent(state, action), prs: state.prs }
      }
      const found = state.prs.some(p => p.pr === action.data.pr)
      const updatedPrs = found
        ? state.prs.map(p => {
            if (p.pr !== action.data.pr) return p
            const updates = { ...p, merged: true }
            if (action.data.title) updates.title = action.data.title
            return updates
          })
        : [...state.prs, {
            pr: action.data.pr,
            merged: true,
            ...(action.data.title ? { title: action.data.title } : {}),
            ...(action.data.issue ? { issue: action.data.issue } : {}),
          }]
      return {
        ...addEvent(state, action),
        prs: updatedPrs,
      }
    }

    case 'LIFETIME_STATS':
      return { ...state, lifetimeStats: action.data }

    case 'CONFIG':
      return { ...state, config: action.data }

    case 'EXISTING_PRS': {
      // Backend provides merged flag on PRs — use as-is.
      // Merged state is tracked authoritatively in the pipeline snapshot,
      // so we no longer preserve session-volatile merged PRs here.
      return { ...state, prs: action.data || [] }
    }

    case 'HITL_ITEMS':
      return { ...state, hitlItems: action.data }

    case 'HUMAN_INPUT_REQUESTS':
      return { ...state, humanInputRequests: action.data }

    case 'HUMAN_INPUT_SUBMITTED': {
      const next = { ...state.humanInputRequests }
      delete next[action.data.issueNumber]
      return { ...state, humanInputRequests: next }
    }

    case 'hitl_escalation': {
      // Automated escalation: worker is keyed by `review-<pr>`
      // Manual escalation (request-changes): no pr, worker keyed by issue number
      const hitlReviewKey = `review-${action.data.pr}`
      const hitlReviewWorker = action.data.pr != null ? state.workers[hitlReviewKey] : null
      const hitlIssueWorker = action.data.issue != null ? state.workers[action.data.issue] : null
      let hitlWorkers = state.workers
      if (hitlReviewWorker) {
        hitlWorkers = { ...state.workers, [hitlReviewKey]: { ...hitlReviewWorker, status: 'escalated' } }
      } else if (hitlIssueWorker) {
        hitlWorkers = { ...state.workers, [action.data.issue]: { ...hitlIssueWorker, status: 'escalated' } }
      }
      return {
        ...addEvent(state, action),
        workers: hitlWorkers,
        hitlEscalation: action.data,
      }
    }

    case 'hitl_update':
      return {
        ...addEvent(state, action),
        hitlUpdate: action.data,
      }

    case 'queue_update':
      return { ...addEvent(state, action), queueStats: action.data }

    case 'QUEUE_STATS':
      return { ...state, queueStats: action.data }

    case 'background_worker_status': {
      const { worker, status, last_run, details } = action.data
      const prev = state.backgroundWorkers.find(w => w.name === worker)
      const rest = state.backgroundWorkers.filter(w => w.name !== worker)
      // Preserve local enabled flag if backend doesn't send one
      const enabled = action.data.enabled !== undefined ? action.data.enabled : (prev?.enabled ?? true)
      // Heartbeat events don't carry interval_seconds — preserve from prior state
      const interval_seconds = action.data.interval_seconds ?? prev?.interval_seconds ?? null
      return {
        ...addEvent(state, action),
        backgroundWorkers: [...rest, { name: worker, status, last_run, details, enabled, interval_seconds }],
      }
    }

    case 'TOGGLE_BG_WORKER': {
      const { name: toggleName, enabled: toggleEnabled } = action.data
      const existingWorker = state.backgroundWorkers.find(w => w.name === toggleName)
      if (existingWorker) {
        return {
          ...state,
          backgroundWorkers: state.backgroundWorkers.map(w =>
            w.name === toggleName ? { ...w, enabled: toggleEnabled } : w
          ),
        }
      }
      // Worker not yet in state — create a stub entry
      return {
        ...state,
        backgroundWorkers: [...state.backgroundWorkers, { name: toggleName, status: 'ok', enabled: toggleEnabled, last_run: null, details: {} }],
      }
    }

    case 'BACKGROUND_WORKERS': {
      // Merge backend data with local toggle overrides
      const localOverrides = Object.fromEntries(
        state.backgroundWorkers.map(w => [w.name, w.enabled])
      )
      const merged = action.data.map(w => ({
        ...w,
        enabled: localOverrides[w.name] !== undefined ? localOverrides[w.name] : w.enabled,
      }))
      return { ...state, backgroundWorkers: merged }
    }

    case 'UPDATE_BG_WORKER_INTERVAL': {
      const { name: intervalName, interval_seconds } = action.data
      const existingBw = state.backgroundWorkers.find(w => w.name === intervalName)
      if (existingBw) {
        return {
          ...state,
          backgroundWorkers: state.backgroundWorkers.map(w =>
            w.name === intervalName ? { ...w, interval_seconds } : w
          ),
        }
      }
      return {
        ...state,
        backgroundWorkers: [...state.backgroundWorkers, { name: intervalName, status: 'ok', enabled: true, last_run: null, interval_seconds, details: {} }],
      }
    }

    case 'METRICS':
      return { ...state, metrics: action.data }

    case 'GITHUB_METRICS':
      return { ...state, githubMetrics: action.data }

    case 'METRICS_HISTORY':
      return { ...state, metricsHistory: action.data }

    case 'metrics_update':
      return {
        ...addEvent(state, action),
        metrics: state.metrics
          ? { ...state.metrics, lifetime: { ...state.metrics.lifetime, ...action.data } }
          : state.metrics,
      }

    case 'epic_update': {
      const progress = action.data?.progress
      if (!progress) return addEvent(state, action)
      const epicNum = progress.epic_number
      const existingEpics = state.epics.filter(e => e.epic_number !== epicNum)
      return {
        ...addEvent(state, action),
        epics: [...existingEpics, progress],
      }
    }

    case 'EPICS':
      return { ...state, epics: action.data || [] }

    case 'EPIC_READY': {
      const readyNum = action.data?.epic_number
      if (!readyNum) return state
      return {
        ...state,
        epics: state.epics.map(e =>
          e.epic_number === readyNum ? { ...e, status: 'ready' } : e
        ),
      }
    }

    case 'EPIC_RELEASING': {
      // null data signals a clear (e.g. release failure revert)
      if (!action.data) return { ...state, epicReleasing: null }
      const releasingNum = action.data.epic_number
      if (!releasingNum) return state
      return {
        ...state,
        epicReleasing: {
          epicNumber: releasingNum,
          progress: action.data.progress || 0,
          total: action.data.total || 0,
        },
        epics: state.epics.map(e =>
          e.epic_number === releasingNum ? { ...e, status: 'releasing' } : e
        ),
      }
    }

    case 'EPIC_RELEASED': {
      const releasedNum = action.data?.epic_number
      if (!releasedNum) return state
      return {
        ...state,
        epicReleasing: null,
        epics: state.epics.map(e =>
          e.epic_number === releasedNum
            ? { ...e, status: 'released', version: action.data.version || '', released_at: action.data.released_at || new Date().toISOString() }
            : e
        ),
      }
    }

    case 'system_alert':
      return { ...addEvent(state, action), systemAlert: action.data }

    case 'CLEAR_SYSTEM_ALERT':
      return { ...state, systemAlert: null }

    case 'error':
      return addEvent(state, action)

    case 'BACKFILL_EVENTS': {
      const existingKeys = new Set(
        state.events.map(e => `${e.type}|${e.timestamp}`)
      )
      const newEvents = action.data
        .map(e => ({ type: e.type, timestamp: e.timestamp, data: e.data }))
        .filter(e => !existingKeys.has(`${e.type}|${e.timestamp}`))
      const merged = [...state.events, ...newEvents]
        .sort((a, b) => b.timestamp.localeCompare(a.timestamp))
        .slice(0, MAX_EVENTS)
      return { ...state, events: merged }
    }

    case 'PIPELINE_SNAPSHOT': {
      const incoming = action.data || {}
      const allStages = ['triage', 'discover', 'shape', 'plan', 'implement', 'review', 'hitl', 'merged']

      const nextStages = Object.fromEntries(allStages.map((key) => {
        if (!Object.prototype.hasOwnProperty.call(incoming, key)) {
          return [key, state.pipelineIssues[key] || []]
        }
        // Server snapshot is authoritative: reconcile stage membership so issues
        // absent from the snapshot are removed (eliminates ghost cards).
        return [key, mergeStageIssues(state.pipelineIssues[key], incoming[key] || [])]
      }))

      return {
        ...state,
        pipelineIssues: nextStages,
        pipelinePollerLastRun: new Date().toISOString(),
      }
    }

    case 'pipeline_stats':
    case 'PIPELINE_STATS': {
      return { ...state, pipelineStats: action.data }
    }

    case 'report_update':
    case 'REPORT_UPDATE': {
      // A tracked report changed status — update inline if we have a matching report,
      // otherwise the next poll cycle will pick it up.
      const reportId = action.data?.report_id
      const newStatus = action.data?.status
      if (!reportId || !newStatus) return state
      const updated = state.trackedReports.map(r =>
        r.id === reportId ? { ...r, status: newStatus } : r
      )
      return { ...state, trackedReports: updated }
    }

    case 'WS_PIPELINE_UPDATE': {
      const { issueNumber, fromStage, toStage, status: pipeStatus } = action.data
      const next = { ...state.pipelineIssues }

      // Remove from source stage if specified
      let foundInFrom = false
      if (fromStage && next[fromStage]) {
        const idx = next[fromStage].findIndex(i => i.issue_number === issueNumber)
        if (idx >= 0) {
          foundInFrom = true
          next[fromStage] = next[fromStage].filter((_, i) => i !== idx)
          // Add to target stage if specified
          if (toStage && next[toStage] !== undefined) {
            const moved = { issue_number: issueNumber, title: '', url: '', status: pipeStatus || 'queued' }
            next[toStage] = [...next[toStage], moved]
          }
        }
        // If not found in fromStage but toStage is merged, add anyway (item may have
        // been removed by a prior event like review_update done)
        if (!foundInFrom && toStage === 'merged') {
          const alreadyMerged = (next.merged || []).some(i => i.issue_number === issueNumber)
          if (!alreadyMerged) {
            const moved = { issue_number: issueNumber, title: '', url: '', status: 'done' }
            next.merged = [...(next.merged || []), moved]
          }
        }
      } else if (!fromStage && pipeStatus) {
        // Status-only update: find the issue in any stage and update its status
        for (const stageKey of Object.keys(next)) {
          const idx = next[stageKey].findIndex(i => i.issue_number === issueNumber)
          if (idx >= 0) {
            next[stageKey] = next[stageKey].map(i =>
              i.issue_number === issueNumber ? { ...i, status: pipeStatus } : i
            )
            break
          }
        }
      }

      return { ...state, pipelineIssues: next }
    }

    case 'SESSION_RESET': {
      return {
        ...state,
        workers: {},
        prs: [],
        reviews: [],
        sessionPrsCount: 0,
        hitlItems: [],
        hitlEscalation: null,
        humanInputRequests: {},
        lastSeenId: -1,
        pipelineIssues: { ...emptyPipeline },
        intents: [],
      }
    }

    case 'INTENT_SUBMITTED':
      return {
        ...state,
        intents: [...state.intents, {
          text: action.data.text,
          issueNumber: null,
          timestamp: new Date().toISOString(),
          status: 'pending',
        }],
      }

    case 'INTENT_CREATED':
      return {
        ...state,
        intents: state.intents.map(i =>
          i.status === 'pending' && i.text === action.data.text
            ? { ...i, issueNumber: action.data.issueNumber, status: 'created' }
            : i
        ),
      }

    case 'INTENT_FAILED':
      return {
        ...state,
        intents: state.intents.map(i =>
          i.status === 'pending' && i.text === action.data.text
            ? { ...i, status: 'failed' }
            : i
        ),
      }

    case 'session_start': {
      const newSession = {
        id: action.data.session_id,
        repo: action.repo ?? action.data.repo,
        started_at: action.timestamp || new Date().toISOString(),
        ended_at: null,
        issues_processed: [],
        issues_succeeded: 0,
        issues_failed: 0,
        status: 'active',
      }
      const filtered = state.sessions.filter(s => s.id !== action.data.session_id)
      return {
        ...addEvent(state, action),
        sessions: [newSession, ...filtered],
        currentSessionId: action.data.session_id,
      }
    }

    case 'session_end': {
      const endedId = action.data.session_id
      return {
        ...addEvent(state, action),
        sessions: state.sessions.map(s =>
          s.id === endedId
            ? {
                ...s,
                ended_at: action.timestamp || new Date().toISOString(),
                status: 'completed',
                issues_processed: action.data.issues_processed ?? s.issues_processed,
                issues_succeeded: action.data.issues_succeeded ?? s.issues_succeeded,
                issues_failed: action.data.issues_failed ?? s.issues_failed,
              }
            : s
        ),
        currentSessionId: null,
      }
    }

    case 'SESSIONS': {
      const fetched = action.data || []
      const fetchedIds = new Set(fetched.map(s => s.id))
      // Keep any active session added via WS event that isn't in the HTTP response yet
      const preserved = state.sessions.filter(s => s.status === 'active' && !fetchedIds.has(s.id))
      return { ...state, sessions: [...preserved, ...fetched] }
    }

    case 'SET_REPOS':
      return {
        ...state,
        canRegisterRepos: action.data?.can_register === true,
        supervisedRepos: Array.isArray(action.data?.repos)
          ? action.data.repos
          : [],
      }

    case 'SELECT_REPO': {
      const newSlug = normalizeRepoSlug(action.data.slug)
      const changed = newSlug !== state.selectedRepoSlug
      return {
        ...state,
        selectedRepoSlug: newSlug,
        selectedRepoSlugRaw: action.data.slug ?? null,
        ...(changed && {
          pipelineIssues: { ...emptyPipeline },
          hitlItems: [],
          workers: {},
          prs: [],
          reviews: [],
          sessionPrsCount: 0,
          events: [],
        }),
      }
    }

    case 'SET_RUNTIMES':
      return {
        ...state,
        runtimes: Array.isArray(action.data?.runtimes) ? action.data.runtimes : [],
      }

    case 'OPTIMISTIC_RUNTIME': {
      const { slug, running } = action.data
      const existing = (state.runtimes || []).find(rt => rt.slug === slug)
      if (existing) {
        return {
          ...state,
          runtimes: state.runtimes.map(rt =>
            rt.slug === slug ? { ...rt, running } : rt,
          ),
        }
      }
      return {
        ...state,
        runtimes: [...(state.runtimes || []), { slug, running }],
      }
    }

    case 'SET_CENTRALIZED_DATA':
      return {
        ...state,
        issueHistory: action.data?.issueHistory ?? state.issueHistory,
        harnessInsights: action.data?.harnessInsights ?? state.harnessInsights,
        reviewInsights: action.data?.reviewInsights ?? state.reviewInsights,
        retrospectives: action.data?.retrospectives ?? state.retrospectives,
        troubleshooting: action.data?.troubleshooting ?? state.troubleshooting,
      }

    case 'SET_TRACKED_REPORTS':
      return { ...state, trackedReports: action.data || [] }

    case 'adr_draft_opened':
      return {
        ...addEvent(state, action),
        adrDrafts: [
          {
            issueNumber: action.data.issue_number,
            title: action.data.title,
            reason: action.data.reason,
            timestamp: action.timestamp,
          },
          ...(state.adrDrafts || []).slice(0, 19),
        ],
      }

    default:
      return addEvent(state, action)
  }
}

const HydraFlowContext = createContext(null)

function getReporterId() {
  if (typeof window === 'undefined') return ''
  const key = 'hydraflow-user-id'
  let id = localStorage.getItem(key)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(key, id)
  }
  return id
}

/** Maps a WebSocket event to a WS_PIPELINE_UPDATE action, or null if not applicable. */
export function getPipelineAction(event) {
  const issueNum = event.data?.issue != null ? Number(event.data.issue) : null
  if (issueNum == null) return null
  const s = event.data?.status
  if (event.type === 'triage_update') {
    if (s === 'done') return { type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: 'triage', toStage: 'plan', status: 'queued' } }
    if (s === 'failed') return { type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: null, toStage: null, status: 'failed' } }
    if (s) return { type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: null, toStage: null, status: 'active' } }
  } else if (event.type === 'planner_update') {
    if (s === 'done') return { type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: 'plan', toStage: 'implement', status: 'queued' } }
    if (s === 'failed') return { type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: null, toStage: null, status: 'failed' } }
    if (s) return { type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: null, toStage: null, status: 'active' } }
  } else if (event.type === 'worker_update') {
    if (s === 'done') return { type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: 'implement', toStage: 'review', status: 'queued' } }
    if (s) return { type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: null, toStage: null, status: 'active' } }
  } else if (event.type === 'review_update') {
    if (s === 'done') return { type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: null, toStage: null, status: 'done' } }
    if (s) return { type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: null, toStage: null, status: 'active' } }
  } else if (event.type === 'merge_update' && s === 'merged') {
    return { type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: 'review', toStage: 'merged', status: 'done' } }
  }
  return null
}

export function HydraFlowProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const lastEventTsRef = useRef(null)
  const bgWorkersRef = useRef(state.backgroundWorkers)
  const reporterIdRef = useRef(getReporterId())

  bgWorkersRef.current = state.backgroundWorkers

  const applyRepoParam = useCallback((url) => {
    const slug = state.selectedRepoSlug
    if (!slug) return url
    const separator = url.includes('?') ? '&' : '?'
    return `${url}${separator}repo=${encodeURIComponent(slug)}`
  }, [state.selectedRepoSlug])

  const fetchWithRepo = useCallback((url, options) => fetch(applyRepoParam(url), options), [applyRepoParam])

  const fetchLifetimeStats = useCallback(() => {
    fetchWithRepo('/api/stats')
      .then(r => r.json())
      .then(data => dispatch({ type: 'LIFETIME_STATS', data }))
      .catch(() => {})
  }, [fetchWithRepo])

  const fetchHitlItems = useCallback(() => {
    fetchWithRepo('/api/hitl')
      .then(r => r.json())
      .then(data => dispatch({ type: 'HITL_ITEMS', data }))
      .catch(() => {})
  }, [fetchWithRepo])

  const fetchTrackedReports = useCallback(() => {
    const rid = reporterIdRef.current
    if (!rid) return
    fetch(`/api/reports?reporter_id=${encodeURIComponent(rid)}`)
      .then(r => r.json())
      .then(data => { if (Array.isArray(data)) dispatch({ type: 'SET_TRACKED_REPORTS', data }) })
      .catch(() => {})
  }, [])

  const refreshReportStatuses = useCallback(async () => {
    const rid = reporterIdRef.current
    if (!rid) return
    try {
      await fetch(`/api/reports/refresh?reporter_id=${encodeURIComponent(rid)}`, { method: 'POST' })
      fetchTrackedReports()
    } catch {
      // silently ignore
    }
  }, [fetchTrackedReports])

  const updateTrackedReport = useCallback(async (reportId, action, detail) => {
    try {
      const res = await fetch(`/api/reports/${reportId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, detail, reporter_id: reporterIdRef.current }),
      })
      if (res.ok) fetchTrackedReports()
    } catch {
      // silently ignore
    }
  }, [fetchTrackedReports])

  const fetchPipeline = useCallback(() => {
    fetchWithRepo('/api/pipeline')
      .then(r => r.json())
      .then(data => dispatch({ type: 'PIPELINE_SNAPSHOT', data: data.stages || {} }))
      .catch(() => {})
  }, [fetchWithRepo])

  const fetchPipelineStats = useCallback(() => {
    fetchWithRepo('/api/pipeline/stats')
      .then(r => r.json())
      .then(data => dispatch({ type: 'PIPELINE_STATS', data }))
      .catch(() => {})
  }, [fetchWithRepo])

  const fetchGithubMetrics = useCallback(() => {
    fetchWithRepo('/api/metrics/github')
      .then(r => r.json())
      .then(data => dispatch({ type: 'GITHUB_METRICS', data }))
      .catch(() => {})
  }, [fetchWithRepo])

  const fetchMetricsHistory = useCallback(() => {
    fetchWithRepo('/api/metrics/history')
      .then(r => r.json())
      .then(data => dispatch({ type: 'METRICS_HISTORY', data }))
      .catch(() => {})
  }, [fetchWithRepo])

  const fetchEpics = useCallback(() => {
    fetchWithRepo('/api/epics')
      .then(r => r.json())
      .then(data => dispatch({ type: 'EPICS', data }))
      .catch(() => {})
  }, [fetchWithRepo])

  const fetchSessions = useCallback(() => {
    fetchWithRepo('/api/sessions')
      .then(r => r.json())
      .then(data => dispatch({ type: 'SESSIONS', data }))
      .catch(() => {})
  }, [fetchWithRepo])

  const selectRepo = useCallback((slug) => {
    dispatch({ type: 'SELECT_REPO', data: { slug } })
  }, [])

  const fetchRepos = useCallback(async () => {
    try {
      const res = await fetch('/api/repos')
      if (!res.ok) throw new Error(`status ${res.status}`)
      const payload = await res.json()
      const repos = Array.isArray(payload.repos) ? payload.repos : []
      dispatch({ type: 'SET_REPOS', data: { repos, can_register: payload.can_register } })
    } catch (err) {
      console.warn('Failed to fetch supervised repos', err)
      dispatch({ type: 'SET_REPOS', data: { repos: [], can_register: false } })
    }
  }, [])

  const fetchRuntimes = useCallback(async () => {
    try {
      const res = await fetch('/api/runtimes')
      if (!res.ok) return
      const data = await res.json()
      dispatch({ type: 'SET_RUNTIMES', data: { runtimes: data.runtimes || [] } })
    } catch { /* ignore */ }
  }, [])

  const parseApiError = useCallback(async (res, fallback) => {
    try {
      const body = await res.json()
      if (body && typeof body.error === 'string' && body.error.trim()) {
        return body.error
      }
      if (body && typeof body.detail === 'string' && body.detail.trim()) {
        return body.detail
      }
      if (Array.isArray(body?.detail) && body.detail.length > 0) {
        const parts = body.detail
          .map((item) => {
            if (item && typeof item.msg === 'string') return item.msg
            return ''
          })
          .filter(Boolean)
        if (parts.length > 0) return parts.join('; ')
      }
    } catch { /* ignore */ }
    return fallback
  }, [])

  const canonicalSlug = useCallback((value) => {
    return String(value || '').trim().replace(/[\\/]+/g, '-').toLowerCase()
  }, [])

  const postCompat = useCallback(async (url, options) => {
    const payloads = Array.isArray(options?.payloads) ? options.payloads : []
    const queryPayloads = Array.isArray(options?.queryPayloads) ? options.queryPayloads : []
    const baseInit = {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    }
    let last = null

    for (const payload of payloads) {
      const res = await fetch(url, {
        ...baseInit,
        body: JSON.stringify(payload),
      })
      last = res
      if (res.status !== 422) return res
    }

    for (const qp of queryPayloads) {
      const params = new URLSearchParams()
      for (const [key, value] of Object.entries(qp || {})) {
        params.set(key, String(value ?? ''))
      }
      const queryUrl = `${url}?${params.toString()}`
      const res = await fetch(queryUrl, { method: 'POST' })
      last = res
      if (res.status !== 422) return res
    }

    return last || fetch(url, { method: 'POST' })
  }, [])

  const startRuntime = useCallback(async (slug, repoPath = null) => {
    try {
      dispatch({ type: 'OPTIMISTIC_RUNTIME', data: { slug, running: true } })
      const encodedSlug = encodeURIComponent(slug)
      const runtimeRes = await fetch(`/api/runtimes/${encodedSlug}/start`, {
        method: 'POST',
      })
      if (runtimeRes.ok) {
        // Brief delay for async runtime startup to complete, then refresh
        await new Promise(r => setTimeout(r, 1000))
        await Promise.all([fetchRuntimes(), fetchRepos()])
        return { ok: true }
      }

      // Compatibility mode: when runtime route is unavailable or validation shape differs,
      // start via supervisor-compatible endpoints.
      if (runtimeRes.status === 404 || runtimeRes.status === 405 || runtimeRes.status === 422 || runtimeRes.status === 501) {
        const repoRes = await postCompat('/api/repos', {
          payloads: [
            { slug },
            { req: { slug } },
            { repo: slug },
            { req: { repo: slug } },
          ],
          queryPayloads: [{ slug }, { repo: slug }],
        })
        // Older/mixed backends may reject /api/repos payload contracts; fallback to
        // direct path-based /api/repos/add when /api/repos is non-OK.
        if (!repoRes.ok) {
          let path = String(repoPath || '').trim()
          if (!path) {
            const listRes = await fetch('/api/repos')
            if (!listRes.ok) {
              dispatch({ type: 'OPTIMISTIC_RUNTIME', data: { slug, running: false } })
              const message = await parseApiError(
                listRes,
                `Failed to list repos (${listRes.status})`,
              )
              return { ok: false, error: message }
            }
            const payload = await listRes.json()
            const repos = Array.isArray(payload?.repos) ? payload.repos : []
            const targetSlug = canonicalSlug(slug)
            const match = repos.find((repo) => {
              const repoSlug = canonicalSlug(repo?.slug)
              const repoPathSlug = canonicalSlug(repo?.path)
              return repoSlug === targetSlug || repoPathSlug.endsWith(`-${targetSlug}`)
            })
            path = String(match?.path || '').trim()
          }
          if (!path) {
            dispatch({ type: 'OPTIMISTIC_RUNTIME', data: { slug, running: false } })
            return { ok: false, error: `Repo not found for slug: ${slug}` }
          }
          const addRes = await postCompat('/api/repos/add', {
            payloads: [
              { path },
              { req: { path } },
              { repo_path: path },
              { req: { repo_path: path } },
            ],
            queryPayloads: [{ path }, { repo_path: path }],
          })
          if (!addRes.ok) {
            dispatch({ type: 'OPTIMISTIC_RUNTIME', data: { slug, running: false } })
            const message = await parseApiError(
              addRes,
              `Failed to start repo (${addRes.status})`,
            )
            return { ok: false, error: message }
          }
          await Promise.all([fetchRepos(), fetchRuntimes()])
          return { ok: true }
        }
        await Promise.all([fetchRepos(), fetchRuntimes()])
        return { ok: true }
      }

      dispatch({ type: 'OPTIMISTIC_RUNTIME', data: { slug, running: false } })
      const message = await parseApiError(
        runtimeRes,
        `Failed to start runtime (${runtimeRes.status})`,
      )
      return { ok: false, error: message }
    } catch (err) {
      dispatch({ type: 'OPTIMISTIC_RUNTIME', data: { slug, running: false } })
      console.warn('Failed to start runtime', slug, err)
      return { ok: false, error: err?.message || 'Failed to start runtime' }
    }
  }, [fetchRuntimes, fetchRepos, parseApiError, canonicalSlug, postCompat])

  const stopRuntime = useCallback(async (slug) => {
    try {
      dispatch({ type: 'OPTIMISTIC_RUNTIME', data: { slug, running: false } })
      const res = await fetch(`/api/runtimes/${encodeURIComponent(slug)}/stop`, {
        method: 'POST',
      })
      if (!res.ok) {
        dispatch({ type: 'OPTIMISTIC_RUNTIME', data: { slug, running: true } })
        const message = await parseApiError(
          res,
          `Failed to stop runtime (${res.status})`,
        )
        return { ok: false, error: message }
      }
      await fetchRuntimes()
      return { ok: true }
    } catch (err) {
      dispatch({ type: 'OPTIMISTIC_RUNTIME', data: { slug, running: true } })
      console.warn('Failed to stop runtime', slug, err)
      return { ok: false, error: err?.message || 'Failed to stop runtime' }
    }
  }, [fetchRuntimes, parseApiError])

  const removeRepo = useCallback(async (repoSlug) => {
    const slug = (repoSlug || '').trim()
    if (!slug) return
    try {
      const res = await fetch(`/api/repos/${encodeURIComponent(slug)}`, {
        method: 'DELETE',
      })
      if (!res.ok) throw new Error(`status ${res.status}`)
      await fetchRepos()
    } catch (err) {
      console.warn('Failed to remove repo', err)
    }
  }, [fetchRepos])

  const addRepoBySlug = useCallback(async (slug) => {
    const trimmed = (slug || '').trim()
    if (!trimmed) return { ok: false, error: 'slug required' }
    try {
      const res = await fetch('/api/repos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slug: trimmed }),
      })
      if (!res.ok) {
        let errorMsg = `status ${res.status}`
        try { const body = await res.json(); if (body.error) errorMsg = body.error } catch { /* ignore */ }
        return { ok: false, error: errorMsg }
      }
      await fetchRepos()
      return { ok: true }
    } catch (err) {
      return { ok: false, error: err.message || 'Network error' }
    }
  }, [fetchRepos])

  const addRepoByPath = useCallback(async (repoPath) => {
    const path = (repoPath || '').trim()
    if (!path) return { ok: false, error: 'path required' }
    try {
      const res = await fetch('/api/repos/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      })
      if (!res.ok) {
        let errorMsg = `status ${res.status}`
        try { const body = await res.json(); if (body.error) errorMsg = body.error } catch { /* ignore */ }
        return { ok: false, error: errorMsg }
      }
      await fetchRepos()
      return { ok: true }
    } catch (err) {
      return { ok: false, error: err.message || 'Network error' }
    }
  }, [fetchRepos])

  const removeRepoShortcut = useCallback((repoSlug) => {
    removeRepo(repoSlug)
  }, [removeRepo])

  const submitIntent = useCallback(async (text) => {
    dispatch({ type: 'INTENT_SUBMITTED', data: { text } })
    try {
      const res = await fetch('/api/intent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
      if (!res.ok) {
        dispatch({ type: 'INTENT_FAILED', data: { text } })
        return null
      }
      const data = await res.json()
      dispatch({ type: 'INTENT_CREATED', data: { text, issueNumber: data.issue_number } })
      return data
    } catch {
      dispatch({ type: 'INTENT_FAILED', data: { text } })
      return null
    }
  }, [])

  const submitReport = useCallback(async ({ description, screenshot_base64 }) => {
    const pi = state.pipelineIssues || {}
    const reporter_id = reporterIdRef.current
    const environment = {
      source: 'dashboard',
      app_version: state.config?.app_version || '',
      orchestrator_status: state.orchestratorStatus || 'unknown',
      queue_depths: {
        triage: (pi.triage || []).length,
        plan: (pi.plan || []).length,
        implement: (pi.implement || []).length,
        review: (pi.review || []).length,
      },
    }
    try {
      const res = await fetch('/api/report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description, screenshot_base64, environment, reporter_id }),
      })
      if (!res.ok) return null
      const data = await res.json()
      fetchTrackedReports()
      return data
    } catch {
      return null
    }
  }, [state.config, state.orchestratorStatus, state.pipelineIssues, fetchTrackedReports])

  const releaseEpic = useCallback(async (epicNumber) => {
    dispatch({ type: 'EPIC_RELEASING', data: { epic_number: epicNumber, progress: 0, total: 0 } })
    try {
      const res = await fetch(applyRepoParam(`/api/epics/${epicNumber}/release`), { method: 'POST' })
      if (!res.ok) {
        // Revert optimistic update
        fetchEpics()
        dispatch({ type: 'EPIC_RELEASING', data: null })
        return { ok: false, error: `Release failed: ${res.status}` }
      }
      const data = await res.json()
      dispatch({ type: 'EPIC_RELEASED', data: { epic_number: epicNumber, version: data.version, released_at: data.released_at } })
      return { ok: true, version: data.version }
    } catch (err) {
      dispatch({ type: 'EPIC_RELEASING', data: null })
      fetchEpics()
      return { ok: false, error: err.message }
    }
  }, [applyRepoParam, fetchEpics])

  const resetSession = useCallback(() => {
    dispatch({ type: 'SESSION_RESET' })
  }, [])

  const toggleBgWorker = useCallback(async (name, enabled) => {
    // Optimistic local update — works even when backend is down
    dispatch({ type: 'TOGGLE_BG_WORKER', data: { name, enabled } })
    try {
      await fetch('/api/control/bg-worker', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, enabled }),
      })
    } catch { /* ignore — local state already updated */ }
  }, [])

  const triggerBgWorker = useCallback(async (name) => {
    try {
      const resp = await fetch('/api/control/bg-worker/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
      return resp.ok
    } catch {
      return false
    }
  }, [])

  const updateBgWorkerInterval = useCallback(async (name, intervalSeconds) => {
    // Optimistic local update
    dispatch({ type: 'UPDATE_BG_WORKER_INTERVAL', data: { name, interval_seconds: intervalSeconds } })
    try {
      await fetch('/api/control/bg-worker/interval', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, interval_seconds: intervalSeconds }),
      })
    } catch { /* ignore — local state already updated */ }
  }, [])

  const requestChanges = useCallback(async (issueNumber, feedback, stage) => {
    try {
      const resp = await fetch('/api/request-changes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ issue_number: issueNumber, feedback, stage }),
      })
      if (resp.ok) {
        fetchHitlItems()
      }
      return resp.ok
    } catch {
      return false
    }
  }, [fetchHitlItems])

  const submitHumanInput = useCallback(async (issueNumber, answer) => {
    try {
      await fetch(applyRepoParam(`/api/human-input/${issueNumber}`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answer }),
      })
      dispatch({ type: 'HUMAN_INPUT_SUBMITTED', data: { issueNumber } })
    } catch { /* ignore */ }
  }, [applyRepoParam])

  const refreshControlStatus = useCallback(async () => {
    try {
      const res = await fetchWithRepo('/api/control/status')
      if (!res.ok) return false
      const data = await res.json()
      dispatch({
        type: 'orchestrator_status',
        data: { status: data.status, credits_paused_until: data.credits_paused_until },
        timestamp: new Date().toISOString(),
      })
      if (data.config) {
        dispatch({ type: 'CONFIG', data: data.config })
      }
      return true
    } catch {
      return false
    }
  }, [fetchWithRepo])

  const refreshCreditStatus = useCallback(async () => {
    try {
      const res = await fetchWithRepo('/api/control/credit-refresh', { method: 'POST' })
      if (!res.ok) return { ok: false, status: 'error' }
      const data = await res.json()
      return { ok: true, status: data.status }
    } catch {
      return { ok: false, status: 'error' }
    }
  }, [fetchWithRepo])

  const startOrchestrator = useCallback(async () => {
    if (state.selectedRepoSlug) {
      const result = await startRuntime(state.selectedRepoSlug)
      if (result.ok) await refreshControlStatus()
      return result.ok
    }
    try {
      const res = await fetch('/api/control/start', { method: 'POST' })
      if (!res.ok) return false
      await refreshControlStatus()
      return true
    } catch {
      return false
    }
  }, [refreshControlStatus, startRuntime, state.selectedRepoSlug])

  const stopOrchestrator = useCallback(async () => {
    if (state.selectedRepoSlug) {
      const result = await stopRuntime(state.selectedRepoSlug)
      if (result.ok) await refreshControlStatus()
      return result.ok
    }
    try {
      const res = await fetch('/api/control/stop', { method: 'POST' })
      if (!res.ok) return false
      await refreshControlStatus()
      return true
    } catch {
      return false
    }
  }, [refreshControlStatus, state.selectedRepoSlug, stopRuntime])

  const connect = useCallback(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const repoParam = state.selectedRepoSlug ? `?repo=${encodeURIComponent(state.selectedRepoSlug)}` : ''
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws${repoParam}`)

    ws.onopen = () => {
      dispatch({ type: 'CONNECTED' })
      fetchWithRepo('/api/control/status')
        .then(r => r.json())
        .then(data => {
          dispatch({
            type: 'orchestrator_status',
            data: { status: data.status, credits_paused_until: data.credits_paused_until },
            timestamp: new Date().toISOString(),
          })
          if (data.config) {
            dispatch({ type: 'CONFIG', data: data.config })
          }
        })
        .catch(() => {})
      fetchLifetimeStats()
      fetchWithRepo('/api/prs')
        .then(r => r.json())
        .then(data => dispatch({ type: 'EXISTING_PRS', data }))
        .catch(() => {})
      fetchHitlItems()
      fetchWithRepo('/api/system/workers')
        .then(r => r.json())
        .then(data => {
          // Sync local toggle overrides to backend
          const localWorkers = bgWorkersRef.current
          if (localWorkers.length > 0 && data.workers) {
            const backendMap = Object.fromEntries(data.workers.map(w => [w.name, w.enabled]))
            for (const lw of localWorkers) {
              if (lw.enabled !== undefined && backendMap[lw.name] !== undefined && lw.enabled !== backendMap[lw.name]) {
                fetch('/api/control/bg-worker', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ name: lw.name, enabled: lw.enabled }),
                }).catch(() => {})
              }
            }
          }
          dispatch({ type: 'BACKGROUND_WORKERS', data: data.workers })
        })
        .catch(() => {})
      fetchWithRepo('/api/queue')
        .then(r => r.json())
        .then(data => dispatch({ type: 'QUEUE_STATS', data }))
        .catch(() => {})
      fetchWithRepo('/api/metrics')
        .then(r => r.json())
        .then(data => dispatch({ type: 'METRICS', data }))
        .catch(() => {})
      fetchGithubMetrics()
      fetchMetricsHistory()
      fetchPipeline()
      fetchPipelineStats()
      fetchEpics()
      fetchSessions()
      fetchRepos()
      fetchRuntimes()
      if (lastEventTsRef.current) {
        fetch(`/api/events?since=${encodeURIComponent(lastEventTsRef.current)}`)
          .then(r => r.json())
          .then(events => dispatch({ type: 'BACKFILL_EVENTS', data: events }))
          .catch(() => {})
      }
    }
    ws.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data)
        dispatch({ type: event.type, data: event.data, timestamp: event.timestamp, id: event.id })
        if (event.timestamp && (!lastEventTsRef.current || event.timestamp > lastEventTsRef.current)) {
          lastEventTsRef.current = event.timestamp
        }
        // Dispatch WS pipeline updates for stage transitions
        const pipelineAction = getPipelineAction(event)
        if (pipelineAction) dispatch(pipelineAction)

        if (event.type === 'metrics_update') {
          fetchLifetimeStats()
          fetchWithRepo('/api/metrics').then(r => r.json()).then(data => dispatch({ type: 'METRICS', data })).catch(() => {})
          fetchGithubMetrics()
          fetchMetricsHistory()
        }
        if (event.type === 'queue_update') fetchPipeline()
        if (event.type === 'hitl_update' || event.type === 'hitl_escalation') fetchHitlItems()
        if (event.type === 'epic_update' || event.type === 'epic_ready' || event.type === 'epic_released') fetchEpics()
      } catch { /* ignore parse errors */ }
    }

    ws.onclose = (event) => {
      // Guard against stale connections: when selectedRepoSlug changes, the
      // useEffect cleanup closes the old WS and connect() opens a new one
      // (wsRef.current = new_ws). If this onclose fires after that, skip the
      // reconnect to avoid opening a second connection to the wrong repo.
      if (wsRef.current !== ws) return
      dispatch({ type: 'DISCONNECTED' })
      // 1008 = Policy Violation — server explicitly rejected our repo slug.
      // Don't reconnect; the slug is invalid and retrying would loop forever.
      if (event.code === 1008) return
      reconnectTimer.current = setTimeout(connect, 2000)
    }

    // Don't force-close on error — browsers fire `close` after `error`
    // automatically, and calling close() here races a frame still in flight
    // through the Vite dev proxy, producing EPIPE noise during reconnect.
    ws.onerror = () => {}
    wsRef.current = ws
  }, [state.selectedRepoSlug, fetchLifetimeStats, fetchHitlItems, fetchGithubMetrics, fetchMetricsHistory, fetchPipeline, fetchPipelineStats, fetchEpics, fetchSessions, fetchRepos, fetchRuntimes, fetchWithRepo])

  useEffect(() => {
    const poll = () => {
      fetchWithRepo('/api/human-input')
        .then(r => r.ok ? r.json() : {})
        .then(data => dispatch({ type: 'HUMAN_INPUT_REQUESTS', data }))
        .catch(() => {})
    }
    poll()
    const interval = setInterval(poll, 3000)
    return () => clearInterval(interval)
  }, [fetchWithRepo])

  // Pipeline polling — interval is editable via system worker controls.
  // When WebSocket is connected and pipeline_stats events are flowing,
  // double the polling interval since stats arrive via WebSocket.
  const pipelinePollerIntervalMs = useMemo(() => {
    const worker = state.backgroundWorkers.find(w => w.name === 'pipeline_poller')
    const baseMs = (worker?.interval_seconds ?? SYSTEM_WORKER_INTERVALS.pipeline_poller) * 1000
    return (state.connected && state.pipelineStats) ? baseMs * 2 : baseMs
  }, [state.backgroundWorkers, state.connected, state.pipelineStats])

  useEffect(() => {
    fetchPipeline()
    const interval = setInterval(fetchPipeline, pipelinePollerIntervalMs)
    return () => clearInterval(interval)
  }, [fetchPipeline, pipelinePollerIntervalMs])

  useEffect(() => {
    connect()
    return () => {
      if (wsRef.current) wsRef.current.close()
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    }
  }, [connect])

  useEffect(() => {
    fetchRepos()
    const interval = setInterval(fetchRepos, 15000)
    return () => clearInterval(interval)
  }, [fetchRepos])

  useEffect(() => {
    fetchRuntimes()
    const interval = setInterval(fetchRuntimes, 15000)
    return () => clearInterval(interval)
  }, [fetchRuntimes])

  const stageStatus = useMemo(
    () => deriveStageStatus(
      state.pipelineIssues,
      state.workers,
      state.backgroundWorkers,
      state.pipelineStats,
    ),
    [state.pipelineIssues, state.workers, state.backgroundWorkers, state.pipelineStats],
  )

  const repoFilteredSessions = useMemo(() => {
    if (!state.selectedRepoSlug) return state.sessions
    return state.sessions.filter(s => {
      return normalizeRepoSlug(s.repo) === state.selectedRepoSlug
    })
  }, [state.sessions, state.selectedRepoSlug])

  // Centralized polling for insights/history data (replaces per-component fetches)
  useEffect(() => {
    if (!state.connected) return
    let cancelled = false

    const endpoints = [
      { url: '/api/issues/history?limit=500', key: 'issueHistory' },
      { url: '/api/harness-insights', key: 'harnessInsights' },
      { url: '/api/review-insights', key: 'reviewInsights' },
      { url: '/api/retrospectives', key: 'retrospectives' },
      { url: '/api/troubleshooting', key: 'troubleshooting' },
    ]

    async function poll() {
      const results = await Promise.allSettled(
        endpoints.map(({ url }) => fetch(url).then(r => r.ok ? r.json() : null))
      )
      if (cancelled) return
      const update = {}
      endpoints.forEach(({ key }, i) => {
        const r = results[i]
        if (r.status === 'fulfilled' && r.value != null) {
          update[key] = r.value
        }
      })
      if (Object.keys(update).length > 0) {
        dispatch({ type: 'SET_CENTRALIZED_DATA', data: update })
      }
    }

    poll()
    const interval = setInterval(poll, 30_000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [state.connected])

  // Reflect WebSocket connection state as a DOM attribute so Playwright helpers
  // (wait_for_ws_ready) can detect readiness without polling JS state.
  useEffect(() => {
    document.body.setAttribute('data-connected', String(state.connected))
    return () => { document.body.removeAttribute('data-connected') }
  }, [state.connected])

  // Fetch tracked reports on mount and periodically; also refresh
  // filed/stale statuses so the UI reflects actual issue outcomes.
  useEffect(() => {
    fetchTrackedReports()
    const interval = setInterval(() => {
      refreshReportStatuses()
    }, 30_000)
    return () => clearInterval(interval)
  }, [fetchTrackedReports, refreshReportStatuses])

  const value = {
    ...state,
    sessions: repoFilteredSessions,
    stageStatus,
    resetSession,
    submitIntent,
    submitReport,
    reporterId: reporterIdRef.current,
    trackedReports: state.trackedReports,
    updateTrackedReport,
    refreshReportStatuses,
    submitHumanInput,
    requestChanges,
    toggleBgWorker,
    triggerBgWorker,
    updateBgWorkerInterval,
    dismissSystemAlert: useCallback(() => dispatch({ type: 'CLEAR_SYSTEM_ALERT' }), [dispatch]),
    refreshCreditStatus,
    refreshHitl: fetchHitlItems,
    selectRepo,
    addRepoBySlug,
    addRepoByPath,
    fetchRepos,
    removeRepoShortcut,
    startRuntime,
    stopRuntime,
    startOrchestrator,
    stopOrchestrator,
    releaseEpic,
    refreshControlStatus,
  }

  return (
    <HydraFlowContext.Provider value={value}>
      {children}
    </HydraFlowContext.Provider>
  )
}

export function useHydraFlow() {
  const context = useContext(HydraFlowContext)
  if (!context) {
    throw new Error('useHydraFlow must be used within a HydraFlowProvider')
  }
  return context
}
