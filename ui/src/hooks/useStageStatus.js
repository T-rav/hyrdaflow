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
 *   workload.done = sessionCounters.mergedCount (merged PRs), NOT workers with status 'done'
 */
export function deriveStageStatus(pipelineIssues, workers, backgroundWorkers, sessionCounters) {
  const issues = pipelineIssues || {}
  const workerValues = Object.values(workers || {})
  const bgMap = new Map((backgroundWorkers || []).map(w => [w.name, w]))
  const counters = sessionCounters || {}

  const stageStatus = {}

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

  // Workload aggregate across all workers
  const workload = {
    total: workerValues.length,
    active: workerValues.filter(w => ACTIVE_STATUSES.includes(w.status)).length,
    done: counters.mergedCount || 0,
    failed: workerValues.filter(w => w.status === 'failed').length,
  }

  stageStatus.workload = workload

  return stageStatus
}

