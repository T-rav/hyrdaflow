import React, { useState, useMemo } from 'react'
import { theme } from '../theme'
import { EPIC_FILTERS } from '../constants'
import { useHydraFlow } from '../context/HydraFlowContext'
import { EpicCard } from './EpicCard'

/**
 * Classifies an epic into a filter category.
 * ready_to_release: all children merged but epic not released
 * released: epic status is 'released' or 'completed'
 * active: everything else
 */
function epicCategory(epic) {
  if (epic.status === 'released' || epic.status === 'completed') return 'released'
  const total = epic.total_children || epic.children?.length || 0
  const merged = epic.merged_children || 0
  if (total > 0 && merged === total) return 'ready_to_release'
  return 'active'
}

/**
 * Sort comparator: ready_to_release first, then active, then released.
 * Within each group, sort by progress percentage descending.
 */
const CATEGORY_ORDER = { ready_to_release: 0, active: 1, released: 2 }

function epicSortProgress(a, b) {
  const catA = CATEGORY_ORDER[epicCategory(a)] ?? 1
  const catB = CATEGORY_ORDER[epicCategory(b)] ?? 1
  if (catA !== catB) return catA - catB
  const pctA = (a.total_children || 0) > 0 ? (a.merged_children || 0) / a.total_children : 0
  const pctB = (b.total_children || 0) > 0 ? (b.merged_children || 0) / b.total_children : 0
  return pctB - pctA
}

function epicSortCreated(a, b) {
  const catA = CATEGORY_ORDER[epicCategory(a)] ?? 1
  const catB = CATEGORY_ORDER[epicCategory(b)] ?? 1
  if (catA !== catB) return catA - catB
  return (b.created_at || '').localeCompare(a.created_at || '')
}

const SORT_OPTIONS = [
  { key: 'progress', label: 'Progress' },
  { key: 'created', label: 'Created' },
]

/**
 * EpicDashboard — top-level container for the Epics tab.
 * Renders filter pills, sort toggle, search box, and EpicCard list.
 */
export function EpicDashboard() {
  const { epics, epicReleasing, releaseEpic } = useHydraFlow()
  const [filter, setFilter] = useState('all')
  const [sort, setSort] = useState('progress')
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    let list = epics || []

    // Filter
    if (filter !== 'all') {
      list = list.filter(e => epicCategory(e) === filter)
    }

    // Search
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      list = list.filter(e =>
        (e.title || '').toLowerCase().includes(q) ||
        String(e.epic_number).includes(q)
      )
    }

    // Sort
    const sortFn = sort === 'created' ? epicSortCreated : epicSortProgress
    return [...list].sort(sortFn)
  }, [epics, filter, sort, search])

  return (
    <div style={styles.container} data-testid="epic-dashboard">
      <div style={styles.toolbar}>
        <div style={styles.filterPills} data-testid="epic-filter-pills">
          {EPIC_FILTERS.map(f => (
            <span
              key={f.key}
              role="button"
              tabIndex={0}
              onClick={() => setFilter(f.key)}
              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setFilter(f.key) } }}
              style={filter === f.key ? pillActiveStyle : pillInactiveStyle}
            >
              {f.label}
            </span>
          ))}
        </div>

        <div style={styles.controls}>
          <div style={styles.sortGroup} data-testid="epic-sort">
            {SORT_OPTIONS.map(s => (
              <span
                key={s.key}
                role="button"
                tabIndex={0}
                onClick={() => setSort(s.key)}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSort(s.key) } }}
                style={sort === s.key ? sortActiveStyle : sortInactiveStyle}
              >
                {s.label}
              </span>
            ))}
          </div>

          <input
            type="text"
            placeholder="Search epics..."
            aria-label="Search epics"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={styles.search}
            data-testid="epic-search"
          />
        </div>
      </div>

      <div style={styles.list}>
        {filtered.length === 0 ? (
          <div style={styles.empty} data-testid="epic-empty">
            {(epics || []).length === 0 ? 'No epics found' : 'No matching epics'}
          </div>
        ) : (
          filtered.map(epic => (
            <EpicCard key={epic.epic_number} epic={epic} onRelease={releaseEpic} releasing={epicReleasing} />
          ))
        )}
      </div>
    </div>
  )
}

// Pre-computed pill styles
const pillBase = {
  fontSize: 11,
  fontWeight: 600,
  padding: '4px 12px',
  borderRadius: 12,
  cursor: 'pointer',
  transition: 'all 0.15s',
  userSelect: 'none',
}

export const pillActiveStyle = {
  ...pillBase,
  background: theme.purple,
  color: theme.white,
}

export const pillInactiveStyle = {
  ...pillBase,
  background: theme.surfaceInset,
  color: theme.textMuted,
}

// Pre-computed sort styles
const sortBase = {
  fontSize: 10,
  fontWeight: 600,
  padding: '3px 8px',
  borderRadius: 8,
  cursor: 'pointer',
  transition: 'all 0.15s',
  userSelect: 'none',
}

const sortActiveStyle = {
  ...sortBase,
  background: theme.accentSubtle,
  color: theme.accent,
}

const sortInactiveStyle = {
  ...sortBase,
  background: 'transparent',
  color: theme.textMuted,
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'hidden',
  },
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    padding: '12px 16px',
    borderBottom: `1px solid ${theme.border}`,
    flexWrap: 'wrap',
  },
  filterPills: {
    display: 'flex',
    gap: 4,
  },
  controls: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  sortGroup: {
    display: 'flex',
    gap: 2,
  },
  search: {
    fontSize: 11,
    padding: '4px 8px',
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    background: theme.surfaceInset,
    color: theme.text,
    outline: 'none',
    width: 160,
  },
  list: {
    flex: 1,
    overflow: 'auto',
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  empty: {
    padding: 24,
    textAlign: 'center',
    fontSize: 13,
    color: theme.textMuted,
  },
}
