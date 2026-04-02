import { describe, it, expect } from 'vitest'
import { ACTIVE_STATUSES, PIPELINE_STAGES, PIPELINE_LOOPS, INTERVAL_PRESETS, EDITABLE_INTERVAL_WORKERS, REPORT_ISSUE_PRESETS, WORKER_PRESETS, PIPELINE_POLLER_PRESETS, ADR_REVIEWER_PRESETS, BOT_PR_PRESETS, BACKGROUND_WORKERS } from '../../constants'
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

  it('every loop has key, label, color, dimColor, and configKey properties', () => {
    for (const loop of PIPELINE_LOOPS) {
      expect(loop).toHaveProperty('key')
      expect(loop).toHaveProperty('label')
      expect(loop).toHaveProperty('color')
      expect(loop).toHaveProperty('dimColor')
      expect(loop).toHaveProperty('configKey')
    }
  })

  it('maps each loop to the correct configKey', () => {
    const configMap = Object.fromEntries(PIPELINE_LOOPS.map(l => [l.key, l.configKey]))
    expect(configMap).toEqual({
      triage: 'max_triagers',
      plan: 'max_planners',
      implement: 'max_workers',
      review: 'max_reviewers',
    })
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
  it('includes memory_sync', () => {
    expect(EDITABLE_INTERVAL_WORKERS.has('memory_sync')).toBe(true)
  })

  it('includes report_issue', () => {
    expect(EDITABLE_INTERVAL_WORKERS.has('report_issue')).toBe(true)
  })

  it('does not include non-editable workers', () => {
    expect(EDITABLE_INTERVAL_WORKERS.has('retrospective')).toBe(false)
    expect(EDITABLE_INTERVAL_WORKERS.has('triage')).toBe(false)
  })
})

describe('REPORT_ISSUE_PRESETS', () => {
  it('has 4 presets', () => {
    expect(REPORT_ISSUE_PRESETS).toHaveLength(4)
  })

  it('each preset has label and seconds', () => {
    for (const preset of REPORT_ISSUE_PRESETS) {
      expect(preset).toHaveProperty('label')
      expect(preset).toHaveProperty('seconds')
      expect(typeof preset.seconds).toBe('number')
    }
  })

  it('presets are in ascending order', () => {
    for (let i = 1; i < REPORT_ISSUE_PRESETS.length; i++) {
      expect(REPORT_ISSUE_PRESETS[i].seconds).toBeGreaterThan(REPORT_ISSUE_PRESETS[i - 1].seconds)
    }
  })

  it('contains the expected values', () => {
    expect(REPORT_ISSUE_PRESETS).toEqual([
      { label: '30s', seconds: 30 },
      { label: '1m', seconds: 60 },
      { label: '5m', seconds: 300 },
      { label: '10m', seconds: 600 },
    ])
  })
})

describe('BOT_PR_PRESETS', () => {
  it('has 5 presets from 1h to 24h', () => {
    expect(BOT_PR_PRESETS).toHaveLength(5)
    expect(BOT_PR_PRESETS[0].seconds).toBe(3600)
    expect(BOT_PR_PRESETS[4].seconds).toBe(86400)
  })
})

describe('BACKGROUND_WORKERS bot_pr entry', () => {
  it('includes bot_pr worker', () => {
    const botPr = BACKGROUND_WORKERS.find(w => w.key === 'bot_pr')
    expect(botPr).toBeDefined()
    expect(botPr.label).toBe('Bot PR Manager')
  })
})

describe('EDITABLE_INTERVAL_WORKERS includes bot_pr', () => {
  it('bot_pr is editable', () => {
    expect(EDITABLE_INTERVAL_WORKERS.has('bot_pr')).toBe(true)
  })
})

describe('WORKER_PRESETS', () => {
  it('has exactly the expected worker keys', () => {
    expect(Object.keys(WORKER_PRESETS).sort()).toEqual(['adr_reviewer', 'bot_pr', 'ci_monitor', 'code_grooming', 'pipeline_poller', 'report_issue', 'security_patch', 'sentry_ingest', 'stale_issue'])
  })

  it('maps pipeline_poller to PIPELINE_POLLER_PRESETS', () => {
    expect(WORKER_PRESETS.pipeline_poller).toBe(PIPELINE_POLLER_PRESETS)
  })

  it('maps adr_reviewer to ADR_REVIEWER_PRESETS', () => {
    expect(WORKER_PRESETS.adr_reviewer).toBe(ADR_REVIEWER_PRESETS)
  })

  it('maps report_issue to REPORT_ISSUE_PRESETS', () => {
    expect(WORKER_PRESETS.report_issue).toBe(REPORT_ISSUE_PRESETS)
  })
})
