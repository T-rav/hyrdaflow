import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { theme } from '../theme'

const OUTCOME_TYPES = [
  'all', 'merged', 'already_satisfied', 'hitl_closed',
  'hitl_skipped', 'failed', 'manual_close',
]

const OUTCOME_COLORS = {
  merged: { color: theme.green, bg: theme.greenSubtle },
  already_satisfied: { color: theme.accent, bg: theme.accentSubtle },
  hitl_closed: { color: theme.orange, bg: theme.orangeSubtle },
  hitl_skipped: { color: theme.yellow, bg: theme.yellowSubtle },
  failed: { color: theme.red, bg: theme.redSubtle },
  manual_close: { color: theme.textMuted, bg: theme.surfaceInset },
}

const outcomeBadgeBase = {
  display: 'inline-flex',
  alignItems: 'center',
  borderRadius: 999,
  fontSize: 9,
  fontWeight: 700,
  padding: '1px 6px',
  textTransform: 'uppercase',
  letterSpacing: 0.3,
  whiteSpace: 'nowrap',
}

const outcomeBadgeStyles = Object.fromEntries(
  Object.entries(OUTCOME_COLORS).map(([key, { color, bg }]) => [
    key,
    { ...outcomeBadgeBase, color, background: bg || theme.surface },
  ])
)

function formatTs(ts) {
  if (!ts) return '-'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return '-'
  return d.toLocaleString()
}

