// localStorage-backed saved-view store for the Atlas filter state.
//
// Pure functions — no React. Tested in isolation. The shape is intentionally
// small (a flat record of {name → filters}) so it survives a JSON round-trip
// without versioning machinery; if the filter schema changes, unknown keys
// are silently dropped on load.

const STORAGE_KEY = 'atlas-saved-views'

export function loadSavedViews() {
  if (typeof window === 'undefined' || !window.localStorage) return {}
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object') return parsed
    return {}
  } catch {
    return {}
  }
}

function persist(views) {
  if (typeof window === 'undefined' || !window.localStorage) return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(views))
  } catch {
    // Quota / private browsing — silently no-op. The in-memory state still
    // works for the session.
  }
}

export function saveView(name, filters) {
  const trimmed = String(name || '').trim()
  if (!trimmed) return loadSavedViews()
  const views = loadSavedViews()
  views[trimmed] = { ...filters }
  persist(views)
  return views
}

export function deleteSavedView(name) {
  const views = loadSavedViews()
  delete views[name]
  persist(views)
  return views
}
