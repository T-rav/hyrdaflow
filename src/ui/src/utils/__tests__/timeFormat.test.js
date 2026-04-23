import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { formatRelative, formatDuration } from '../timeFormat'

describe('formatRelative', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-22T12:00:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns "just now" for less than 30 seconds ago', () => {
    expect(formatRelative('2026-04-22T11:59:45Z')).toBe('just now')
  })

  it('returns seconds when under a minute', () => {
    expect(formatRelative('2026-04-22T11:59:15Z')).toBe('45s ago')
  })

  it('returns minutes when under an hour', () => {
    expect(formatRelative('2026-04-22T11:45:00Z')).toBe('15m ago')
  })

  it('returns hours when under a day', () => {
    expect(formatRelative('2026-04-22T09:00:00Z')).toBe('3h ago')
  })

  it('returns days when over a day', () => {
    expect(formatRelative('2026-04-20T12:00:00Z')).toBe('2d ago')
  })

  it('returns empty string for null or undefined input', () => {
    expect(formatRelative(null)).toBe('')
    expect(formatRelative(undefined)).toBe('')
  })

  it('returns empty string for invalid timestamp', () => {
    expect(formatRelative('not-a-date')).toBe('')
  })
})

describe('formatDuration', () => {
  it('returns seconds when under a minute', () => {
    expect(formatDuration('2026-04-22T12:00:00Z', '2026-04-22T12:00:45Z')).toBe('45s')
  })

  it('returns "0s" for equal timestamps', () => {
    expect(formatDuration('2026-04-22T12:00:00Z', '2026-04-22T12:00:00Z')).toBe('0s')
  })

  it('returns minutes when under an hour', () => {
    expect(formatDuration('2026-04-22T12:00:00Z', '2026-04-22T12:42:00Z')).toBe('42min')
  })

  it('returns hours + minutes when over an hour', () => {
    expect(formatDuration('2026-04-22T12:00:00Z', '2026-04-22T13:12:00Z')).toBe('1h 12min')
  })

  it('omits zero-minute suffix at exact hour', () => {
    expect(formatDuration('2026-04-22T12:00:00Z', '2026-04-22T14:00:00Z')).toBe('2h')
  })

  it('returns empty string for missing or invalid inputs', () => {
    expect(formatDuration(null, '2026-04-22T12:00:00Z')).toBe('')
    expect(formatDuration('2026-04-22T12:00:00Z', null)).toBe('')
    expect(formatDuration('nope', '2026-04-22T12:00:00Z')).toBe('')
  })

  it('returns empty string when end is before start', () => {
    expect(formatDuration('2026-04-22T12:01:00Z', '2026-04-22T12:00:00Z')).toBe('')
  })
})