export function OutcomesPanel() {
  const [outcomeFilter, setOutcomeFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [groupByEpic, setGroupByEpic] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [items, setItems] = useState([])
  const [collapsedEpics, setCollapsedEpics] = useState(new Set())
  const cachedItems = useRef(null)
  const refreshTimer = useRef(null)

  const fetchOutcomes = useCallback((opts = {}) => {
    const { background = false } = opts
    if (!background) {
      if (cachedItems.current) setItems(cachedItems.current)
      setLoading(true)
      setError('')
    }

    return fetch('/api/issues/outcomes')
      .then(async (res) => {
        if (!res.ok) throw new Error(`status ${res.status}`)
        return await res.json()
      })
      .then(data => {
        const entries = Object.entries(data || {}).map(([issueNum, entry]) => ({
          issue_number: Number(issueNum),
          ...entry,
        }))
        cachedItems.current = entries
        setItems(entries)
      })
      .catch(() => {
        if (!background) setError('Could not load outcomes')
      })
      .finally(() => {
        if (!background) setLoading(false)
      })
  }, [])

  useEffect(() => {
    fetchOutcomes()
    refreshTimer.current = setInterval(() => {
      fetchOutcomes({ background: true })
    }, 30_000)
    return () => clearInterval(refreshTimer.current)
  }, [fetchOutcomes])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return items.filter(item => {
      if (outcomeFilter !== 'all' && (item.outcome || '') !== outcomeFilter) return false
      if (!q) return true
      const text = `#${item.issue_number} ${(item.title || '').toLowerCase()}`
      return text.includes(q)
    })
  }, [items, outcomeFilter, search])

  const grouped = useMemo(() => {
    if (!groupByEpic) return null
    const groups = {}
    for (const item of filtered) {
      const label = item.epic || 'Ungrouped'
      if (!groups[label]) groups[label] = []
      groups[label].push(item)
    }
    return groups
  }, [filtered, groupByEpic])

  const summaryCounts = useMemo(() => {
    const counts = {}
    for (const item of filtered) {
      const t = item.outcome || 'unknown'
      counts[t] = (counts[t] || 0) + 1
    }
    return counts
  }, [filtered])

  const toggleEpicCollapse = (epicLabel) => {
    setCollapsedEpics(prev => {
      const next = new Set(prev)
      if (next.has(epicLabel)) next.delete(epicLabel)
      else next.add(epicLabel)
      return next
    })
  }

  function renderRow(item) {
    const outcomeType = item.outcome || 'unknown'
    const badge = outcomeBadgeStyles[outcomeType] || outcomeBadgeStyles.manual_close
    return (
      <div key={item.issue_number} style={styles.row}>
        <span style={styles.issueCell}>#{item.issue_number}</span>
        <span style={styles.titleCell}>{item.title || `Issue #${item.issue_number}`}</span>
        <span style={badge}>{outcomeType.replace(/_/g, ' ')}</span>
        <span style={styles.metaCell}>{item.phase || '-'}</span>
        <span style={styles.reasonCell}>{item.reason || '-'}</span>
        <span style={styles.metaCell}>{item.pr_number ? `#${item.pr_number}` : '-'}</span>
        <span style={styles.metaCell}>{formatTs(item.closed_at)}</span>
      </div>
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.controls}>
        <div style={styles.filterRow}>
          <input
            type="text"
            placeholder="Search issue #, title"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={styles.searchInput}
          />
          <select value={outcomeFilter} onChange={e => setOutcomeFilter(e.target.value)} style={styles.select}>
            {OUTCOME_TYPES.map(opt => (
              <option key={opt} value={opt}>{opt === 'all' ? 'All outcomes' : opt.replace(/_/g, ' ')}</option>
            ))}
          </select>
          <label style={styles.checkboxLabel}>
            <input type="checkbox" checked={groupByEpic} onChange={e => setGroupByEpic(e.target.checked)} />
            Group by epic
          </label>
        </div>
      </div>

      <div style={styles.summaryRow}>
        <span>{filtered.length} outcomes</span>
        {Object.entries(summaryCounts)
          .sort((a, b) => b[1] - a[1])
          .map(([type, count]) => (
            <span key={type} style={styles.summaryPill}>
              <span style={outcomeBadgeStyles[type] || outcomeBadgeStyles.manual_close}>
                {type.replace(/_/g, ' ')}
              </span>
              {' '}{count}
            </span>
          ))}
      </div>

      {loading && <div style={styles.info}>Loading outcomes...</div>}
      {error && <div style={styles.error}>{error}</div>}

      <div style={styles.table}>
        <div style={styles.headerRow}>
          <span style={styles.issueCell}>Issue</span>
          <span style={styles.titleCell}>Title</span>
          <span style={styles.headerMeta}>Outcome</span>
          <span style={styles.metaCell}>Phase</span>
          <span style={styles.reasonCell}>Reason</span>
          <span style={styles.metaCell}>PR</span>
          <span style={styles.metaCell}>Closed</span>
        </div>

        {grouped ? (
          Object.entries(grouped)
            .sort(([a], [b]) => (a === 'Ungrouped' ? 1 : b === 'Ungrouped' ? -1 : a.localeCompare(b)))
            .map(([epicLabel, epicItems]) => {
              const isCollapsed = collapsedEpics.has(epicLabel)
              return (
                <div key={epicLabel}>
                  <button
                    type="button"
                    onClick={() => toggleEpicCollapse(epicLabel)}
                    style={styles.epicHeader}
                  >
                    <span>{isCollapsed ? '\u25B8' : '\u25BE'}</span>
                    <span style={styles.epicTitle}>{epicLabel}</span>
                    <span style={styles.epicCount}>{epicItems.length} outcome{epicItems.length !== 1 ? 's' : ''}</span>
                  </button>
                  {!isCollapsed && epicItems.map(item => renderRow(item))}
                </div>
              )
            })
        ) : (
          filtered.map(item => renderRow(item))
        )}

        {!loading && filtered.length === 0 && (
          <div style={styles.info}>No outcomes match this filter.</div>
        )}
      </div>
    </div>
  )
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'hidden',
    padding: 16,
    gap: 10,
  },
  controls: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    padding: 10,
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  filterRow: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap',
  },
  searchInput: {
    minWidth: 260,
    flex: 1,
    border: `1px solid ${theme.border}`,
    background: theme.surfaceInset,
    color: theme.text,
    borderRadius: 6,
    padding: '6px 8px',
    fontSize: 12,
  },
  select: {
    minWidth: 140,
    border: `1px solid ${theme.border}`,
    background: theme.surfaceInset,
    color: theme.text,
    borderRadius: 6,
    padding: '6px 8px',
    fontSize: 12,
  },
  checkboxLabel: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    fontSize: 12,
    color: theme.text,
  },
  summaryRow: {
    display: 'flex',
    gap: 16,
    fontSize: 12,
    color: theme.textMuted,
    padding: '0 2px',
    alignItems: 'center',
  },
  summaryPill: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
  },
  table: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    overflowY: 'auto',
    flex: 1,
    minHeight: 0,
  },
  headerRow: {
    display: 'grid',
    gridTemplateColumns: '60px minmax(200px, 1.5fr) 110px 90px minmax(140px, 1fr) 60px 150px',
    gap: 8,
    alignItems: 'center',
    padding: '8px 10px',
    fontSize: 11,
    fontWeight: 600,
    color: theme.textMuted,
    textTransform: 'uppercase',
    letterSpacing: '0.3px',
    borderBottom: `1px solid ${theme.border}`,
  },
  headerMeta: {
    color: theme.textMuted,
    whiteSpace: 'nowrap',
  },
  row: {
    display: 'grid',
    gridTemplateColumns: '60px minmax(200px, 1.5fr) 110px 90px minmax(140px, 1fr) 60px 150px',
    gap: 8,
    alignItems: 'center',
    padding: '8px 10px',
    fontSize: 12,
    borderBottom: `1px solid ${theme.border}`,
  },
  issueCell: {
    fontWeight: 700,
    color: theme.accent,
    flexShrink: 0,
  },
  titleCell: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    color: theme.text,
  },
  metaCell: {
    color: theme.textMuted,
    whiteSpace: 'nowrap',
  },
  reasonCell: {
    color: theme.textMuted,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  epicHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    width: '100%',
    padding: '8px 10px',
    border: 'none',
    borderBottom: `1px solid ${theme.border}`,
    borderLeft: `3px solid ${theme.accent}`,
    background: theme.surfaceInset,
    cursor: 'pointer',
    fontSize: 12,
    color: theme.text,
    textAlign: 'left',
  },
  epicTitle: {
    fontWeight: 700,
  },
  epicCount: {
    color: theme.textMuted,
    fontSize: 11,
  },
  info: {
    padding: 12,
    color: theme.textMuted,
    fontSize: 12,
  },
  error: {
    padding: 12,
    borderRadius: 6,
    border: `1px solid ${theme.red}`,
    color: theme.red,
    fontSize: 12,
    background: theme.redSubtle || theme.surface,
  },
}
