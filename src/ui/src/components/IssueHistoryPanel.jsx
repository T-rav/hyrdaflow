import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { theme } from '../theme'

const RANGE_PRESETS = [
  { key: '24h', label: '24h', hours: 24 },
  { key: '7d', label: '7d', hours: 24 * 7 },
  { key: '30d', label: '30d', hours: 24 * 30 },
  { key: '90d', label: '90d', hours: 24 * 90 },
  { key: 'all', label: 'All', hours: null },
  { key: 'custom', label: 'Custom', hours: null },
]

const STATUS_OPTIONS = [
  'all',
  'unknown',
  'active',
  'triaged',
  'planned',
  'implemented',
  'in_review',
  'reviewed',
  'hitl',
  'failed',
  'merged',
]

const OUTCOME_TYPES = [
  'all', 'merged', 'already_satisfied', 'hitl_closed',
  'hitl_skipped', 'hitl_approved', 'failed', 'manual_close',
]

const OUTCOME_COLORS = {
  merged: { color: theme.green, bg: theme.greenSubtle },
  already_satisfied: { color: theme.accent, bg: theme.accentSubtle },
  hitl_closed: { color: theme.orange, bg: theme.orangeSubtle },
  hitl_skipped: { color: theme.yellow, bg: theme.yellowSubtle },
  failed: { color: theme.red, bg: theme.redSubtle },
  manual_close: { color: theme.textMuted, bg: theme.surfaceInset },
}

const LINK_KIND_META = {
  relates_to: { label: 'relates to', color: theme.accent, bg: theme.accentSubtle },
  duplicates: { label: 'duplicates', color: theme.orange, bg: theme.orangeSubtle },
  supersedes: { label: 'supersedes', color: theme.purple, bg: theme.purpleSubtle },
  replies_to: { label: 'replies to', color: theme.green, bg: theme.greenSubtle },
}

