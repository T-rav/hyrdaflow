import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { theme } from '../theme'
import { EPIC_STATUSES } from '../constants'
import { useHydraFlow } from '../context/HydraFlowContext'

const STATUS_COLORS = {
  active: { color: theme.accent, bg: theme.accentSubtle },
  completed: { color: theme.green, bg: theme.greenSubtle },
  stale: { color: theme.yellow, bg: theme.yellowSubtle },
  blocked: { color: theme.red, bg: theme.redSubtle },
}

const statusBadgeBase = {
  display: 'inline-flex',
  alignItems: 'center',
  borderRadius: 999,
  fontSize: 10,
  fontWeight: 700,
  padding: '2px 8px',
  textTransform: 'uppercase',
  letterSpacing: 0.4,
}

const statusBadgeStyles = Object.fromEntries(
  Object.entries(STATUS_COLORS).map(([key, { color, bg }]) => [
    key,
    { ...statusBadgeBase, color, background: bg || theme.surface },
  ])
)

function formatTs(ts) {
  if (!ts) return '-'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return '-'
  return d.toLocaleString()
}

function EpicChildRow({ child }) {
  const dotColor = child.is_completed ? theme.green : child.is_failed ? theme.red : theme.textMuted
  return (
    <div style={styles.childRow}>
      <span style={{ ...styles.childDot, background: dotColor }} />
      {child.url ? (
        <a href={child.url} target="_blank" rel="noopener noreferrer" style={styles.childLink}>
          #{child.issue_number}
        </a>
      ) : (
        <span style={styles.childLink}>#{child.issue_number}</span>
      )}
      <span style={styles.childTitle}>{child.title || `Issue #${child.issue_number}`}</span>
      {child.stage && <span style={styles.childStage}>{child.stage}</span>}
      {child.is_completed && <span style={styles.childBadgeDone}>done</span>}
      {child.is_failed && <span style={styles.childBadgeFailed}>failed</span>}
    </div>
  )
}

