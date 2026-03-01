import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { theme } from '../theme'
import { EPIC_STATUSES, CRATE_STATUSES } from '../constants'
import { useHydraFlow } from '../context/HydraFlowContext'

const STATUS_COLORS = {
  active: { color: theme.accent, bg: theme.accentSubtle },
  completed: { color: theme.green, bg: theme.greenSubtle },
  stale: { color: theme.yellow, bg: theme.yellowSubtle },
  blocked: { color: theme.red, bg: theme.redSubtle },
}

const CRATE_STATE_COLORS = {
  open: { color: theme.accent, bg: theme.accentSubtle },
  closed: { color: theme.green, bg: theme.greenSubtle },
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

const crateBadgeStyles = Object.fromEntries(
  Object.entries(CRATE_STATE_COLORS).map(([key, { color, bg }]) => [
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

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString()
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

function CrateRow({ crate }) {
  const [expanded, setExpanded] = useState(false)
  const total = crate.total_issues || 0
  const progress = crate.progress || 0
  const badge = crateBadgeStyles[crate.state] || crateBadgeStyles.open

  return (
    <div style={styles.crateCard}>
      <div
        style={styles.crateCardHeader}
        onClick={() => setExpanded(prev => !prev)}
        role="button"
        tabIndex={0}
      >
        <span style={styles.chevron}>{expanded ? '\u25BE' : '\u25B8'}</span>
        <span style={styles.crateTitle}>{crate.title}</span>
        {crate.due_on && <span style={styles.crateDue}>Due {formatDate(crate.due_on)}</span>}
        <span style={badge}>{crate.state}</span>
        <span style={styles.crateCount}>{total} {total === 1 ? 'issue' : 'issues'}</span>
      </div>
      <div style={styles.crateCardBody}>
        <div style={styles.barTrack}>
          {progress > 0 && (
            <div style={{ ...styles.barGreen, width: `${progress}%` }} />
          )}
        </div>
        <div style={styles.progressRow}>
          <span style={styles.progressText}>
            {crate.closed_issues}/{total} closed · {progress}%
          </span>
        </div>
      </div>
      {expanded && crate.description && (
        <div style={styles.crateDescription}>{crate.description}</div>
      )}
    </div>
  )
}

export function WorkLogPanel() {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [crateFilter, setCrateFilter] = useState('all')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [epics, setEpics] = useState([])
  const [crates, setCrates] = useState([])
  const [newCrateName, setNewCrateName] = useState('')
  const [creating, setCreating] = useState(false)
  const cachedEpics = useRef(null)
  const cachedCrates = useRef(null)
  const refreshTimer = useRef(null)

  const fetchData = useCallback((opts = {}) => {
    const { background = false } = opts
    if (!background) {
      if (cachedEpics.current) setEpics(cachedEpics.current)
      if (cachedCrates.current) setCrates(cachedCrates.current)
      setLoading(true)
      setError('')
    }

    return Promise.all([
      fetch('/api/epics')
        .then(async (res) => {
          if (!res.ok) throw new Error(`status ${res.status}`)
          return await res.json()
        })
        .then(data => {
          const list = Array.isArray(data) ? data : []
          cachedEpics.current = list
          setEpics(list)
        }),
      fetch('/api/crates')
        .then(async (res) => {
          if (!res.ok) throw new Error(`status ${res.status}`)
          return await res.json()
        })
        .then(data => {
          const list = Array.isArray(data) ? data : []
          cachedCrates.current = list
          setCrates(list)
        }),
    ])
      .catch(() => {
        if (!background) setError('Could not load work log data')
      })
      .finally(() => {
        if (!background) setLoading(false)
      })
  }, [])

  useEffect(() => {
    fetchData()
    refreshTimer.current = setInterval(() => {
      fetchData({ background: true })
    }, 30_000)
    return () => clearInterval(refreshTimer.current)
  }, [fetchData])

  const filteredEpics = useMemo(() => {
    const q = search.trim().toLowerCase()
    return epics.filter(epic => {
      if (statusFilter !== 'all' && epic.status !== statusFilter) return false
      if (!q) return true
      const text = `#${epic.epic_number} ${(epic.title || '').toLowerCase()}`
      return text.includes(q)
    })
  }, [epics, statusFilter, search])

  const filteredCrates = useMemo(() => {
    return crates.filter(crate => {
      if (crateFilter !== 'all' && crate.state !== crateFilter) return false
      if (!search.trim()) return true
      return crate.title.toLowerCase().includes(search.trim().toLowerCase())
    })
  }, [crates, crateFilter, search])

  const statusCounts = useMemo(() => {
    const counts = { active: 0, completed: 0, stale: 0, blocked: 0 }
    for (const epic of epics) {
      if (counts[epic.status] !== undefined) counts[epic.status]++
    }
    return counts
  }, [epics])

  const handleCreateCrate = useCallback(async () => {
    const title = newCrateName.trim()
    if (!title) return
    setCreating(true)
    try {
      const res = await fetch('/api/crates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      })
      if (res.ok) {
        setNewCrateName('')
        fetchData()
      }
    } catch { /* ignore */ }
    setCreating(false)
  }, [newCrateName, fetchData])

  return (
    <div style={styles.container}>
      <div style={styles.controls}>
        <div style={styles.summaryCards}>
          <div style={styles.summaryCard}>
            <div style={styles.summaryValue}>{crates.length}</div>
            <div style={styles.summaryLabel}>Crates</div>
          </div>
          <div style={styles.summaryCard}>
            <div style={styles.summaryValue}>{epics.length}</div>
            <div style={styles.summaryLabel}>Epics</div>
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
            placeholder="Search crates, epics"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={styles.searchInput}
          />
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={styles.select}>
            <option value="all">All epic statuses</option>
            {EPIC_STATUSES.map(status => (
              <option key={status} value={status}>{status}</option>
            ))}
          </select>
          <select value={crateFilter} onChange={e => setCrateFilter(e.target.value)} style={styles.select} data-testid="crate-filter">
            <option value="all">All crates</option>
            {CRATE_STATUSES.map(status => (
              <option key={status} value={status}>{status}</option>
            ))}
          </select>
        </div>
      </div>

      {loading && <div style={styles.info}>Loading work log...</div>}
      {error && <div style={styles.error}>{error}</div>}

      {/* Crates section */}
      <div style={styles.sectionHeader}>
        <span style={styles.sectionTitle}>Crates</span>
        <div style={styles.createRow}>
          <input
            type="text"
            placeholder="New crate name..."
            value={newCrateName}
            onChange={e => setNewCrateName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleCreateCrate()}
            style={styles.createInput}
            data-testid="new-crate-input"
          />
          <button
            type="button"
            onClick={handleCreateCrate}
            disabled={creating || !newCrateName.trim()}
            style={!newCrateName.trim() ? styles.createButtonDisabled : styles.createButton}
            data-testid="create-crate-btn"
          >
            {creating ? 'Creating...' : 'Create'}
          </button>
        </div>
      </div>

      <div style={styles.list} data-testid="crates-list">
        {filteredCrates.map(crate => (
          <CrateRow key={crate.number} crate={crate} />
        ))}
        {!loading && filteredCrates.length === 0 && (
          <div style={styles.info}>No crates yet. Create one to group your work.</div>
        )}
      </div>

      {/* Epics section */}
      <div style={styles.sectionHeader}>
        <span style={styles.sectionTitle}>Epics</span>
      </div>

      <div style={styles.list} data-testid="epics-list">
        {filteredEpics.map(epic => (
          <EpicRow key={epic.epic_number} epic={epic} />
        ))}
        {!loading && filteredEpics.length === 0 && (
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
    overflow: 'auto',
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
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    marginTop: 4,
  },
  sectionTitle: {
    fontSize: 13,
    fontWeight: 700,
    color: theme.textBright,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  createRow: {
    display: 'flex',
    gap: 8,
    alignItems: 'center',
  },
  createInput: {
    width: 200,
    border: `1px solid ${theme.border}`,
    background: theme.surfaceInset,
    color: theme.text,
    borderRadius: 6,
    padding: '4px 8px',
    fontSize: 12,
  },
  createButton: {
    border: `1px solid ${theme.accent}`,
    background: theme.accentSubtle,
    color: theme.accent,
    borderRadius: 6,
    padding: '4px 12px',
    fontSize: 11,
    fontWeight: 600,
    cursor: 'pointer',
  },
  createButtonDisabled: {
    border: `1px solid ${theme.border}`,
    background: theme.surfaceInset,
    color: theme.textMuted,
    borderRadius: 6,
    padding: '4px 12px',
    fontSize: 11,
    fontWeight: 600,
    cursor: 'default',
    opacity: 0.5,
  },
  list: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    overflowY: 'auto',
    minHeight: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 0,
  },
  crateCard: {
    borderBottom: `1px solid ${theme.border}`,
    overflow: 'hidden',
  },
  crateCardHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '10px 12px',
    cursor: 'pointer',
    transition: 'background 0.15s',
  },
  crateTitle: {
    fontSize: 12,
    fontWeight: 700,
    color: theme.text,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    flex: 1,
  },
  crateDue: {
    fontSize: 10,
    color: theme.textMuted,
    flexShrink: 0,
  },
  crateCount: {
    fontSize: 11,
    color: theme.textMuted,
    flexShrink: 0,
  },
  crateCardBody: {
    padding: '0 12px 10px 30px',
  },
  crateDescription: {
    padding: '0 12px 10px 30px',
    fontSize: 11,
    color: theme.textMuted,
    borderTop: `1px dashed ${theme.border}`,
    paddingTop: 8,
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