function statusStyle(status) {
  const common = {
    display: 'inline-flex',
    alignItems: 'center',
    borderRadius: 999,
    fontSize: 10,
    fontWeight: 700,
    padding: '2px 8px',
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  }
  if (status === 'merged') return { ...common, background: theme.greenSubtle || theme.surface, color: theme.green }
  if (status === 'failed') return { ...common, background: theme.redSubtle || theme.surface, color: theme.red }
  if (status === 'hitl') return { ...common, background: theme.yellowSubtle || theme.surface, color: theme.yellow }
  if (status === 'active') return { ...common, background: theme.accentSubtle || theme.surface, color: theme.accent }
  return { ...common, background: theme.surfaceInset, color: theme.textMuted }
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

function formatNumber(n) {
  return (Number.isFinite(n) ? n : 0).toLocaleString()
}

function estimateSavedTokens(prunedChars) {
  const chars = Number(prunedChars || 0)
  if (!Number.isFinite(chars) || chars <= 0) return 0
  return Math.round(chars / 4)
}

function formatTs(ts) {
  if (!ts) return '-'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return '-'
  return d.toLocaleString()
}

function buildTimeRange(preset, customStart, customEnd) {
  if (preset === 'all') return { since: null, until: null }
  if (preset === 'custom') {
    const toIso = (value) => {
      if (!value) return null
      const parsed = new Date(value)
      return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString()
    }
    const since = toIso(customStart)
    const until = toIso(customEnd)
    return { since, until }
  }
  const found = RANGE_PRESETS.find(p => p.key === preset)
  if (!found || found.hours == null) return { since: null, until: null }
  const untilDate = new Date()
  const sinceDate = new Date(untilDate.getTime() - found.hours * 60 * 60 * 1000)
  return { since: sinceDate.toISOString(), until: untilDate.toISOString() }
}

function renderLinkedIssue(linked, index) {
  // Backward compat: if entry is a plain int (old data), render as before
  if (typeof linked === 'number') {
    return <span key={linked} style={styles.linkedPill}>#{linked}</span>
  }
  const kind = linked.kind || 'relates_to'
  const meta = LINK_KIND_META[kind] || LINK_KIND_META.relates_to
  const pillStyle = {
    ...styles.linkedPill,
    borderColor: meta.color,
    color: meta.color,
    background: meta.bg || theme.surface,
  }
  return (
    <span key={`${kind}-${linked.target_id}-${index}`} style={pillStyle}>
      {meta.label} #{linked.target_id}
    </span>
  )
}

export function OutcomesPanel() {
  const [preset, setPreset] = useState('30d')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [outcomeFilter, setOutcomeFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [epicOnly, setEpicOnly] = useState(false)
  const [groupByEpic, setGroupByEpic] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [payload, setPayload] = useState({ items: [], totals: {} })
  const [expanded, setExpanded] = useState({})
  const [collapsedEpics, setCollapsedEpics] = useState(new Set())
  const cachedPayload = useRef(null)
  const refreshTimer = useRef(null)

  const timeRange = useMemo(
    () => buildTimeRange(preset, customStart, customEnd),
    [preset, customStart, customEnd],
  )

  const fetchHistory = useCallback((params, { background = false } = {}) => {
    if (!background) {
      // Show cached data immediately if available (stale-while-revalidate)
      if (cachedPayload.current) {
        setPayload(cachedPayload.current)
      }
      setLoading(true)
      setError('')
    }

    return fetch(`/api/issues/history?${params.toString()}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`status ${res.status}`)
        return await res.json()
      })
      .then(data => {
        const next = {
          items: Array.isArray(data.items) ? data.items : [],
          totals: data.totals || {},
        }
        cachedPayload.current = next
        setPayload(next)
      })
      .catch(() => {
        if (!background) setError('Could not load issue history')
      })
      .finally(() => {
        if (!background) setLoading(false)
      })
  }, [])

  useEffect(() => {
    const params = new URLSearchParams()
    if (timeRange.since) params.set('since', timeRange.since)
    if (timeRange.until) params.set('until', timeRange.until)
    params.set('limit', '500')

    fetchHistory(params)

    // Background refresh every 30s
    clearInterval(refreshTimer.current)
    refreshTimer.current = setInterval(() => {
      fetchHistory(params, { background: true })
    }, 30_000)

    return () => clearInterval(refreshTimer.current)
  }, [timeRange.since, timeRange.until, fetchHistory])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (payload.items || []).filter(item => {
      if (statusFilter !== 'all' && (item.status || 'unknown') !== statusFilter) return false
      if (outcomeFilter !== 'all' && item.outcome?.outcome !== outcomeFilter) return false
      if (epicOnly && !item.epic) return false
      if (!q) return true
      const issueText = `#${item.issue_number} ${(item.title || '').toLowerCase()}`
      if (issueText.includes(q)) return true
      if ((item.epic || '').toLowerCase().includes(q)) return true
      return false
    })
  }, [payload.items, statusFilter, outcomeFilter, epicOnly, search])

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

  const visibleTotals = useMemo(() => {
    return filtered.reduce((acc, item) => {
      acc.total_tokens += Number(item.inference?.total_tokens || 0)
      acc.inference_calls += Number(item.inference?.inference_calls || 0)
      acc.pruned_chars_total += Number(item.inference?.pruned_chars_total || 0)
      return acc
    }, { total_tokens: 0, inference_calls: 0, pruned_chars_total: 0 })
  }, [filtered])

  const summaryCounts = useMemo(() => {
    const counts = {}
    for (const item of filtered) {
      const t = item.outcome?.outcome || 'unknown'
      counts[t] = (counts[t] || 0) + 1
    }
    return counts
  }, [filtered])

  const visibleSavedTokens = estimateSavedTokens(visibleTotals.pruned_chars_total)
  const visibleUnprunedTokens = visibleTotals.total_tokens + visibleSavedTokens

  const toggleExpanded = (issueNumber) => {
    setExpanded(prev => ({ ...prev, [issueNumber]: !prev[issueNumber] }))
  }

  const toggleEpicCollapse = (epicLabel) => {
    setCollapsedEpics(prev => {
      const next = new Set(prev)
      if (next.has(epicLabel)) next.delete(epicLabel)
      else next.add(epicLabel)
      return next
    })
  }

  function renderIssueRow(item) {
    const issueNum = item.issue_number
    const isExpanded = !!expanded[issueNum]
    const issueActualTokens = Number(item.inference?.total_tokens || 0)
    const issueSavedTokens = estimateSavedTokens(item.inference?.pruned_chars_total || 0)
    const issueUnprunedTokens = issueActualTokens + issueSavedTokens
    const outcomeType = item.outcome?.outcome
    return (
      <div key={issueNum} style={styles.rowWrap}>
        <div style={styles.row}>
          <button
            type="button"
            onClick={() => toggleExpanded(issueNum)}
            style={styles.expandButton}
            aria-label={`Toggle issue ${issueNum}`}
          >
            {isExpanded ? '▾' : '▸'}
          </button>
          <div style={styles.issueCell}>
            <a href={item.issue_url || '#'} target="_blank" rel="noreferrer" style={styles.issueLink}>
              #{issueNum}
            </a>
            <span style={styles.issueTitle}>{item.title || `Issue #${issueNum}`}</span>
          </div>
          <span style={statusStyle(item.status || 'unknown')}>{item.status || 'unknown'}</span>
          <span style={styles.outcomeCell}>
            {outcomeType
              ? <span style={outcomeBadgeStyles[outcomeType] || outcomeBadgeStyles.manual_close}>{outcomeType.replace(/_/g, ' ')}</span>
              : <span style={styles.metaCell}>-</span>}
          </span>
          <span style={styles.metaCell}>{item.prs?.length || 0} PRs</span>
          <span style={styles.metaCell}>{item.epic || '-'}</span>
          <span style={styles.metaCell}>
            {formatNumber(issueActualTokens)} tok
            {' · '}
            {formatNumber(issueSavedTokens)} saved
          </span>
          <span style={styles.metaCell}>{formatTs(item.last_seen)}</span>
        </div>

        {isExpanded && (
          <div style={styles.expanded}>
            {item.outcome?.outcome && (
              <div style={styles.expRow}>
                <span style={styles.expLabel}>Outcome</span>
                <span style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={outcomeBadgeStyles[item.outcome.outcome] || outcomeBadgeStyles.manual_close}>
                    {item.outcome.outcome.replace(/_/g, ' ')}
                  </span>
                  {item.outcome.reason && <span>{item.outcome.reason}</span>}
                  {item.outcome.phase && <span style={{ color: theme.textMuted }}>phase: {item.outcome.phase}</span>}
                  {item.outcome.pr_number != null && (
                    <span style={{ color: theme.textMuted }}>PR #{item.outcome.pr_number}</span>
                  )}
                  {item.outcome.closed_at && (
                    <span style={{ color: theme.textMuted }}>closed: {formatTs(item.outcome.closed_at)}</span>
                  )}
                </span>
              </div>
            )}
            <div style={styles.expRow}>
              <span style={styles.expLabel}>PRs</span>
              <span>
                {(item.prs || []).length > 0
                  ? item.prs.map(pr => (
                    <a key={pr.number} href={pr.url || '#'} target="_blank" rel="noreferrer" style={styles.inlineLink}>
                      #{pr.number}{pr.merged ? ' (merged)' : ''}
                    </a>
                  ))
                  : '-'}
              </span>
            </div>
            <div style={styles.expRow}>
              <span style={styles.expLabel}>Linked Issues</span>
              <span>
                {(item.linked_issues || []).length > 0
                  ? item.linked_issues.map((linked, idx) => renderLinkedIssue(linked, idx))
                  : '-'}
              </span>
            </div>
            <div style={styles.expRow}>
              <span style={styles.expLabel}>Inference</span>
              <span>
                {formatNumber(item.inference?.inference_calls || 0)} calls
                {' · '}
                {formatNumber(issueActualTokens)} tokens (actual)
                {' · '}
                {formatNumber(issueSavedTokens)} tokens saved (est)
                {' · '}
                {formatNumber(issueUnprunedTokens)} tokens w/o pruning (est)
                {' · '}in: {formatNumber(item.inference?.input_tokens || 0)} / out: {formatNumber(item.inference?.output_tokens || 0)}
                {' · '}pruned chars: {formatNumber(item.inference?.pruned_chars_total || 0)}
              </span>
            </div>
            <div style={styles.expRow}>
              <span style={styles.expLabel}>Models</span>
              <span>{Object.entries(item.model_calls || {}).map(([k, v]) => `${k} (${v})`).join(', ') || '-'}</span>
            </div>
            <div style={styles.expRow}>
              <span style={styles.expLabel}>Sources</span>
              <span>{Object.entries(item.source_calls || {}).map(([k, v]) => `${k} (${v})`).join(', ') || '-'}</span>
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.controls}>
        <div style={styles.controlGroup}>
          <span style={styles.controlLabel}>Range</span>
          <div style={styles.rangeRow}>
            {RANGE_PRESETS.map(opt => (
              <button
                key={opt.key}
                type="button"
                onClick={() => setPreset(opt.key)}
                style={preset === opt.key ? buttonActiveStyle : styles.button}
              >
                {opt.label}
              </button>
            ))}
          </div>
          {preset === 'custom' && (
            <div style={styles.customRow}>
              <input
                type="datetime-local"
                value={customStart}
                onChange={e => setCustomStart(e.target.value)}
                style={styles.input}
              />
              <input
                type="datetime-local"
                value={customEnd}
                onChange={e => setCustomEnd(e.target.value)}
                style={styles.input}
              />
            </div>
          )}
        </div>

        <div style={styles.filterRow}>
          <input
            type="text"
            placeholder="Search issue #, title, epic"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={styles.searchInput}
          />
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={styles.select}>
            {STATUS_OPTIONS.map(opt => (
              <option key={opt} value={opt}>{opt === 'all' ? 'All statuses' : opt}</option>
            ))}
          </select>
          <select value={outcomeFilter} onChange={e => setOutcomeFilter(e.target.value)} style={styles.select} data-testid="outcome-filter">
            {OUTCOME_TYPES.map(opt => (
              <option key={opt} value={opt}>{opt === 'all' ? 'All outcomes' : opt.replace(/_/g, ' ')}</option>
            ))}
          </select>
          <label style={styles.checkboxLabel}>
            <input type="checkbox" checked={epicOnly} onChange={e => setEpicOnly(e.target.checked)} />
            Epic only
          </label>
          <label style={styles.checkboxLabel}>
            <input type="checkbox" checked={groupByEpic} onChange={e => setGroupByEpic(e.target.checked)} />
            Group by epic
          </label>
        </div>
      </div>

      <div style={styles.summaryRow}>
        <span>{filtered.length} issues</span>
        <span>{formatNumber(visibleTotals.inference_calls)} calls</span>
        <span>{formatNumber(visibleTotals.total_tokens)} tokens (actual)</span>
        <span>{formatNumber(visibleSavedTokens)} tokens saved (est)</span>
        <span>{formatNumber(visibleUnprunedTokens)} tokens w/o pruning (est)</span>
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

      {loading && <div style={styles.info}>Loading issue history...</div>}
      {error && <div style={styles.error}>{error}</div>}

      <div style={styles.table}>
        {grouped ? (
          Object.entries(grouped)
            .sort(([a], [b]) => (a === 'Ungrouped' ? 1 : b === 'Ungrouped' ? -1 : a.localeCompare(b)))
            .map(([epicLabel, items]) => {
              const isCollapsed = collapsedEpics.has(epicLabel)
              return (
                <div key={epicLabel}>
                  <button
                    type="button"
                    onClick={() => toggleEpicCollapse(epicLabel)}
                    style={styles.epicHeader}
                  >
                    <span>{isCollapsed ? '▸' : '▾'}</span>
                    <span style={styles.epicTitle}>{epicLabel}</span>
                    <span style={styles.epicCount}>{items.length} issue{items.length !== 1 ? 's' : ''}</span>
                  </button>
                  {!isCollapsed && items.map(item => renderIssueRow(item))}
                </div>
              )
            })
        ) : (
          filtered.map(item => renderIssueRow(item))
        )}

        {!loading && filtered.length === 0 && (
          <div style={styles.info}>No issues match this filter.</div>
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
  controlGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  controlLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: theme.textMuted,
    textTransform: 'uppercase',
  },
  rangeRow: {
    display: 'flex',
    gap: 6,
    flexWrap: 'wrap',
  },
  customRow: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap',
  },
  filterRow: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap',
  },
  input: {
    border: `1px solid ${theme.border}`,
    background: theme.surfaceInset,
    color: theme.text,
    borderRadius: 6,
    padding: '6px 8px',
    fontSize: 12,
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
  button: {
    border: `1px solid ${theme.border}`,
    background: theme.surfaceInset,
    color: theme.textMuted,
    borderRadius: 6,
    padding: '4px 8px',
    fontSize: 11,
    cursor: 'pointer',
  },
  summaryRow: {
    display: 'flex',
    gap: 16,
    fontSize: 12,
    color: theme.textMuted,
    padding: '0 2px',
    alignItems: 'center',
    flexWrap: 'wrap',
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
  rowWrap: {
    borderBottom: `1px solid ${theme.border}`,
  },
  row: {
    display: 'grid',
    gridTemplateColumns: '26px minmax(260px, 1.4fr) auto 100px 80px minmax(120px, 1fr) 120px 170px',
    gap: 8,
    alignItems: 'center',
    padding: '8px 10px',
    fontSize: 12,
  },
  expandButton: {
    border: 'none',
    background: 'transparent',
    color: theme.textMuted,
    cursor: 'pointer',
    fontSize: 12,
  },
  issueCell: {
    minWidth: 0,
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  issueLink: {
    color: theme.accent,
    textDecoration: 'none',
    fontWeight: 700,
    flexShrink: 0,
  },
  issueTitle: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  outcomeCell: {
    whiteSpace: 'nowrap',
    overflow: 'hidden',
  },
  metaCell: {
    color: theme.textMuted,
    whiteSpace: 'nowrap',
  },
  expanded: {
    borderTop: `1px dashed ${theme.border}`,
    padding: '8px 10px 10px 36px',
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    fontSize: 12,
    color: theme.text,
  },
  expRow: {
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap',
    alignItems: 'center',
  },
  expLabel: {
    minWidth: 98,
    color: theme.textMuted,
    fontWeight: 600,
  },
  inlineLink: {
    color: theme.accent,
    marginRight: 8,
    textDecoration: 'none',
  },
  linkedPill: {
    display: 'inline-flex',
    alignItems: 'center',
    border: `1px solid ${theme.border}`,
    borderRadius: 999,
    padding: '1px 6px',
    marginRight: 6,
    fontSize: 10,
    color: theme.textMuted,
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

const buttonActiveStyle = {
  ...styles.button,
  color: theme.accent,
  borderColor: theme.accent,
  background: theme.accentSubtle,
}
