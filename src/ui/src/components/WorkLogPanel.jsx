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

const activeBadge = { ...badgeBase, color: theme.green, background: theme.greenSubtle }

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString()
}

function CrateRow({ crate, isActive, onActivate }) {
  const [expanded, setExpanded] = useState(false)
  const total = crate.total_issues || 0
  const progress = crate.progress || 0
  const badge = crateBadgeStyles[crate.state] || crateBadgeStyles.open
  const toggle = () => setExpanded(prev => !prev)

  const cardStyle = isActive
    ? { ...styles.crateCard, borderLeft: `3px solid ${theme.accent}` }
    : styles.crateCard

  return (
    <div style={cardStyle}>
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
        {isActive && <span style={activeBadge}>ACTIVE</span>}
        {crate.due_on && <span style={styles.crateDue}>Due {formatDate(crate.due_on)}</span>}
        <span style={badge}>{crate.state}</span>
        <span style={styles.crateCount}>{total} {total === 1 ? 'issue' : 'issues'}</span>
        {!isActive && crate.state === 'open' && (
          <button
            type="button"
            onClick={e => { e.stopPropagation(); onActivate(crate.number) }}
            style={styles.activateButton}
            data-testid={`activate-crate-${crate.number}`}
          >
            Activate
          </button>
        )}
      </div>
      <div style={styles.crateCardBody}>
        <div style={styles.barTrack}>
          {progress > 0 && (
            <div style={{ ...styles.barGreen, width: `${Math.min(100, progress)}%` }} />
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

function ActiveCrateBanner({ activeCrate, onAdvance }) {
  if (!activeCrate || activeCrate.crate_number == null) return null
  const total = activeCrate.total_issues || 0
  const progress = activeCrate.progress || 0

  return (
    <div style={styles.banner} data-testid="active-crate-banner">
      <div style={styles.bannerHeader}>
        <span style={styles.bannerLabel}>Active Crate</span>
        <span style={styles.bannerTitle}>{activeCrate.title || `Crate #${activeCrate.crate_number}`}</span>
        <button
          type="button"
          onClick={onAdvance}
          style={styles.advanceButton}
          data-testid="advance-crate-btn"
        >
          Next
        </button>
      </div>
      <div style={styles.barTrack}>
        {progress > 0 && (
          <div style={{ ...styles.barGreen, width: `${progress}%` }} />
        )}
      </div>
      <div style={styles.bannerStats}>
        {activeCrate.closed_issues}/{total} closed · {progress}%
      </div>
    </div>
  )
}

export function WorkLogPanel() {
  const [search, setSearch] = useState('')
  const [crateFilter, setCrateFilter] = useState('all')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [crates, setCrates] = useState([])
  const [activeCrate, setActiveCrate] = useState(null)
  const [newCrateName, setNewCrateName] = useState('')
  const [creating, setCreating] = useState(false)
  const cachedCrates = useRef(null)
  const refreshTimer = useRef(null)

  const abortRef = useRef(null)

  const fetchActiveCrate = useCallback(async (signal) => {
    try {
      const res = await fetch('/api/crates/active', { signal })
      if (res.ok) {
        const data = await res.json()
        setActiveCrate(data)
      }
    } catch (err) {
      if (err?.name !== 'AbortError') {
        // Silently ignore — banner just won't show
      }
    }
  }, [])

  const fetchData = useCallback((opts = {}) => {
    const { background = false, signal } = opts
    if (!background) {
      if (cachedCrates.current) setCrates(cachedCrates.current)
      setLoading(true)
      setError('')
    }

    const cratesPromise = fetch('/api/crates', { signal })
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

    fetchActiveCrate(signal)
    return cratesPromise
  }, [fetchActiveCrate])

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

  const handleActivate = useCallback(async (crateNumber) => {
    try {
      const res = await fetch('/api/crates/active', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ crate_number: crateNumber }),
      })
      if (res.ok) fetchData()
    } catch {
      setError('Failed to activate crate')
    }
  }, [fetchData])

  const handleAdvance = useCallback(async () => {
    try {
      const res = await fetch('/api/crates/advance', { method: 'POST' })
      if (res.ok) fetchData()
      else setError('Failed to advance crate')
    } catch {
      setError('Failed to advance crate')
    }
  }, [fetchData])

  const handleToggleAutoCrate = useCallback(async () => {
    const newValue = !(activeCrate?.auto_crate)
    try {
      const res = await fetch('/api/control/config', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto_crate: newValue }),
      })
      if (res.ok) {
        setActiveCrate(prev => prev ? { ...prev, auto_crate: newValue } : prev)
      }
    } catch {
      setError('Failed to toggle auto-crate')
    }
  }, [activeCrate])

  const activeCrateNumber = activeCrate?.crate_number
  const noActiveCrate = activeCrateNumber == null && !activeCrate?.auto_crate

  return (
    <div style={styles.container}>
      <ActiveCrateBanner activeCrate={activeCrate} onAdvance={handleAdvance} />

      {noActiveCrate && (
        <div style={styles.noCrateBanner} data-testid="no-active-crate-msg">
          No active crate — assign issues to a crate and activate it to start processing
        </div>
      )}

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
          <label style={styles.toggleLabel}>
            <input
              type="checkbox"
              checked={!!activeCrate?.auto_crate}
              onChange={handleToggleAutoCrate}
              data-testid="auto-crate-toggle"
            />
            <span style={styles.toggleText}>Auto-crate</span>
          </label>
          <input
            type="text"
            placeholder="yyyy-mm-dd.N"
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
          <CrateRow
            key={crate.number}
            crate={crate}
            isActive={crate.number === activeCrateNumber}
            onActivate={handleActivate}
          />
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
  banner: {
    border: `1px solid ${theme.accent}`,
    borderRadius: 8,
    background: theme.accentSubtle,
    padding: 12,
  },
  bannerHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  bannerLabel: {
    fontSize: 10,
    fontWeight: 700,
    color: theme.accent,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  bannerTitle: {
    fontSize: 13,
    fontWeight: 700,
    color: theme.textBright,
    flex: 1,
  },
  bannerStats: {
    fontSize: 11,
    color: theme.textMuted,
    marginTop: 4,
  },
  advanceButton: {
    border: `1px solid ${theme.accent}`,
    background: 'transparent',
    color: theme.accent,
    borderRadius: 6,
    padding: '2px 10px',
    fontSize: 10,
    fontWeight: 600,
    cursor: 'pointer',
    flexShrink: 0,
  },
  noCrateBanner: {
    border: `1px solid ${theme.yellow}`,
    borderRadius: 8,
    background: theme.yellowSubtle || theme.surface,
    padding: 12,
    fontSize: 12,
    color: theme.yellow,
    textAlign: 'center',
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
  toggleLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    cursor: 'pointer',
    fontSize: 11,
    color: theme.textMuted,
  },
  toggleText: {
    fontSize: 11,
    color: theme.textMuted,
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
  activateButton: {
    border: `1px solid ${theme.accent}`,
    background: 'transparent',
    color: theme.accent,
    borderRadius: 6,
    padding: '2px 8px',
    fontSize: 10,
    fontWeight: 600,
    cursor: 'pointer',
    flexShrink: 0,
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
  chevron: {
    fontSize: 11,
    color: theme.textMuted,
    flexShrink: 0,
    width: 12,
  },
  barTrack: {
    height: 4,
    borderRadius: 2,
    background: theme.surfaceInset,
    overflow: 'hidden',
  },
  barGreen: {
    height: '100%',
    borderRadius: 2,
    background: theme.green,
    transition: 'width 0.3s',
  },
  progressRow: {
    display: 'flex',
    justifyContent: 'space-between',
    marginTop: 4,
  },
  progressText: {
    fontSize: 10,
    color: theme.textMuted,
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
