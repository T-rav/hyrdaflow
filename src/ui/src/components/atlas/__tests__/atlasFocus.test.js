import { describe, it, expect } from 'vitest'
import { computeFocusSet } from '../atlasFocus'

const PAYLOAD = {
  nodes: [
    { id: 'a' },
    { id: 'b' },
    { id: 'c' },
    { id: 'd' },
  ],
  edges: [
    { source: 'a', target: 'b', kind: 'depends_on' },
    { source: 'a', target: 'c', kind: 'depends_on' },
    { source: 'd', target: 'c', kind: 'depends_on' },
  ],
}

describe('computeFocusSet', () => {
  it('returns null when nothing is selected', () => {
    expect(computeFocusSet(PAYLOAD, null)).toBe(null)
  })

  it('returns null when payload is falsy', () => {
    expect(computeFocusSet(null, 'a')).toBe(null)
  })

  it('includes the selected node and its outgoing neighbours', () => {
    const set = computeFocusSet(PAYLOAD, 'a')
    expect(set.has('a')).toBe(true)
    expect(set.has('b')).toBe(true)
    expect(set.has('c')).toBe(true)
    expect(set.has('d')).toBe(false)
  })

  it('includes incoming neighbours too', () => {
    const set = computeFocusSet(PAYLOAD, 'c')
    expect(set.has('c')).toBe(true)
    expect(set.has('a')).toBe(true)
    expect(set.has('d')).toBe(true)
    expect(set.has('b')).toBe(false)
  })

  it('returns a single-member set for an isolated node', () => {
    const set = computeFocusSet({ nodes: [{ id: 'x' }], edges: [] }, 'x')
    expect([...set]).toEqual(['x'])
  })
})
