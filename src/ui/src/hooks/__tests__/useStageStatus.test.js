import { describe, it, expect } from 'vitest'
import { deriveStageStatus } from '../useStageStatus'

describe('deriveStageStatus', () => {
  const emptyPipeline = { triage: [], plan: [], implement: [], review: [], hitl: [] }

  const makePipelineStats = (overrides = {}) => ({
    timestamp: '2026-03-06T00:00:00Z',
    stages: {
      triage: { queued: 0, active: 0, completed_session: 0, completed_lifetime: 0, worker_count: 0, worker_cap: null },
      plan: { queued: 0, active: 0, completed_session: 0, completed_lifetime: 0, worker_count: 0, worker_cap: null },
      implement: { queued: 0, active: 0, completed_session: 0, completed_lifetime: 0, worker_count: 0, worker_cap: null },
      review: { queued: 0, active: 0, completed_session: 0, completed_lifetime: 0, worker_count: 0, worker_cap: null },
      hitl: { queued: 0, active: 0, completed_session: 0, completed_lifetime: 0, worker_count: 0, worker_cap: null },
      merged: { queued: 0, active: 0, completed_session: 0, completed_lifetime: 0, worker_count: 0, worker_cap: null },
      ...overrides,
    },
  })

  it('returns all zeros when pipelineStats has zero values', () => {
    const result = deriveStageStatus({}, {}, [], makePipelineStats())

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

  it('returns all zeros and null workerCaps when pipelineStats is null', () => {
    const result = deriveStageStatus(null, null, null, null)

    expect(result.triage.issueCount).toBe(0)
    expect(result.triage.sessionCount).toBe(0)
    expect(result.triage.activeCount).toBe(0)
    expect(result.triage.queuedCount).toBe(0)
    expect(result.triage.workerCount).toBe(0)
    expect(result.workload.total).toBe(0)
    expect(result.workload.done).toBe(0)
    expect(result.workerCaps).toEqual({
      triage: null, plan: null, implement: null, review: null,
    })
  })

  it('handles partial pipelineStats stages (some stages missing)', () => {
    const stats = makePipelineStats({
      triage: { queued: 2, active: 1, completed_session: 5, completed_lifetime: 10, worker_count: 1, worker_cap: 2 },
    })
    delete stats.stages.plan
    delete stats.stages.implement

    const result = deriveStageStatus(emptyPipeline, {}, [], stats)

    expect(result.triage.sessionCount).toBe(5)
    expect(result.triage.workerCount).toBe(1)
    expect(result.plan.sessionCount).toBe(0)
    expect(result.plan.workerCount).toBe(0)
    expect(result.implement.sessionCount).toBe(0)
  })

  it('uses pipelineStats for sessionCount, activeCount, queuedCount, workerCount', () => {
    const stats = makePipelineStats({
      triage: { queued: 3, active: 2, completed_session: 10, completed_lifetime: 50, worker_count: 1, worker_cap: 2 },
      implement: { queued: 1, active: 4, completed_session: 20, completed_lifetime: 100, worker_count: 3, worker_cap: 5 },
    })

    const result = deriveStageStatus(emptyPipeline, {}, [], stats)

    expect(result.triage.sessionCount).toBe(10)
    expect(result.triage.activeCount).toBe(2)
    expect(result.triage.queuedCount).toBe(3)
    expect(result.triage.workerCount).toBe(1)

    expect(result.implement.sessionCount).toBe(20)
    expect(result.implement.activeCount).toBe(4)
    expect(result.implement.queuedCount).toBe(1)
    expect(result.implement.workerCount).toBe(3)
  })

  it('uses pipelineStats worker_cap for workerCaps', () => {
    const stats = makePipelineStats({
      triage: { queued: 0, active: 0, completed_session: 0, completed_lifetime: 0, worker_count: 0, worker_cap: 2 },
      plan: { queued: 0, active: 0, completed_session: 0, completed_lifetime: 0, worker_count: 0, worker_cap: 3 },
      implement: { queued: 0, active: 0, completed_session: 0, completed_lifetime: 0, worker_count: 0, worker_cap: 5 },
      review: { queued: 0, active: 0, completed_session: 0, completed_lifetime: 0, worker_count: 0, worker_cap: 4 },
    })

    const result = deriveStageStatus(emptyPipeline, {}, [], stats)

    expect(result.workerCaps).toEqual({
      triage: 2,
      plan: 3,
      implement: 5,
      review: 4,
    })
  })

  it('gets issueCount from pipelineIssues (for card rendering)', () => {
    const pipeline = {
      ...emptyPipeline,
      triage: [
        { issue_number: 1, status: 'active' },
        { issue_number: 2, status: 'queued' },
      ],
      implement: [
        { issue_number: 4, status: 'active' },
        { issue_number: 5, status: 'active' },
        { issue_number: 6, status: 'queued' },
      ],
    }

    const result = deriveStageStatus(pipeline, {}, [], makePipelineStats())

    expect(result.triage.issueCount).toBe(2)
    expect(result.implement.issueCount).toBe(3)
    expect(result.review.issueCount).toBe(0)
  })

  it('computes enabled state from backgroundWorkers', () => {
    const bgWorkers = [
      { name: 'triage', enabled: true },
      { name: 'plan', enabled: false },
      { name: 'implement', enabled: true },
      { name: 'review', enabled: false },
    ]

    const result = deriveStageStatus(emptyPipeline, {}, bgWorkers, makePipelineStats())

    expect(result.triage.enabled).toBe(true)
    expect(result.plan.enabled).toBe(false)
    expect(result.implement.enabled).toBe(true)
    expect(result.review.enabled).toBe(false)
  })

  it('merged stage is always enabled (no pipeline loop)', () => {
    const bgWorkers = [
      { name: 'triage', enabled: false },
    ]
    const result = deriveStageStatus(emptyPipeline, {}, bgWorkers, makePipelineStats())
    expect(result.merged.enabled).toBe(true)
  })

  it('defaults enabled to true when bg worker not in state', () => {
    const result = deriveStageStatus(emptyPipeline, {}, [], makePipelineStats())
    expect(result.triage.enabled).toBe(true)
    expect(result.plan.enabled).toBe(true)
  })

  it('uses pipelineStats.stages.merged.completed_session for workload.done', () => {
    const stats = makePipelineStats({
      merged: { queued: 0, active: 0, completed_session: 15, completed_lifetime: 100, worker_count: 0, worker_cap: null },
    })

    const result = deriveStageStatus(emptyPipeline, {}, [], stats)

    expect(result.workload.done).toBe(15)
    expect(result.merged.sessionCount).toBe(15)
  })

  describe('workload aggregate', () => {
    it('computes workload totals from pipeline issues plus merged from pipelineStats', () => {
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
      const stats = makePipelineStats({
        merged: { queued: 0, active: 0, completed_session: 2, completed_lifetime: 10, worker_count: 0, worker_cap: null },
      })

      const result = deriveStageStatus(pipeline, workers, [], stats)

      expect(result.workload).toEqual({
        total: 5,   // 3 open pipeline issues + 2 merged
        active: 2,  // max(pipeline active=1, worker active=2)
        done: 2,
        failed: 1,
      })
    })

    it('returns all zeros for empty workers and empty pipeline', () => {
      const result = deriveStageStatus(emptyPipeline, {}, [], makePipelineStats())
      expect(result.workload).toEqual({ total: 0, active: 0, done: 0, failed: 0 })
    })

    it('keeps active non-zero when workers are active but pipeline snapshot lags', () => {
      const workers = {
        1: { role: 'implementer', status: 'quality_fix' },
        2: { role: 'implementer', status: 'queued' },
      }

      const result = deriveStageStatus(emptyPipeline, workers, [], makePipelineStats())
      expect(result.workload.active).toBe(1)
      expect(result.workload.total).toBe(0)
    })

    it('done is 0 when pipelineStats merged.completed_session is 0', () => {
      const workers = {
        1: { role: 'implementer', status: 'running' },
        2: { role: 'implementer', status: 'testing' },
        3: { role: 'planner', status: 'planning' },
      }
      const result = deriveStageStatus(emptyPipeline, workers, [], makePipelineStats())
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
    const stats = makePipelineStats({
      triage: { queued: 0, active: 1, completed_session: 2, completed_lifetime: 10, worker_count: 1, worker_cap: 2 },
      plan: { queued: 1, active: 1, completed_session: 1, completed_lifetime: 5, worker_count: 1, worker_cap: 3 },
      implement: { queued: 0, active: 1, completed_session: 4, completed_lifetime: 20, worker_count: 1, worker_cap: 5 },
      review: { queued: 0, active: 0, completed_session: 0, completed_lifetime: 0, worker_count: 0, worker_cap: 2 },
      merged: { queued: 0, active: 0, completed_session: 3, completed_lifetime: 15, worker_count: 0, worker_cap: null },
    })

    const result = deriveStageStatus(pipeline, workers, bgWorkers, stats)

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
      total: 8, active: 3, done: 3, failed: 0,
    })
    expect(result.workerCaps).toEqual({
      triage: 2, plan: 3, implement: 5, review: 2,
    })
  })
})
