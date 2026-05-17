import { describe, it, expect, beforeEach } from 'vitest'
import {
  loadSavedViews,
  saveView,
  deleteSavedView,
} from '../atlasSavedViews'

beforeEach(() => {
  window.localStorage.clear()
})

describe('atlasSavedViews', () => {
  it('returns an empty object when no views are saved', () => {
    expect(loadSavedViews()).toEqual({})
  })

  it('saves and loads a view', () => {
    const filters = { kind: 'runner', context: 'builder', confidence: '' }
    saveView('builder runners', filters)
    expect(loadSavedViews()).toEqual({ 'builder runners': filters })
  })

  it('overwrites an existing view with the same name', () => {
    saveView('view', { kind: 'service', context: '', confidence: '' })
    saveView('view', { kind: 'port', context: '', confidence: '' })
    expect(loadSavedViews().view).toEqual({
      kind: 'port',
      context: '',
      confidence: '',
    })
  })

  it('trims whitespace and ignores empty names', () => {
    saveView('  ', { kind: '', context: '', confidence: '' })
    expect(loadSavedViews()).toEqual({})
    saveView('  named  ', { kind: 'service', context: '', confidence: '' })
    expect(Object.keys(loadSavedViews())).toEqual(['named'])
  })

  it('deletes a view', () => {
    saveView('a', { kind: '', context: '', confidence: '' })
    saveView('b', { kind: 'runner', context: '', confidence: '' })
    deleteSavedView('a')
    expect(Object.keys(loadSavedViews())).toEqual(['b'])
  })

  it('returns an empty object when localStorage holds invalid JSON', () => {
    window.localStorage.setItem('atlas-saved-views', '{not json')
    expect(loadSavedViews()).toEqual({})
  })
})
