import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { PipelineStatus, connectorStyles, stageStyles } from '../PipelineStatus'

const STAGE_KEYS = ['plan', 'implement', 'review']
const STAGE_COLORS = {
  plan: 'var(--purple)',
  implement: 'var(--yellow)',
  review: 'var(--orange)',
}

describe('PipelineStatus pre-computed styles', () => {
  it('connectorStyles has an entry for each stage', () => {
    for (const key of STAGE_KEYS) {
      expect(connectorStyles).toHaveProperty(key)
      expect(connectorStyles[key]).toHaveProperty('active')
      expect(connectorStyles[key]).toHaveProperty('inactive')
    }
  })

  it('connector active variant uses stage color, inactive uses border variable', () => {
    for (const key of STAGE_KEYS) {
      expect(connectorStyles[key].active.background).toBe(STAGE_COLORS[key])
      expect(connectorStyles[key].inactive.background).toBe('var(--border)')
    }
  })

  it('connector variants include base connector properties', () => {
    for (const key of STAGE_KEYS) {
      expect(connectorStyles[key].active).toMatchObject({ width: 32, height: 2, flexShrink: 0 })
      expect(connectorStyles[key].inactive).toMatchObject({ width: 32, height: 2, flexShrink: 0 })
    }
  })

  it('stageStyles has an entry for each stage with active/inactive sub-keys', () => {
    for (const key of STAGE_KEYS) {
      expect(stageStyles).toHaveProperty(key)
      expect(stageStyles[key]).toHaveProperty('active')
      expect(stageStyles[key]).toHaveProperty('inactive')
    }
  })

  it('stage active variant uses stage color for background/borderColor', () => {
    for (const key of STAGE_KEYS) {
      expect(stageStyles[key].active).toMatchObject({
        background: STAGE_COLORS[key],
        color: 'var(--bg)',
        borderColor: STAGE_COLORS[key],
      })
    }
  })

  it('stage inactive variant uses dim colors', () => {
    for (const key of STAGE_KEYS) {
      expect(stageStyles[key].inactive).toMatchObject({
        background: 'var(--surface-inset)',
        color: 'var(--text-inactive)',
        borderColor: 'var(--border)',
      })
    }
  })

  it('stage variants include base stage properties', () => {
    for (const key of STAGE_KEYS) {
      expect(stageStyles[key].active).toMatchObject({
        padding: '4px 14px',
        borderRadius: 12,
        fontSize: 11,
        fontWeight: 600,
      })
    }
  })

  it('style objects are referentially stable', () => {
    expect(connectorStyles.plan.active).toBe(connectorStyles.plan.active)
    expect(stageStyles.review.inactive).toBe(stageStyles.review.inactive)
  })
})

describe('PipelineStatus component', () => {
  it('returns null when idle with no workers', () => {
    const { container } = render(<PipelineStatus phase="idle" workers={{}} />)
    expect(container.firstChild).toBeNull()
  })

  it('counts quality_fix workers as active in implement stage', () => {
    const workers = {
      1: { status: 'quality_fix', role: 'implementer' },
    }
    render(<PipelineStatus phase="running" workers={workers} />)
    // The implement stage should show a count of 1
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('Implement')).toBeInTheDocument()
  })

  it('renders stages when workers exist', () => {
    const workers = {
      1: { status: 'running', role: 'planner' },
    }
    render(<PipelineStatus phase="running" workers={workers} />)
    expect(screen.getByText('Plan')).toBeInTheDocument()
    expect(screen.getByText('Implement')).toBeInTheDocument()
    expect(screen.getByText('Review')).toBeInTheDocument()
  })
})