function EpicRow({ epic }) {
  const { config } = useHydraFlow()
  const [expanded, setExpanded] = useState(false)
  const [children, setChildren] = useState(null)
  const [loading, setLoading] = useState(false)

  const pct = epic.percent_complete || 0
  const badge = statusBadgeStyles[epic.status] || statusBadgeStyles.active
  const repo = config?.repo || ''
  const epicUrl = repo ? `https://github.com/${repo}/issues/${epic.epic_number}` : ''

  const handleToggle = useCallback(async () => {
    if (!expanded && children === null) {
      setLoading(true)
      try {
        const res = await fetch(`/api/epics/${epic.epic_number}`)
        if (res.ok) {
          const detail = await res.json()
          setChildren(detail.children || [])
        }
      } catch { /* ignore */ }
      setLoading(false)
    }
    setExpanded(prev => !prev)
  }, [expanded, children, epic.epic_number])

  return (
    <div style={styles.epicCard}>
      <div style={styles.epicCardHeader} onClick={handleToggle} role="button" tabIndex={0}>
        <span style={styles.chevron}>{expanded ? '\u25BE' : '\u25B8'}</span>
        {epicUrl ? (
          <a
            href={epicUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={styles.epicLink}
            onClick={e => e.stopPropagation()}
          >
            #{epic.epic_number}
          </a>
        ) : (
          <span style={styles.epicLabel}>#{epic.epic_number}</span>
        )}
        <span style={styles.epicTitle}>{epic.title}</span>
        {epic.auto_decomposed && <span style={styles.autoBadge}>auto</span>}
        <span style={badge}>{epic.status}</span>
      </div>

      <div style={styles.epicCardBody}>
        <div style={styles.barTrack}>
          {epic.completed > 0 && (
            <div style={{ ...styles.barGreen, width: `${(epic.completed / (epic.total_children || 1)) * 100}%` }} />
          )}
          {epic.failed > 0 && (
            <div style={{ ...styles.barRed, width: `${(epic.failed / (epic.total_children || 1)) * 100}%` }} />
          )}
        </div>
        <div style={styles.progressRow}>
          <span style={styles.progressText}>
            {epic.completed}/{epic.total_children} done
            {epic.failed > 0 && ` \u00B7 ${epic.failed} failed`}
            {epic.in_progress > 0 && ` \u00B7 ${epic.in_progress} in progress`}
            {` \u00B7 ${Math.round(pct)}%`}
          </span>
          {epic.last_activity && (
            <span style={styles.lastActivity}>Last: {formatTs(epic.last_activity)}</span>
          )}
        </div>
      </div>

      {expanded && (
        <div style={styles.childList}>
          {loading && <span style={styles.childLoading}>Loading...</span>}
          {children && children.length > 0 && children.map(child => (
            <EpicChildRow key={child.issue_number} child={child} />
          ))}
          {children && children.length === 0 && !loading && (
            <span style={styles.childLoading}>No child issues found</span>
          )}
        </div>
      )}
    </div>
  )
}

export function EpicsPanel() {
  const [statusFilter, setStatusFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [epics, setEpics] = useState([])
  const cachedEpics = useRef(null)
  const refreshTimer = useRef(null)

  const fetchEpics = useCallback((opts = {}) => {
    const { background = false } = opts
    if (!background) {
      if (cachedEpics.current) setEpics(cachedEpics.current)
      setLoading(true)
      setError('')
    }

    return fetch('/api/epics')
      .then(async (res) => {
        if (!res.ok) throw new Error(`status ${res.status}`)
        return await res.json()
      })
      .then(data => {
        const list = Array.isArray(data) ? data : []
        cachedEpics.current = list
        setEpics(list)
      })
      .catch(() => {
        if (!background) setError('Could not load epics')
      })
      .finally(() => {
        if (!background) setLoading(false)
      })
  }, [])

  useEffect(() => {
    fetchEpics()
    refreshTimer.current = setInterval(() => {
      fetchEpics({ background: true })
    }, 30_000)
    return () => clearInterval(refreshTimer.current)
  }, [fetchEpics])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return epics.filter(epic => {
      if (statusFilter !== 'all' && epic.status !== statusFilter) return false
      if (!q) return true
      const text = `#${epic.epic_number} ${(epic.title || '').toLowerCase()}`
      return text.includes(q)
    })
  }, [epics, statusFilter, search])

  const statusCounts = useMemo(() => {
    const counts = { active: 0, completed: 0, stale: 0, blocked: 0 }
    for (const epic of epics) {
      if (counts[epic.status] !== undefined) counts[epic.status]++
    }
    return counts
  }, [epics])

  return (
    <div style={styles.container}>
      <div style={styles.controls}>
        <div style={styles.summaryCards}>
          <div style={styles.summaryCard}>
            <div style={styles.summaryValue}>{epics.length}</div>
            <div style={styles.summaryLabel}>Total</div>
          </div>
          {EPIC_STATUSES.map(status => (
            <div key={status} style={styles.summaryCard}>
              <div style={{ ...styles.summaryValue, color: STATUS_COLORS[status]?.color || theme.textBright }}>
                {statusCounts[status] || 0}
              </div>
              <div style={styles.summaryLabel}>{status}</div>
            </div>
          ))}
        </div>

        <div style={styles.filterRow}>
          <input
            type="text"
            placeholder="Search epic #, title"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={styles.searchInput}
          />
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={styles.select}>
            <option value="all">All statuses</option>
            {EPIC_STATUSES.map(status => (
              <option key={status} value={status}>{status}</option>
            ))}
          </select>
        </div>
      </div>

      {loading && <div style={styles.info}>Loading epics...</div>}
      {error && <div style={styles.error}>{error}</div>}

      <div style={styles.list}>
        {filtered.map(epic => (
          <EpicRow key={epic.epic_number} epic={epic} />
        ))}

        {!loading && filtered.length === 0 && (
          <div style={styles.info}>No epics match this filter.</div>
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
  summaryCards: {
    display: 'flex',
    gap: 12,
    flexWrap: 'wrap',
  },
  summaryCard: {
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: '8px 16px',
    textAlign: 'center',
    minWidth: 80,
  },
  summaryValue: {
    fontSize: 18,
    fontWeight: 700,
    color: theme.textBright,
  },
  summaryLabel: {
    fontSize: 11,
    color: theme.textMuted,
    textTransform: 'capitalize',
    marginTop: 2,
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
  list: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    overflowY: 'auto',
    flex: 1,
    minHeight: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 0,
  },
  epicCard: {
    borderBottom: `1px solid ${theme.border}`,
    overflow: 'hidden',
  },
  epicCardHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '10px 12px',
    cursor: 'pointer',
    transition: 'background 0.15s',
  },
  epicCardBody: {
    padding: '0 12px 10px 30px',
  },
  chevron: {
    fontSize: 10,
    color: theme.textMuted,
    flexShrink: 0,
    width: 10,
  },
  epicLink: {
    fontSize: 12,
    fontWeight: 700,
    color: theme.purple,
    flexShrink: 0,
    textDecoration: 'none',
    cursor: 'pointer',
  },
  epicLabel: {
    fontSize: 12,
    fontWeight: 700,
    color: theme.purple,
    flexShrink: 0,
  },
  epicTitle: {
    fontSize: 12,
    color: theme.text,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    flex: 1,
  },
  autoBadge: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.accent,
    background: theme.accentSubtle,
    borderRadius: 4,
    padding: '1px 4px',
    flexShrink: 0,
  },
  barTrack: {
    display: 'flex',
    height: 6,
    background: theme.surfaceInset,
    borderRadius: 3,
    overflow: 'hidden',
    marginBottom: 4,
  },
  barGreen: {
    height: '100%',
    background: theme.green,
    transition: 'width 0.3s ease',
  },
  barRed: {
    height: '100%',
    background: theme.red,
    transition: 'width 0.3s ease',
  },
  progressRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  progressText: {
    fontSize: 11,
    color: theme.textMuted,
  },
  lastActivity: {
    fontSize: 10,
    color: theme.textMuted,
  },
  childList: {
    padding: '0 12px 10px 30px',
    borderTop: `1px dashed ${theme.border}`,
    paddingTop: 8,
  },
  childRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '3px 0',
  },
  childDot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    flexShrink: 0,
  },
  childLink: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.accent,
    flexShrink: 0,
    textDecoration: 'none',
  },
  childTitle: {
    fontSize: 11,
    color: theme.text,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    flex: 1,
  },
  childStage: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.textMuted,
    background: theme.surfaceInset,
    borderRadius: 4,
    padding: '1px 4px',
    textTransform: 'uppercase',
    flexShrink: 0,
  },
  childBadgeDone: {
    fontSize: 9,
    fontWeight: 700,
    color: theme.green,
    background: theme.greenSubtle,
    borderRadius: 4,
    padding: '1px 4px',
    textTransform: 'uppercase',
    flexShrink: 0,
  },
  childBadgeFailed: {
    fontSize: 9,
    fontWeight: 700,
    color: theme.red,
    background: theme.redSubtle,
    borderRadius: 4,
    padding: '1px 4px',
    textTransform: 'uppercase',
    flexShrink: 0,
  },
  childLoading: {
    fontSize: 11,
    color: theme.textMuted,
    padding: 4,
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
