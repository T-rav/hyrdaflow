import { PIPELINE_STAGES, PIPELINE_LOOPS, ACTIVE_STATUSES } from '../constants'

/**
 * Mapping from stage key to the session counter property name in state.
 */
const SESSION_COUNTER_KEYS = {
  triage: 'sessionTriaged',
  plan: 'sessionPlanned',
  implement: 'sessionImplemented',
  review: 'sessionReviewed',
  merged: 'mergedCount',
}

/**
 * Set of pipeline loop keys for quick lookup of which stages have toggleable loops.
 */
const LOOP_KEYS = new Set(PIPELINE_LOOPS.map(l => l.key))
const DEFAULT_STAGE_WORKER_CAPS = {
  triage: 1,
  plan: 1,
  implement: 2,
  review: 2,
}

function normalizeWorkerCap(value, fallback) {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  return Math.max(fallback, Math.floor(n))
}

/**
 * Pure function that derives a unified stageStatus model from raw state slices.
 *
 * Returns an object keyed by stage key with per-stage metrics, plus a `workload` aggregate.
 *
 * @param {Object} pipelineIssues - Issues per stage { triage: [...], plan: [...], ... }
 * @param {Object} workers - Worker map keyed by issue/worker key
 * @param {Array} backgroundWorkers - Array of { name, status, enabled, ... }
 * @param {Object} sessionCounters - { sessionTriaged, sessionPlanned, sessionImplemented, sessionReviewed, mergedCount }
 * @returns {{ [stageKey]: { issueCount, activeCount, queuedCount, workerCount, enabled, sessionCount }, workload: { total, active, done, failed } }}
 *   workload is pipeline-centric (same source as Stream/System pipeline views):
 *   open issue counts come from pipelineIssues; merged comes from session counters.
 */
export function deriveStageStatus(pipelineIssues, workers, backgroundWorkers, sessionCounters, config) {
  const issues = pipelineIssues || {}
  const workerValues = Object.values(workers || {})
  const bgMap = new Map((backgroundWorkers || []).map(w => [w.name, w]))
  const counters = sessionCounters || {}
  const cfg = config || {}

  const stageStatus = {}

  const workerCaps = {
    triage: DEFAULT_STAGE_WORKER_CAPS.triage,
    plan: normalizeWorkerCap(cfg.max_planners, DEFAULT_STAGE_WORKER_CAPS.plan),
    implement: normalizeWorkerCap(cfg.max_workers, DEFAULT_STAGE_WORKER_CAPS.implement),
    review: normalizeWorkerCap(cfg.max_reviewers, DEFAULT_STAGE_WORKER_CAPS.review),
  }

  for (const stage of PIPELINE_STAGES) {
    const stageIssues = issues[stage.key] || []
    const activeIssues = stageIssues.filter(i => i.status === 'active').length

    // Worker count: filter workers by role and active status
    let workerCount = 0
    if (stage.role) {
      workerCount = workerValues.filter(
        w => w.role === stage.role && ACTIVE_STATUSES.includes(w.status)
      ).length
    }

    // Enabled state: from backgroundWorkers for stages with pipeline loops; merged is always true
    let enabled = true
    if (LOOP_KEYS.has(stage.key)) {
      const bgWorker = bgMap.get(stage.key)
      enabled = bgWorker ? bgWorker.enabled !== false : true
    }

    // Session count
    const counterKey = SESSION_COUNTER_KEYS[stage.key]
    const sessionCount = counterKey ? (counters[counterKey] || 0) : 0

    stageStatus[stage.key] = {
      issueCount: stageIssues.length,
      activeCount: activeIssues,
      queuedCount: stageIssues.length - activeIssues,
      workerCount,
      enabled,
      sessionCount,
    }
  }

  // Workload aggregate aligned with pipeline snapshots to avoid drift between
  // Header and Stream/System pipeline views.
  const openStageKeys = ['triage', 'plan', 'implement', 'review', 'hitl']
  const openIssues = openStageKeys.flatMap((k) => issues[k] || [])
  const pipelineActive = openIssues.filter(i => i.status === 'active').length
  const pipelineFailed = openIssues.filter(
    i => i.status === 'failed' || i.status === 'error'
  ).length
  const workerActive = workerValues.filter(w => ACTIVE_STATUSES.includes(w.status)).length

  const doneCount = counters.mergedCount || 0
  const totalCount = openIssues.length + doneCount

  const workload = {
    total: totalCount,
    active: Math.max(pipelineActive, workerActive),
    done: doneCount,
    failed: pipelineFailed,
  }

  stageStatus.workload = workload
  stageStatus.workerCaps = workerCaps

  return stageStatus
}
