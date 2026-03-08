import React, { useMemo, useState } from 'react'
import { theme } from '../theme'
import { useHydraFlow } from '../context/HydraFlowContext'

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
  hitl_approved: { color: theme.green, bg: theme.greenSubtle },
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
    whiteSpace: 'nowrap',
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

function formatCompact(n) {
  const v = Number.isFinite(n) ? n : 0
  const fmt = (val, suffix) => {
    const s = val.toFixed(1)
    return `${s.replace(/\.0$/, '')}${suffix}`
  }
  // Check thresholds top-down; use 999.95 cutoffs so .toFixed(1) rounding
  // doesn't overflow into the next magnitude (e.g. 999_950 → "1M" not "1000K")
  if (v >= 999_950_000) return fmt(v / 1e9, 'B')
  if (v >= 999_950) return fmt(v / 1e6, 'M')
  if (v >= 1e3) return fmt(v / 1e3, 'K')
  return v.toLocaleString()
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

function formatShortTs(ts) {
  if (!ts) return '-'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return '-'
  const now = new Date()
  const diffMs = now - d
  const diffHours = diffMs / (1000 * 60 * 60)
  if (diffHours < 24) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
  if (diffHours < 24 * 7) {
    return d.toLocaleDateString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
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

// Grid column template — shared between header and data rows
const GRID_COLUMNS = '26px 52px minmax(180px, 2fr) 84px 100px 50px minmax(80px, 1fr) 70px 100px'

export function OutcomesPanel() {
  const { issueHistory } = useHydraFlow()
  const [preset, setPreset] = useState('all')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [outcomeFilter, setOutcomeFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [epicOnly, setEpicOnly] = useState(false)
  const [groupBy, setGroupBy] = useState('none')
  const [expanded, setExpanded] = useState({})
  const [collapsedGroups, setCollapsedGroups] = useState(new Set())

  const loading = !issueHistory
  const payload = useMemo(() => ({
    items: Array.isArray(issueHistory?.items) ? issueHistory.items : [],
    totals: issueHistory?.totals || {},
  }), [issueHistory])

  const timeRange = useMemo(
    () => buildTimeRange(preset, customStart, customEnd),
    [preset, customStart, customEnd],
  )

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    const since = timeRange.since ? new Date(timeRange.since).getTime() : null
    const until = timeRange.until ? new Date(timeRange.until).getTime() : null
    return (payload.items || []).filter(item => {
      if (since || until) {
        const ts = item.last_seen ? new Date(item.last_seen).getTime() : 0
        if (since && ts < since) return false
        if (until && ts > until) return false
      }
      if (statusFilter !== 'all' && (item.status || 'unknown') !== statusFilter) return false
      if (outcomeFilter !== 'all' && item.outcome?.outcome !== outcomeFilter) return false
      if (epicOnly && !item.epic) return false
      if (!q) return true
      const issueText = `#${item.issue_number} ${(item.title || '').toLowerCase()}`
      if (issueText.includes(q)) return true
      if ((item.epic || '').toLowerCase().includes(q)) return true
      if ((item.crate_title || '').toLowerCase().includes(q)) return true
      return false
    })
  }, [payload.items, statusFilter, outcomeFilter, epicOnly, search, timeRange.since, timeRange.until])

  const grouped = useMemo(() => {
    if (groupBy === 'none') return null
    const groups = {}
    for (const item of filtered) {
      let label
      if (groupBy === 'crate') {
        label = item.crate_number
          ? (item.crate_title || `Crate #${item.crate_number}`)
          : 'Uncrated'
      } else {
        label = item.epic || 'Ungrouped'
      }
      if (!groups[label]) groups[label] = { items: [], meta: {}, sortKey: null }
      groups[label].items.push(item)
    }
    if (groupBy === 'crate') {
      for (const [label, group] of Object.entries(groups)) {
        const items = group.items
        group.sortKey = label === 'Uncrated' ? Infinity : (items[0]?.crate_number ?? Infinity)
        group.meta = {
          total: items.length,
          merged: items.filter(i => i.outcome?.outcome === 'merged').length,
          failed: items.filter(i => i.outcome?.outcome === 'failed').length,
          tokens: items.reduce((s, i) => s + (i.inference?.total_tokens || 0), 0),
        }
      }
    }
    return groups
  }, [filtered, groupBy])

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

  const toggleExpanded = (issueNumber) => {
    setExpanded(prev => ({ ...prev, [issueNumber]: !prev[issueNumber] }))
  }

  const toggleGroupCollapse = (label) => {
    setCollapsedGroups(prev => {
      const next = new Set(prev)
      if (next.has(label)) next.delete(label)
      else next.add(label)
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
    const title = item.title || ''
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
          <a href={item.issue_url || '#'} target="_blank" rel="noreferrer" style={styles.issueLink}>
            #{issueNum}
          </a>
          <span style={styles.titleCell} title={title || `Issue #${issueNum}`}>
            {title || <span style={styles.dimText}>Untitled</span>}
          </span>
          <span style={statusStyle(item.status || 'unknown')}>{item.status || 'unknown'}</span>
          <span style={styles.outcomeCell}>
            {outcomeType
              ? <span style={outcomeBadgeStyles[outcomeType] || outcomeBadgeStyles.manual_close}>{outcomeType.replace(/_/g, ' ')}</span>
              : <span style={styles.dimText}>\u2014</span>}
          </span>
          <span style={styles.metaCell}>{item.prs?.length || 0}</span>
          <span style={styles.epicCell} title={item.epic || ''}>{item.epic || <span style={styles.dimText}>\u2014</span>}</span>
          <span style={styles.tokenCell} title={`${formatNumber(issueActualTokens)} actual · ${formatNumber(issueSavedTokens)} saved`}>
            {formatCompact(issueActualTokens)}
          </span>
          <span style={styles.timeCell} title={formatTs(item.last_seen)}>{formatShortTs(item.last_seen)}</span>
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

  function renderCrateItems(items, crateLabel) {
    const epics = {}
    for (const item of items) {
      const epicLabel = item.epic || 'No epic'
      if (!epics[epicLabel]) epics[epicLabel] = []
      epics[epicLabel].push(item)
    }
    const epicKeys = Object.keys(epics)
    if (epicKeys.length === 1 && epicKeys[0] === 'No epic') {
      return items.map(item => renderIssueRow(item))
    }
    return Object.entries(epics)
      .sort(([a], [b]) => (a === 'No epic' ? 1 : b === 'No epic' ? -1 : a.localeCompare(b)))
      .map(([epicLabel, epicItems]) => {
        const subKey = `${crateLabel}::${epicLabel}`
        const isSubCollapsed = collapsedGroups.has(subKey)
        return (
          <div key={subKey}>
            <button
              type="button"
              onClick={() => toggleGroupCollapse(subKey)}
              style={styles.subEpicHeader}
              aria-expanded={!isSubCollapsed}
              aria-label={`Toggle ${epicLabel} sub-group`}
            >
              <span>{isSubCollapsed ? '▸' : '▾'}</span>
              <span style={styles.epicTitle}>{epicLabel}</span>
              <span style={styles.epicCount}>{epicItems.length} issue{epicItems.length !== 1 ? 's' : ''}</span>
            </button>
            {!isSubCollapsed && epicItems.map(item => renderIssueRow(item))}
          </div>
        )
      })
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
            placeholder="Search issue #, title, epic, crate"
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
          <select value={groupBy} onChange={e => setGroupBy(e.target.value)} style={styles.select}>
            <option value="none">No grouping</option>
            <option value="epic">Group by epic</option>
            <option value="crate">Group by crate</option>
          </select>
          <label style={styles.checkboxLabel}>
            <input type="checkbox" checked={epicOnly} onChange={e => setEpicOnly(e.target.checked)} />
            Epic only
          </label>
        </div>
      </div>

      <div style={styles.summaryRow}>
        <span style={styles.summaryCount}>{filtered.length} issues</span>
        <span>{formatCompact(visibleTotals.total_tokens)} tok</span>
        <span>{formatCompact(visibleSavedTokens)} saved</span>
        <span style={styles.summaryDivider}>|</span>
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

      {loading && <div style={styles.info}>Loading...</div>}

      <div style={styles.table}>
        <div style={styles.headerRow}>
          <span />
          <span style={styles.headerCell}>#</span>
          <span style={styles.headerCell}>Title</span>
          <span style={styles.headerCell}>Stage</span>
          <span style={styles.headerCell}>Outcome</span>
          <span style={styles.headerCell}>PRs</span>
          <span style={styles.headerCell}>Epic</span>
          <span style={styles.headerCellRight}>Tokens</span>
          <span style={styles.headerCellRight}>Last Seen</span>
        </div>

        <div style={styles.tableBody}>
          {grouped ? (
            Object.entries(grouped)
              .sort(([a, ga], [b, gb]) => {
                const bottomLabel = groupBy === 'crate' ? 'Uncrated' : 'Ungrouped'
                if (a === bottomLabel) return 1
                if (b === bottomLabel) return -1
                if (groupBy === 'crate' && ga.sortKey != null && gb.sortKey != null) {
                  return ga.sortKey - gb.sortKey
                }
                return a.localeCompare(b)
              })
              .map(([label, group]) => {
                const isCollapsed = collapsedGroups.has(label)
                const items = group.items
                if (groupBy === 'crate') {
                  const meta = group.meta || {}
                  const progressPct = meta.total ? Math.min(100, Math.round((meta.merged / meta.total) * 100)) : 0
                  return (
                    <div key={label}>
                      <button
                        type="button"
                        onClick={() => toggleGroupCollapse(label)}
                        style={styles.crateHeader}
                        aria-expanded={!isCollapsed}
                        aria-label={`Toggle ${label} group`}
                      >
                        <span>{isCollapsed ? '▸' : '▾'}</span>
                        <span style={styles.crateTitle}>{label}</span>
                        <span style={styles.crateMeta}>
                          {meta.merged}/{meta.total} merged
                        </span>
                        <span style={styles.crateBar}>
                          <span style={{ ...styles.crateBarFill, width: `${progressPct}%` }} />
                        </span>
                        {meta.failed > 0 && (
                          <span style={styles.crateFailCount}>{meta.failed} failed</span>
                        )}
                        <span style={styles.crateTokens}>{formatCompact(meta.tokens)} tok</span>
                      </button>
                      {!isCollapsed && renderCrateItems(items, label)}
                    </div>
                  )
                }
                return (
                  <div key={label}>
                    <button
                      type="button"
                      onClick={() => toggleGroupCollapse(label)}
                      style={styles.epicHeader}
                      aria-expanded={!isCollapsed}
                      aria-label={`Toggle ${label} group`}
                    >
                      <span>{isCollapsed ? '▸' : '▾'}</span>
                      <span style={styles.epicTitle}>{label}</span>
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
    flexShrink: 0,
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
    minWidth: 220,
    flex: 1,
    border: `1px solid ${theme.border}`,
    background: theme.surfaceInset,
    color: theme.text,
    borderRadius: 6,
    padding: '6px 8px',
    fontSize: 12,
  },
  select: {
    minWidth: 130,
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
    gap: 12,
    fontSize: 11,
    color: theme.textMuted,
    padding: '0 2px',
    alignItems: 'center',
    flexWrap: 'wrap',
    flexShrink: 0,
  },
  summaryCount: {
    fontWeight: 700,
    color: theme.textBright,
  },
  summaryDivider: {
    color: theme.border,
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
    flex: 1,
    minHeight: 0,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  headerRow: {
    display: 'grid',
    gridTemplateColumns: GRID_COLUMNS,
    gap: 8,
    alignItems: 'center',
    padding: '6px 10px',
    fontSize: 10,
    fontWeight: 700,
    color: theme.textMuted,
    textTransform: 'uppercase',
    letterSpacing: '0.4px',
    borderBottom: `1px solid ${theme.border}`,
    background: theme.surfaceInset,
    flexShrink: 0,
  },
  headerCell: {
    whiteSpace: 'nowrap',
    overflow: 'hidden',
  },
  headerCellRight: {
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textAlign: 'right',
  },
  tableBody: {
    overflowY: 'auto',
    flex: 1,
    minHeight: 0,
  },
  rowWrap: {
    borderBottom: `1px solid ${theme.border}`,
  },
  row: {
    display: 'grid',
    gridTemplateColumns: GRID_COLUMNS,
    gap: 8,
    alignItems: 'center',
    padding: '7px 10px',
    fontSize: 12,
  },
  expandButton: {
    border: 'none',
    background: 'transparent',
    color: theme.textMuted,
    cursor: 'pointer',
    fontSize: 12,
    padding: 0,
  },
  issueLink: {
    color: theme.accent,
    textDecoration: 'none',
    fontWeight: 700,
    whiteSpace: 'nowrap',
  },
  titleCell: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    minWidth: 0,
  },
  dimText: {
    color: theme.textMuted,
    opacity: 0.5,
  },
  outcomeCell: {
    whiteSpace: 'nowrap',
    overflow: 'hidden',
  },
  metaCell: {
    color: theme.textMuted,
    whiteSpace: 'nowrap',
    textAlign: 'center',
  },
  epicCell: {
    color: theme.textMuted,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    minWidth: 0,
  },
  tokenCell: {
    color: theme.textMuted,
    whiteSpace: 'nowrap',
    textAlign: 'right',
    fontVariantNumeric: 'tabular-nums',
  },
  timeCell: {
    color: theme.textMuted,
    whiteSpace: 'nowrap',
    textAlign: 'right',
    fontSize: 11,
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
  crateHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    width: '100%',
    padding: '8px 10px',
    border: 'none',
    borderBottom: `1px solid ${theme.border}`,
    borderLeft: `3px solid ${theme.purple}`,
    background: theme.surfaceInset,
    cursor: 'pointer',
    fontSize: 12,
    color: theme.text,
    textAlign: 'left',
  },
  crateTitle: {
    fontWeight: 700,
  },
  crateMeta: {
    color: theme.textMuted,
    fontSize: 11,
    whiteSpace: 'nowrap',
  },
  crateBar: {
    width: 60,
    height: 6,
    borderRadius: 3,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    overflow: 'hidden',
    flexShrink: 0,
  },
  crateBarFill: {
    height: '100%',
    background: theme.green,
    borderRadius: 3,
    transition: 'width 0.2s ease',
  },
  crateFailCount: {
    color: theme.red,
    fontSize: 10,
    fontWeight: 700,
  },
  crateTokens: {
    color: theme.textMuted,
    fontSize: 10,
    marginLeft: 'auto',
    whiteSpace: 'nowrap',
  },
  subEpicHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    width: '100%',
    padding: '6px 10px 6px 24px',
    border: 'none',
    borderBottom: `1px solid ${theme.border}`,
    borderLeft: `3px solid ${theme.accent}`,
    background: theme.surface,
    cursor: 'pointer',
    fontSize: 11,
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
}

const buttonActiveStyle = {
  ...styles.button,
  color: theme.accent,
  borderColor: theme.accent,
  background: theme.accentSubtle,
}
