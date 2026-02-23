import { describe, it, expect } from 'vitest'
import { PIPELINE_STAGES } from '../../constants'
import {
  sectionHeaderStyles,
  sectionLabelStyles,
  sectionCountStyles,
} from '../sectionStyles'

describe('sectionStyles shared module', () => {
  const stageKeys = PIPELINE_STAGES.map(s => s.key)

  describe('sectionHeaderStyles', () => {
    it('has an entry for every PIPELINE_STAGES key', () => {
      for (const key of stageKeys) {
        expect(sectionHeaderStyles).toHaveProperty(key)
      }
    })

    it('includes correct base properties in each entry', () => {
      for (const key of stageKeys) {
        const style = sectionHeaderStyles[key]
        expect(style.display).toBe('flex')
        expect(style.alignItems).toBe('center')
        expect(style.gap).toBe(8)
        expect(style.padding).toBe('8px 12px')
        expect(style.margin).toBe('8px 8px 4px')
        expect(style.cursor).toBe('pointer')
        expect(style.userSelect).toBe('none')
        expect(style.borderRadius).toBe(6)
        expect(style.transition).toBe('background 0.15s')
      }
    })

    it('applies correct stage-specific background, border, and borderLeft', () => {
      for (const stage of PIPELINE_STAGES) {
        const style = sectionHeaderStyles[stage.key]
        expect(style.background).toBe(stage.subtleColor)
        // border uses color+33 (20% alpha) to remain visible against the subtleColor background (15% alpha)
        expect(style.border).toBe(`1px solid ${stage.color}33`)
        expect(style.borderLeft).toBe(`3px solid ${stage.color}`)
      }
    })
  })

  describe('sectionLabelStyles', () => {
    it('has an entry for every PIPELINE_STAGES key', () => {
      for (const key of stageKeys) {
        expect(sectionLabelStyles).toHaveProperty(key)
      }
    })

    it('includes correct base properties in each entry', () => {
      for (const key of stageKeys) {
        const style = sectionLabelStyles[key]
        expect(style.fontSize).toBe(11)
        expect(style.fontWeight).toBe(600)
        expect(style.textTransform).toBe('uppercase')
        expect(style.letterSpacing).toBe('0.5px')
      }
    })

    it('applies correct stage color', () => {
      for (const stage of PIPELINE_STAGES) {
        expect(sectionLabelStyles[stage.key].color).toBe(stage.color)
      }
    })
  })

  describe('sectionCountStyles', () => {
    it('has an entry for every PIPELINE_STAGES key', () => {
      for (const key of stageKeys) {
        expect(sectionCountStyles).toHaveProperty(key)
      }
    })

    it('includes correct base properties in each entry', () => {
      for (const key of stageKeys) {
        const style = sectionCountStyles[key]
        expect(style.fontSize).toBe(11)
        expect(style.fontWeight).toBe(600)
        expect(style.marginLeft).toBe('auto')
      }
    })

    it('applies correct stage color', () => {
      for (const stage of PIPELINE_STAGES) {
        expect(sectionCountStyles[stage.key].color).toBe(stage.color)
      }
    })
  })

})
