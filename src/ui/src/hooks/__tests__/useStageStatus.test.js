import { describe, it, expect } from 'vitest'
import { deriveStageStatus } from '../useStageStatus'

describe('deriveStageStatus', () => {
  const emptyPipeline = { triage: [], plan: [], implement: [], review: [], hitl: [] }

  it('returns all zeros and enabled=true for empty inputs', () => {
    const result = deriveStageStatus({}, {}, [], {})

    expect(result.triage).toEqual({
      issueCount: 0, activeCount: 0, queuedCount: 0,
      workerCount: 0, enabled: true, sessionCount: 0,
    })
    expect(result.plan).toEqual({
      issueCount: 0, activeCount: 0, queuedCount: 0,
      workerCount: 0, enabled: true, sessionCount: 0,
    })
    expect(result.implement).toEqual({
      issueCount: 0, activeCount: 0, queuedCount: 0,
      workerCount: 0, enabled: true, sessionCount: 0,
    })
    expect(result.review).toEqual({
      issueCount: 0, activeCount: 0, queuedCount: 0,
      workerCount: 0, enabled: true, sessionCount: 0,
    })
    expect(result.merged).toEqual({
      issueCount: 0, activeCount: 0, queuedCount: 0,
      workerCount: 0, enabled: true, sessionCount: 0,
    })
  })

  it('handles null/undefined inputs gracefully', () => {
    const result = deriveStageStatus(null, null, null, null)

    expect(result.triage.issueCount).toBe(0)
    expect(result.workload.total).toBe(0)
  })

  it('computes issue counts from pipelineIssues', () => {
    const pipeline = {
      ...emptyPipeline,
      triage: [
        { issue_number: 1, status: 'active' },
        { issue_number: 2, status: 'queued' },
      ],
      plan: [
        { issue_number: 3, status: 'queued' },
      ],
      implement: [
        { issue_number: 4, status: 'active' },
        { issue_number: 5, status: 'active' },
        { issue_number: 6, status: 'queued' },
      ],
    }

    const result = deriveStageStatus(pipeline, {}, [], {})

    expect(result.triage.issueCount).toBe(2)
    expect(result.triage.activeCount).toBe(1)
    expect(result.triage.queuedCount).toBe(1)

    expect(result.plan.issueCount).toBe(1)
    expect(result.plan.activeCount).toBe(0)
    expect(result.plan.queuedCount).toBe(1)

    expect(result.implement.issueCount).toBe(3)
    expect(result.implement.activeCount).toBe(2)
    expect(result.implement.queuedCount).toBe(1)

    expect(result.review.issueCount).toBe(0)
  })

  it('computes worker counts by role and active status', () => {
    const workers = {
      'triage-1': { role: 'triage', status: 'evaluating' },
      'triage-2': { role: 'triage', status: 'done' },
      'plan-3': { role: 'planner', status: 'planning' },
      4: { role: 'implementer', status: 'running' },
      5: { role: 'implementer', status: 'testing' },
      6: { role: 'implementer', status: 'queued' },
      'review-7': { role: 'reviewer', status: 'reviewing' },
      'review-8': { role: 'reviewer', status: 'failed' },
    }

    const result = deriveStageStatus(emptyPipeline, workers, [], {})

    expect(result.triage.workerCount).toBe(1)    // evaluating is active, done is not
    expect(result.plan.workerCount).toBe(1)       // planning is active
    expect(result.implement.workerCount).toBe(2)  // running + testing are active, queued is not
    expect(result.review.workerCount).toBe(1)     // reviewing is active, failed is not
  })

  it('merged stage has workerCount 0 (no role)', () => {
    const workers = {
      1: { role: 'implementer', status: 'running' },
    }
    const result = deriveStageStatus(emptyPipeline, workers, [], {})
    expect(result.merged.workerCount).toBe(0)
  })

  it('computes enabled state from backgroundWorkers', () => {
    const bgWorkers = [
      { name: 'triage', enabled: true },
      { name: 'plan', enabled: false },
      { name: 'implement', enabled: true },
      { name: 'review', enabled: false },
    ]

    const result = deriveStageStatus(emptyPipeline, {}, bgWorkers, {})

    expect(result.triage.enabled).toBe(true)
    expect(result.plan.enabled).toBe(false)
    expect(result.implement.enabled).toBe(true)
    expect(result.review.enabled).toBe(false)
  })

  it('merged stage is always enabled (no pipeline loop)', () => {
    const bgWorkers = [
      { name: 'triage', enabled: false },
    ]
    const result = deriveStageStatus(emptyPipeline, {}, bgWorkers, {})
    expect(result.merged.enabled).toBe(true)
  })

  it('defaults enabled to true when bg worker not in state', () => {
    const result = deriveStageStatus(emptyPipeline, {}, [], {})
    expect(result.triage.enabled).toBe(true)
    expect(result.plan.enabled).toBe(true)
  })

  it('maps session counters to stage keys', () => {
    const counters = {
      sessionTriaged: 5,
      sessionPlanned: 3,
      sessionImplemented: 8,
      sessionReviewed: 2,
      mergedCount: 7,
    }

    const result = deriveStageStatus(emptyPipeline, {}, [], counters)

    expect(result.triage.sessionCount).toBe(5)
    expect(result.plan.sessionCount).toBe(3)
    expect(result.implement.sessionCount).toBe(8)
    expect(result.review.sessionCount).toBe(2)
    expect(result.merged.sessionCount).toBe(7)
  })

  it('defaults session counts to 0 when counters missing', () => {
    const result = deriveStageStatus(emptyPipeline, {}, [], {})
    expect(result.triage.sessionCount).toBe(0)
    expect(result.merged.sessionCount).toBe(0)
  })

  it('derives canonical worker caps from config', () => {
    const result = deriveStageStatus(
      emptyPipeline,
      {},
      [],
      {},
      { max_triagers: 2, max_planners: 3, max_workers: 5, max_reviewers: 4 },
    )
    expect(result.workerCaps).toEqual({
      triage: 2,
      plan: 3,
      implement: 5,
      review: 4,
    })
  })

  it('leaves missing/invalid worker caps unset (config drives limits)', () => {
    const result = deriveStageStatus(
      emptyPipeline,
      {},
      [],
      {},
      { max_triagers: 0, max_planners: 0, max_workers: 0, max_reviewers: -2 },
    )
    expect(result.workerCaps).toEqual({
      triage: 0,
      plan: 0,
      implement: 0,
      review: -2,
    })
  })

  it('returns null triage cap when max_triagers is absent from config', () => {
    const result = deriveStageStatus(
      emptyPipeline,
      {},
      [],
      {},
      { max_planners: 2, max_workers: 3, max_reviewers: 1 },
    )
    expect(result.workerCaps.triage).toBeNull()
  })

  describe('workload aggregate', () => {
    it('computes workload totals from pipeline issues plus merged session count', () => {
      const pipeline = {
        ...emptyPipeline,
        triage: [{ issue_number: 1, status: 'active' }],
        implement: [{ issue_number: 2, status: 'failed' }],
        review: [{ issue_number: 3, status: 'queued' }],
      }
      const workers = {
        1: { role: 'implementer', status: 'running' },
        2: { role: 'implementer', status: 'done' },
        3: { role: 'implementer', status: 'failed' },
        4: { role: 'planner', status: 'planning' },
        5: { role: 'reviewer', status: 'queued' },
      }

      const result = deriveStageStatus(pipeline, workers, [], { mergedCount: 2 })

      expect(result.workload).toEqual({
        total: 5,   // 3 open pipeline issues + 2 merged
        active: 2,  // max(pipeline active=1, worker active=2)
        done: 2,    // mergedCount from session counters
        failed: 1,
      })
    })

    it('done uses mergedCount from session counters, not worker status', () => {
      const workers = {
        1: { role: 'implementer', status: 'done' },
        2: { role: 'implementer', status: 'done' },
        3: { role: 'planner', status: 'done' },
        4: { role: 'reviewer', status: 'done' },
        5: { role: 'implementer', status: 'done' },
      }

      const result = deriveStageStatus(emptyPipeline, workers, [], { mergedCount: 2 })

      expect(result.workload.done).toBe(2)
    })

    it('returns all zeros for empty workers and empty pipeline', () => {
      const result = deriveStageStatus(emptyPipeline, {}, [], {})
      expect(result.workload).toEqual({ total: 0, active: 0, done: 0, failed: 0 })
    })

    it('keeps active non-zero when workers are active but pipeline snapshot lags', () => {
      const workers = {
        1: { role: 'implementer', status: 'quality_fix' },
        2: { role: 'implementer', status: 'queued' },
      }

      const result = deriveStageStatus(emptyPipeline, workers, [], {})
      expect(result.workload.active).toBe(1)
      expect(result.workload.total).toBe(0)
    })

    it('done is 0 when no merges have occurred', () => {
      const workers = {
        1: { role: 'implementer', status: 'running' },
        2: { role: 'implementer', status: 'testing' },
        3: { role: 'planner', status: 'planning' },
      }
      const result = deriveStageStatus(emptyPipeline, workers, [], {})
      expect(result.workload).toEqual({ total: 0, active: 3, done: 0, failed: 0 })
    })
  })

  it('handles a full realistic scenario', () => {
    const pipeline = {
      triage: [{ issue_number: 1, status: 'active' }],
      plan: [{ issue_number: 2, status: 'queued' }, { issue_number: 3, status: 'active' }],
      implement: [{ issue_number: 4, status: 'active' }],
      review: [],
      hitl: [{ issue_number: 5, status: 'queued' }],
    }
    const workers = {
      'triage-1': { role: 'triage', status: 'evaluating' },
      'plan-3': { role: 'planner', status: 'planning' },
      4: { role: 'implementer', status: 'running' },
      6: { role: 'implementer', status: 'done' },
    }
    const bgWorkers = [
      { name: 'triage', enabled: true },
      { name: 'plan', enabled: true },
      { name: 'implement', enabled: false },
      { name: 'review', enabled: true },
    ]
    const counters = {
      sessionTriaged: 2,
      sessionPlanned: 1,
      sessionImplemented: 4,
      sessionReviewed: 0,
      mergedCount: 3,
    }

    const result = deriveStageStatus(pipeline, workers, bgWorkers, counters)

    expect(result.triage).toEqual({
      issueCount: 1, activeCount: 1, queuedCount: 0,
      workerCount: 1, enabled: true, sessionCount: 2,
    })
    expect(result.plan).toEqual({
      issueCount: 2, activeCount: 1, queuedCount: 1,
      workerCount: 1, enabled: true, sessionCount: 1,
    })
    expect(result.implement).toEqual({
      issueCount: 1, activeCount: 1, queuedCount: 0,
      workerCount: 1, enabled: false, sessionCount: 4,
    })
    expect(result.review).toEqual({
      issueCount: 0, activeCount: 0, queuedCount: 0,
      workerCount: 0, enabled: true, sessionCount: 0,
    })
    expect(result.merged).toEqual({
      issueCount: 0, activeCount: 0, queuedCount: 0,
      workerCount: 0, enabled: true, sessionCount: 3,
    })
    expect(result.workload).toEqual({
      total: 8, active: 3, done: 3, failed: 0,  // 5 open (incl hitl) + 3 merged
    })
  })
})
