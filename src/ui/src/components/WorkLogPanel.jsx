import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { theme } from '../theme'
import { CRATE_STATUSES } from '../constants'

const CRATE_STATE_COLORS = {
  open: { color: theme.accent, bg: theme.accentSubtle },
  closed: { color: theme.green, bg: theme.greenSubtle },
}

const badgeBase = {
  display: 'inline-flex',
  alignItems: 'center',
  borderRadius: 999,
  fontSize: 10,
  fontWeight: 700,
  padding: '2px 8px',
  textTransform: 'uppercase',
  letterSpacing: 0.4,
}

const crateBadgeStyles = Object.fromEntries(
  Object.entries(CRATE_STATE_COLORS).map(([key, { color, bg }]) => [
    key,
    { ...badgeBase, color, background: bg || theme.surface },
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

function CrateRow({ crate }) {
  const [expanded, setExpanded] = useState(false)
  const total = crate.total_issues || 0
  const progress = crate.progress || 0
  const badge = crateBadgeStyles[crate.state] || crateBadgeStyles.open
  const toggle = () => setExpanded(prev => !prev)

  return (
    <div style={styles.crateCard}>
      <div
        style={styles.crateCardHeader}
        onClick={toggle}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle() } }}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        aria-label={`Toggle crate ${crate.title || ''}`}
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
  const [crateFilter, setCrateFilter] = useState('all')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [crates, setCrates] = useState([])
  const [newCrateName, setNewCrateName] = useState('')
  const [creating, setCreating] = useState(false)
  const cachedCrates = useRef(null)
  const refreshTimer = useRef(null)

  const abortRef = useRef(null)

  const fetchData = useCallback((opts = {}) => {
    const { background = false, signal } = opts
    if (!background) {
      if (cachedCrates.current) setCrates(cachedCrates.current)
      setLoading(true)
      setError('')
    }

    return fetch('/api/crates', { signal })
      .then(async (res) => {
        if (!res.ok) throw new Error(`status ${res.status}`)
        return await res.json()
      })
      .then(data => {
        const list = Array.isArray(data) ? data : []
        cachedCrates.current = list
        setCrates(list)
      })
      .catch((err) => {
        if (err?.name === 'AbortError') return
        if (!background) setError('Could not load delivery queue data')
      })
      .finally(() => {
        if (!background) setLoading(false)
      })
  }, [])

  useEffect(() => {
    const ac = new AbortController()
    abortRef.current = ac
    fetchData({ signal: ac.signal })
    refreshTimer.current = setInterval(() => {
      fetchData({ background: true })
    }, 30_000)
    return () => { ac.abort(); clearInterval(refreshTimer.current) }
  }, [fetchData])

  const filteredCrates = useMemo(() => {
    return crates.filter(crate => {
      if (crateFilter !== 'all' && crate.state !== crateFilter) return false
      if (!search.trim()) return true
      return (crate.title || '').toLowerCase().includes(search.trim().toLowerCase())
    })
  }, [crates, crateFilter, search])

  const handleCreateCrate = useCallback(async () => {
    const title = newCrateName.trim()
    if (!title) return
    setCreating(true)
    setError('')
    try {
      const res = await fetch('/api/crates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      })
      if (res.ok) {
        setNewCrateName('')
        fetchData()
      } else {
        setError('Failed to create crate')
      }
    } catch {
      setError('Failed to create crate')
    }
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
        </div>

        <div style={styles.filterRow}>
          <input
            type="text"
            placeholder="Search crates"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={styles.searchInput}
          />
          <select value={crateFilter} onChange={e => setCrateFilter(e.target.value)} style={styles.select} data-testid="crate-filter">
            <option value="all">All crates</option>
            {CRATE_STATUSES.map(status => (
              <option key={status} value={status}>{status}</option>
            ))}
          </select>
        </div>
      </div>

      {loading && <div style={styles.info}>Loading delivery queue...</div>}
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
