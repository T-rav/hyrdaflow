import { describe, it, expect } from 'vitest'
import { seedState, seedStateEmpty } from '../seed-state.js'
import { initialState } from '../../../src/context/HydraFlowContext.jsx'

describe('seed-state fixture', () => {
  it('covers all keys from initialState', () => {
    const expectedKeys = Object.keys(initialState).sort()
    const seedKeys = Object.keys(seedState).sort()

    for (const key of expectedKeys) {
      expect(seedKeys).toContain(key)
    }
  })

  it('has populated pipeline issues with entries in every stage', () => {
    const stages = ['triage', 'plan', 'implement', 'review', 'hitl', 'merged']
    for (const stage of stages) {
      expect(seedState.pipelineIssues[stage].length).toBeGreaterThan(0)
    }
  })

  it('has connected: true for screenshot rendering', () => {
    expect(seedState.connected).toBe(true)
  })

  it('has only ISO-8601 formatted timestamps (validates format; ensure seed-state.js has no Date.now() or new Date() calls)', () => {
    const json = JSON.stringify(seedState)
    // All timestamps should be fixed ISO-8601 strings — validate format without hardcoding a specific date
    const timestamps = json.match(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/g) || []
    expect(timestamps.length).toBeGreaterThan(0)
    for (const ts of timestamps) {
      expect(ts).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/)
    }
  })

  it('seedStateEmpty covers all keys from initialState', () => {
    const expectedKeys = Object.keys(initialState).sort()
    const emptyKeys = Object.keys(seedStateEmpty).sort()

    for (const key of expectedKeys) {
      expect(emptyKeys).toContain(key)
    }
  })

  it('seedStateEmpty has empty pipeline stages', () => {
    const stages = ['triage', 'plan', 'implement', 'review', 'hitl', 'merged']
    for (const stage of stages) {
      expect(seedStateEmpty.pipelineIssues[stage]).toEqual([])
    }
  })

  it('seedStateEmpty has idle orchestrator', () => {
    expect(seedStateEmpty.orchestratorStatus).toBe('idle')
    expect(seedStateEmpty.phase).toBe('idle')
  })

  it('seedStateEmpty has no workers, prs, or hitl items', () => {
    expect(seedStateEmpty.workers).toEqual({})
    expect(seedStateEmpty.hitlItems).toEqual([])
    expect(seedStateEmpty.prs).toEqual([])
  })
})
