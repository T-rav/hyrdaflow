import { describe, it, expect } from 'vitest'
import { ACTIVE_STATUSES, PIPELINE_STAGES, PIPELINE_LOOPS, INTERVAL_PRESETS, EDITABLE_INTERVAL_WORKERS } from '../../constants'
import { theme } from '../../theme'

describe('ACTIVE_STATUSES', () => {
  it('is an array', () => {
    expect(Array.isArray(ACTIVE_STATUSES)).toBe(true)
  })

  it('contains expected active statuses', () => {
    expect(ACTIVE_STATUSES).toEqual([
      'running', 'testing', 'committing', 'reviewing', 'planning', 'quality_fix',
      'start', 'merge_main', 'merge_fix', 'ci_wait', 'ci_fix', 'merging',
      'evaluating', 'validating', 'retrying', 'fixing',
    ])
  })

  it('includes quality_fix status', () => {
    expect(ACTIVE_STATUSES).toContain('quality_fix')
  })

  it('includes merge_fix status', () => {
    expect(ACTIVE_STATUSES).toContain('merge_fix')
  })

  it('does not include terminal statuses', () => {
    const terminalStatuses = ['queued', 'done', 'failed']
    for (const status of terminalStatuses) {
      expect(ACTIVE_STATUSES).not.toContain(status)
    }
  })
})

describe('PIPELINE_STAGES', () => {
  it('is an array with 5 stages', () => {
    expect(Array.isArray(PIPELINE_STAGES)).toBe(true)
    expect(PIPELINE_STAGES).toHaveLength(5)
  })

  it('contains all pipeline stage keys in order', () => {
    const keys = PIPELINE_STAGES.map(s => s.key)
    expect(keys).toEqual(['triage', 'plan', 'implement', 'review', 'merged'])
  })

  it('has title-case labels for each stage', () => {
    const labels = PIPELINE_STAGES.map(s => s.label)
    expect(labels).toEqual(['Triage', 'Plan', 'Implement', 'Review', 'Merged'])
  })

  it('maps each stage to the correct theme color', () => {
    const colorMap = Object.fromEntries(PIPELINE_STAGES.map(s => [s.key, s.color]))
    expect(colorMap).toEqual({
      triage: theme.yellow,
      plan: theme.purple,
      implement: theme.accent,
      review: theme.orange,
      merged: theme.green,
    })
  })

  it('assigns roles to active stages and null to merged', () => {
    const roleMap = Object.fromEntries(PIPELINE_STAGES.map(s => [s.key, s.role]))
    expect(roleMap).toEqual({
      triage: 'triage',
      plan: 'planner',
      implement: 'implementer',
      review: 'reviewer',
      merged: null,
    })
  })

  it('assigns configKeys to plan, implement, review and null to triage/merged', () => {
    const configMap = Object.fromEntries(PIPELINE_STAGES.map(s => [s.key, s.configKey]))
    expect(configMap).toEqual({
      triage: 'max_triagers',
      plan: 'max_planners',
      implement: 'max_workers',
      review: 'max_reviewers',
      merged: null,
    })
  })

  it('maps each stage to the correct subtle color', () => {
    const subtleMap = Object.fromEntries(PIPELINE_STAGES.map(s => [s.key, s.subtleColor]))
    expect(subtleMap).toEqual({
      triage: theme.yellowSubtle,
      plan: theme.purpleSubtle,
      implement: theme.accentSubtle,
      review: theme.orangeSubtle,
      merged: theme.greenSubtle,
    })
  })

  it('every stage has key, label, color, subtleColor, role, and configKey properties', () => {
    for (const stage of PIPELINE_STAGES) {
      expect(stage).toHaveProperty('key')
      expect(stage).toHaveProperty('label')
      expect(stage).toHaveProperty('color')
      expect(stage).toHaveProperty('subtleColor')
      expect(stage).toHaveProperty('role')
      expect(stage).toHaveProperty('configKey')
    }
  })

  it('has unique keys', () => {
    const keys = PIPELINE_STAGES.map(s => s.key)
    expect(new Set(keys).size).toBe(keys.length)
  })
})

describe('PIPELINE_LOOPS', () => {
  it('has entries for all non-merged pipeline stages', () => {
    const stageKeys = PIPELINE_STAGES.filter(s => s.key !== 'merged').map(s => s.key)
    expect(PIPELINE_LOOPS.map(l => l.key)).toEqual(stageKeys)
  })

  it('every loop has key, label, color, and dimColor properties', () => {
    for (const loop of PIPELINE_LOOPS) {
      expect(loop).toHaveProperty('key')
      expect(loop).toHaveProperty('label')
      expect(loop).toHaveProperty('color')
      expect(loop).toHaveProperty('dimColor')
    }
  })
})

describe('INTERVAL_PRESETS', () => {
  it('has expected number of presets', () => {
    expect(INTERVAL_PRESETS).toHaveLength(4)
  })

  it('each preset has label and seconds', () => {
    for (const preset of INTERVAL_PRESETS) {
      expect(preset).toHaveProperty('label')
      expect(preset).toHaveProperty('seconds')
      expect(typeof preset.seconds).toBe('number')
    }
  })

  it('presets are in ascending order', () => {
    for (let i = 1; i < INTERVAL_PRESETS.length; i++) {
      expect(INTERVAL_PRESETS[i].seconds).toBeGreaterThan(INTERVAL_PRESETS[i - 1].seconds)
    }
  })
})

describe('EDITABLE_INTERVAL_WORKERS', () => {
  it('includes memory_sync and metrics', () => {
    expect(EDITABLE_INTERVAL_WORKERS.has('memory_sync')).toBe(true)
    expect(EDITABLE_INTERVAL_WORKERS.has('metrics')).toBe(true)
  })

  it('does not include non-editable workers', () => {
    expect(EDITABLE_INTERVAL_WORKERS.has('retrospective')).toBe(false)
    expect(EDITABLE_INTERVAL_WORKERS.has('triage')).toBe(false)
  })
})
