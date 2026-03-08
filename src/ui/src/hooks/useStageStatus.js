import { PIPELINE_STAGES, PIPELINE_LOOPS, ACTIVE_STATUSES } from '../constants'

/**
 * Set of pipeline loop keys for quick lookup of which stages have toggleable loops.
 */
const LOOP_KEYS = new Set(PIPELINE_LOOPS.map(l => l.key))

/**
 * Pure function that derives a unified stageStatus model from raw state slices.
 *
 * Returns an object keyed by stage key with per-stage metrics, plus a `workload` aggregate.
 *
 * pipelineStats (from backend) is the single source of truth for all aggregate numbers:
 * sessionCount, activeCount, queuedCount, workerCount, workerCaps, and merged done count.
 * pipelineIssues is only used for issueCount (card rendering) and workload open-issue totals.
 *
 * @param {Object} pipelineIssues - Issues per stage { triage: [...], plan: [...], ... }
 * @param {Object} workers - Worker map keyed by issue/worker key (used for workload.active)
 * @param {Array} backgroundWorkers - Array of { name, status, enabled, ... }
 * @param {Object} pipelineStats - Backend PipelineStats — the single source of truth
 */
export function deriveStageStatus(pipelineIssues, workers, backgroundWorkers, pipelineStats) {
  const issues = pipelineIssues || {}
  const workerValues = Object.values(workers || {})
  const bgMap = new Map((backgroundWorkers || []).map(w => [w.name, w]))
  const stages = pipelineStats?.stages || {}

  const stageStatus = {}

  const workerCaps = {
    triage: stages.triage?.worker_cap ?? null,
    plan: stages.plan?.worker_cap ?? null,
    implement: stages.implement?.worker_cap ?? null,
    review: stages.review?.worker_cap ?? null,
  }

  for (const stage of PIPELINE_STAGES) {
    const stageIssues = issues[stage.key] || []
    const ss = stages[stage.key]

    // Enabled state: from backgroundWorkers for stages with pipeline loops; merged is always true
    let enabled = true
    if (LOOP_KEYS.has(stage.key)) {
      const bgWorker = bgMap.get(stage.key)
      enabled = bgWorker ? bgWorker.enabled !== false : true
    }

    stageStatus[stage.key] = {
      issueCount: stageIssues.length,
      activeCount: ss?.active ?? 0,
      queuedCount: ss?.queued ?? 0,
      workerCount: ss?.worker_count ?? 0,
      enabled,
      sessionCount: ss?.completed_session ?? 0,
    }
  }

  // Workload aggregate
  const openStageKeys = ['triage', 'plan', 'implement', 'review', 'hitl']
  const openIssues = openStageKeys.flatMap((k) => issues[k] || [])
  const pipelineActive = openIssues.filter(i => i.status === 'active').length
  const pipelineFailed = openIssues.filter(
    i => i.status === 'failed' || i.status === 'error'
  ).length
  const workerActive = workerValues.filter(w => ACTIVE_STATUSES.includes(w.status)).length

  const doneCount = stages.merged?.completed_session ?? 0
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
