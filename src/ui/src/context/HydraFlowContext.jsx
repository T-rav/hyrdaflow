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
  selectedSessionId: null,
  selectedRepoSlug: null,
  supervisedRepos: [],
  runtimes: [],
  issueHistory: null,
  harnessInsights: null,
  reviewInsights: null,
  retrospectives: null,
  troubleshooting: null,
  memories: null,
}

function normalizeRepoSlug(value) {
  return String(value || '').trim().replace(/[\\/]+/g, '-')
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
      return {
        ...addEvent(state, action),
        orchestratorStatus: newStatus,
        creditsPausedUntil: action.data.credits_paused_until || null,
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
      if (action.data.source === 'triage') {
        key = `triage-${action.data.issue}`
      } else if (action.data.source === 'planner') {
        key = `plan-${action.data.issue}`
      } else if (action.data.source === 'reviewer') {
        key = `review-${action.data.pr}`
      }
      if (!key || !state.workers[key]) return addEvent(state, action)
      const w = state.workers[key]
      return {
        ...addEvent(state, action),
        workers: {
          ...state.workers,
          [key]: { ...w, transcript: [...w.transcript, action.data.line] },
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
      const updatedPrs = isMerged && action.data.pr
        ? state.prs.map(p => p.pr === action.data.pr ? { ...p, merged: true } : p)
        : state.prs
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
      // /api/prs only returns open PRs — preserve merged PRs from session
      const existingMerged = state.prs.filter(p => p.merged)
      const openPrs = action.data || []
      const openNumbers = new Set(openPrs.map(p => p.pr))
      const merged = existingMerged.filter(p => !openNumbers.has(p.pr))
      return { ...state, prs: [...openPrs, ...merged] }
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
      const openStages = ['triage', 'plan', 'implement', 'review', 'hitl']

      const nextOpen = Object.fromEntries(openStages.map((key) => {
        if (!Object.prototype.hasOwnProperty.call(incoming, key)) {
          return [key, state.pipelineIssues[key] || []]
        }
        // Server snapshot is authoritative: reconcile stage membership so issues
        // absent from the snapshot are removed (eliminates ghost cards).
        return [key, mergeStageIssues(state.pipelineIssues[key], incoming[key] || [])]
      }))

      return {
        ...state,
        pipelineIssues: {
          ...nextOpen,
          // Server never sends merged — preserve session-accumulated merged items
          merged: state.pipelineIssues.merged || [],
        },
        pipelinePollerLastRun: new Date().toISOString(),
      }
    }

    case 'pipeline_stats':
    case 'PIPELINE_STATS': {
      return { ...state, pipelineStats: action.data }
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
        repo: action.data.repo,
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
        supervisedRepos: Array.isArray(action.data?.repos)
          ? action.data.repos
          : [],
      }

    case 'SELECT_SESSION':
      return { ...state, selectedSessionId: action.data.sessionId }

    case 'SELECT_REPO':
      return {
        ...state,
        selectedRepoSlug: normalizeRepoSlug(action.data.slug),
        selectedSessionId: null,
      }

    case 'SET_RUNTIMES':
      return {
        ...state,
        runtimes: Array.isArray(action.data?.runtimes) ? action.data.runtimes : [],
      }

    case 'SET_CENTRALIZED_DATA':
      return {
        ...state,
        issueHistory: action.data?.issueHistory ?? state.issueHistory,
        harnessInsights: action.data?.harnessInsights ?? state.harnessInsights,
        reviewInsights: action.data?.reviewInsights ?? state.reviewInsights,
        retrospectives: action.data?.retrospectives ?? state.retrospectives,
        troubleshooting: action.data?.troubleshooting ?? state.troubleshooting,
        memories: action.data?.memories ?? state.memories,
      }

    case 'DELETE_SESSION':
      return {
        ...state,
        sessions: state.sessions.filter(s => s.id !== action.data.sessionId),
        selectedSessionId: state.selectedSessionId === action.data.sessionId
          ? null
          : state.selectedSessionId,
      }

    default:
      return addEvent(state, action)
  }
}

const HydraFlowContext = createContext(null)

function getInitialState() {
  if (typeof window !== 'undefined' && window.__HYDRAFLOW_SEED_STATE__) {
    return { ...initialState, ...window.__HYDRAFLOW_SEED_STATE__ }
  }
  return initialState
}

export function HydraFlowProvider({ children }) {
  const [state, dispatch] = useReducer(reducer, undefined, getInitialState)
  const isSeeded = typeof window !== 'undefined' && !!window.__HYDRAFLOW_SEED_STATE__
  const wsRef = useRef(null)
  const reconnectTimer = useRef(null)
  const lastEventTsRef = useRef(null)
  const bgWorkersRef = useRef(state.backgroundWorkers)

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

  const selectSession = useCallback((sessionId) => {
    dispatch({ type: 'SELECT_SESSION', data: { sessionId } })
  }, [])

  const selectRepo = useCallback((slug) => {
    dispatch({ type: 'SELECT_REPO', data: { slug } })
  }, [])

  const deleteSession = useCallback(async (sessionId) => {
    dispatch({ type: 'DELETE_SESSION', data: { sessionId } })
    try {
      const res = await fetch(applyRepoParam(`/api/sessions/${encodeURIComponent(sessionId)}`), {
        method: 'DELETE',
      })
      if (!res.ok) {
        // Revert optimistic delete by re-fetching
        fetchSessions()
      }
    } catch {
      fetchSessions()
    }
  }, [applyRepoParam, fetchSessions])

  const fetchRepos = useCallback(async () => {
    try {
      const res = await fetch('/api/repos')
      if (!res.ok) throw new Error(`status ${res.status}`)
      const payload = await res.json()
      const repos = Array.isArray(payload.repos) ? payload.repos : []
      dispatch({ type: 'SET_REPOS', data: { repos } })
    } catch (err) {
      console.warn('Failed to fetch supervised repos', err)
      dispatch({ type: 'SET_REPOS', data: { repos: [] } })
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
      const encodedSlug = encodeURIComponent(slug)
      const runtimeRes = await fetch(`/api/runtimes/${encodedSlug}/start`, {
        method: 'POST',
      })
      if (runtimeRes.ok) {
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

      const message = await parseApiError(
        runtimeRes,
        `Failed to start runtime (${runtimeRes.status})`,
      )
      return { ok: false, error: message }
    } catch (err) {
      console.warn('Failed to start runtime', slug, err)
      return { ok: false, error: err?.message || 'Failed to start runtime' }
    }
  }, [fetchRuntimes, fetchRepos, parseApiError, canonicalSlug, postCompat])

  const stopRuntime = useCallback(async (slug) => {
    try {
      const res = await fetch(`/api/runtimes/${encodeURIComponent(slug)}/stop`, {
        method: 'POST',
      })
      if (!res.ok) {
        const message = await parseApiError(
          res,
          `Failed to stop runtime (${res.status})`,
        )
        return { ok: false, error: message }
      }
      await fetchRuntimes()
      return { ok: true }
    } catch (err) {
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
        body: JSON.stringify({ description, screenshot_base64, environment }),
      })
      if (!res.ok) return null
      return await res.json()
    } catch {
      return null
    }
  }, [state.config, state.orchestratorStatus, state.pipelineIssues])

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

  const startOrchestrator = useCallback(async () => {
    if (state.selectedRepoSlug) {
      const result = await startRuntime(state.selectedRepoSlug)
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
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws`)

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
        const issueNum = event.data?.issue != null ? Number(event.data.issue) : null
        if (issueNum != null) {
          if (event.type === 'triage_update' && event.data?.status === 'done') {
            dispatch({ type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: 'triage', toStage: 'plan', status: 'queued' } })
          } else if (event.type === 'triage_update' && event.data?.status && event.data.status !== 'done') {
            dispatch({ type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: null, toStage: null, status: 'active' } })
          } else if (event.type === 'planner_update' && event.data?.status === 'done') {
            dispatch({ type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: 'plan', toStage: 'implement', status: 'queued' } })
          } else if (event.type === 'planner_update' && event.data?.status && event.data.status !== 'done') {
            dispatch({ type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: null, toStage: null, status: 'active' } })
          } else if (event.type === 'worker_update' && event.data?.status === 'done') {
            dispatch({ type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: 'implement', toStage: 'review', status: 'queued' } })
          } else if (event.type === 'worker_update' && event.data?.status && event.data.status !== 'done') {
            dispatch({ type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: null, toStage: null, status: 'active' } })
          } else if (event.type === 'review_update' && event.data?.status === 'done') {
            dispatch({ type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: null, toStage: null, status: 'done' } })
          } else if (event.type === 'review_update' && event.data?.status && event.data.status !== 'done') {
            dispatch({ type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: null, toStage: null, status: 'active' } })
          } else if (event.type === 'merge_update' && event.data?.status === 'merged') {
            dispatch({ type: 'WS_PIPELINE_UPDATE', data: { issueNumber: issueNum, fromStage: 'review', toStage: 'merged', status: 'done' } })
          }
        }

        if (event.type === 'metrics_update') {
          fetchLifetimeStats()
          fetchWithRepo('/api/metrics').then(r => r.json()).then(data => dispatch({ type: 'METRICS', data })).catch(() => {})
          fetchGithubMetrics()
          fetchMetricsHistory()
        }
        if (event.type === 'hitl_update' || event.type === 'hitl_escalation') fetchHitlItems()
        if (event.type === 'epic_update' || event.type === 'epic_ready' || event.type === 'epic_released') fetchEpics()
      } catch { /* ignore parse errors */ }
    }

    ws.onclose = () => {
      dispatch({ type: 'DISCONNECTED' })
      reconnectTimer.current = setTimeout(connect, 2000)
    }

    ws.onerror = () => ws.close()
    wsRef.current = ws
  }, [fetchLifetimeStats, fetchHitlItems, fetchGithubMetrics, fetchMetricsHistory, fetchPipeline, fetchPipelineStats, fetchEpics, fetchSessions, fetchRepos, fetchRuntimes, fetchWithRepo])

  useEffect(() => {
    if (isSeeded) return
    const poll = () => {
      fetchWithRepo('/api/human-input')
        .then(r => r.ok ? r.json() : {})
        .then(data => dispatch({ type: 'HUMAN_INPUT_REQUESTS', data }))
        .catch(() => {})
    }
    poll()
    const interval = setInterval(poll, 3000)
    return () => clearInterval(interval)
  }, [fetchWithRepo, isSeeded])

  // Pipeline polling — interval is editable via system worker controls.
  // When WebSocket is connected and pipeline_stats events are flowing,
  // double the polling interval since stats arrive via WebSocket.
  const pipelinePollerIntervalMs = useMemo(() => {
    const worker = state.backgroundWorkers.find(w => w.name === 'pipeline_poller')
    const baseMs = (worker?.interval_seconds ?? SYSTEM_WORKER_INTERVALS.pipeline_poller) * 1000
    return (state.connected && state.pipelineStats) ? baseMs * 2 : baseMs
  }, [state.backgroundWorkers, state.connected, state.pipelineStats])

  useEffect(() => {
    if (isSeeded) return
    fetchPipeline()
    const interval = setInterval(fetchPipeline, pipelinePollerIntervalMs)
    return () => clearInterval(interval)
  }, [fetchPipeline, pipelinePollerIntervalMs, isSeeded])

  useEffect(() => {
    if (isSeeded) return
    connect()
    return () => {
      if (wsRef.current) wsRef.current.close()
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    }
  }, [connect, isSeeded])

  useEffect(() => {
    if (isSeeded) return
    fetchRepos()
    const interval = setInterval(fetchRepos, 15000)
    return () => clearInterval(interval)
  }, [fetchRepos, isSeeded])

  useEffect(() => {
    if (isSeeded) return
    fetchRuntimes()
    const interval = setInterval(fetchRuntimes, 15000)
    return () => clearInterval(interval)
  }, [fetchRuntimes, isSeeded])

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

  const selectedSession = useMemo(() => {
    if (!state.selectedSessionId) return null
    return state.sessions.find(s => s.id === state.selectedSessionId) ?? null
  }, [state.selectedSessionId, state.sessions])

  const filteredEvents = useMemo(() => {
    if (!selectedSession) return state.events
    const start = selectedSession.started_at
    const end = selectedSession.ended_at || new Date().toISOString()
    return state.events.filter(e => e.timestamp && e.timestamp >= start && e.timestamp <= end)
  }, [state.events, selectedSession])

  // Centralized polling for insights/history data (replaces per-component fetches)
  useEffect(() => {
    if (isSeeded) return
    if (!state.connected) return
    let cancelled = false

    const endpoints = [
      { url: '/api/issues/history?limit=500', key: 'issueHistory' },
      { url: '/api/harness-insights', key: 'harnessInsights' },
      { url: '/api/review-insights', key: 'reviewInsights' },
      { url: '/api/retrospectives', key: 'retrospectives' },
      { url: '/api/troubleshooting', key: 'troubleshooting' },
      { url: '/api/memories', key: 'memories' },
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
  }, [state.connected, isSeeded])

  const value = {
    ...state,
    events: filteredEvents,
    sessions: repoFilteredSessions,
    selectedSession,
    stageStatus,
    resetSession,
    submitIntent,
    submitReport,
    submitHumanInput,
    requestChanges,
    toggleBgWorker,
    updateBgWorkerInterval,
    refreshHitl: fetchHitlItems,
    selectSession,
    selectRepo,
    deleteSession,
    addRepoByPath,
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
