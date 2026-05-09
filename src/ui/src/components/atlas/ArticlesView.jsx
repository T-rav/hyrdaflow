import React, { useEffect, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { theme } from '../../theme'
import { WikiTopBar } from '../wiki/WikiTopBar'

export function ArticlesView() {
  const [typeFilter, setTypeFilter] = useState('all') // all | adrs | wiki
  const [linkFilter, setLinkFilter] = useState('all') // all | linked | discovered
  const [adrs, setAdrs] = useState([])
  const [repos, setRepos] = useState([])
  const [selectedRepo, setSelectedRepo] = useState(null)
  const [wikiFilters, setWikiFilters] = useState({ topic: '', status: '', q: '' })
  const [entries, setEntries] = useState([])
  const [discoveredIds, setDiscoveredIds] = useState(new Set())
  const [selected, setSelected] = useState(null)
  const [bodyDetail, setBodyDetail] = useState(null)

  // Discovered entry IDs (orphans w/ no term evidence). One fetch on mount —
  // stable enough at the cadence the term-proposer + migration script run at.
  useEffect(() => {
    let cancelled = false
    fetch('/api/atlas/discovered')
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => {
        if (cancelled) return
        const list = Array.isArray(d) ? d : []
        setDiscoveredIds(new Set(list.map((e) => e.id)))
      })
      .catch(() => {
        if (!cancelled) setDiscoveredIds(new Set())
      })
    return () => {
      cancelled = true
    }
  }, [])

  // ADRs (always loaded — small set)
  useEffect(() => {
    fetch('/api/atlas/adrs')
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => setAdrs(Array.isArray(d) ? d : []))
      .catch(() => setAdrs([]))
  }, [])

  // Wiki repos
  useEffect(() => {
    fetch('/api/wiki/repos')
      .then((r) => (r.ok ? r.json() : []))
      .then((list) => {
        const safe = Array.isArray(list) ? list : []
        setRepos(safe)
        if (safe.length > 0 && selectedRepo === null) setSelectedRepo(safe[0])
      })
      .catch(() => setRepos([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Wiki entries
  useEffect(() => {
    if (!selectedRepo) {
      setEntries([])
      return
    }
    const qs = new URLSearchParams()
    if (wikiFilters.topic) qs.set('topic', wikiFilters.topic)
    if (wikiFilters.status) qs.set('status', wikiFilters.status)
    if (wikiFilters.q) qs.set('q', wikiFilters.q)
    qs.set('limit', '200')
    fetch(
      `/api/wiki/repos/${selectedRepo.owner}/${selectedRepo.repo}/entries?${qs}`,
    )
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => setEntries(Array.isArray(d) ? d : []))
      .catch(() => setEntries([]))
  }, [selectedRepo, wikiFilters.topic, wikiFilters.status, wikiFilters.q])

  // Detail body for selected article
  useEffect(() => {
    if (!selected) {
      setBodyDetail(null)
      return
    }
    let url = null
    if (selected.type === 'adr') url = `/api/atlas/adrs/${selected.id}`
    else if (selected.type === 'wiki' && selected.repo)
      url = `/api/wiki/repos/${selected.repo.owner}/${selected.repo.repo}/entries/${selected.id}`
    if (!url) return
    let cancelled = false
    fetch(url)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!cancelled) setBodyDetail(d)
      })
      .catch(() => {
        if (!cancelled) setBodyDetail(null)
      })
    return () => {
      cancelled = true
    }
  }, [selected])

  const merged = useMemo(() => {
    const rows = []
    if (typeFilter === 'all' || typeFilter === 'adrs') {
      for (const a of adrs)
        rows.push({
          key: `adr-${a.number}`,
          type: 'adr',
          id: a.number,
          title: `ADR-${String(a.number).padStart(4, '0')}: ${a.title}`,
          meta: `${a.status ?? ''} · ${a.date ?? ''}`.trim(),
        })
    }
    if (typeFilter === 'all' || typeFilter === 'wiki') {
      for (const e of entries) {
        const isDiscovered = discoveredIds.has(e.id)
        // Link filter only applies to wiki entries — ADRs are out of scope.
        if (linkFilter === 'linked' && isDiscovered) continue
        if (linkFilter === 'discovered' && !isDiscovered) continue
        rows.push({
          key: `wiki-${e.id}-${e.topic}`,
          type: 'wiki',
          id: e.id,
          repo: { owner: e.owner, repo: e.repo },
          title: e.filename,
          meta: `${e.topic} · ${e.status} · #${e.source_issue ?? '?'}${
            isDiscovered ? ' · discovered' : ''
          }`,
        })
      }
    }
    return rows
  }, [typeFilter, linkFilter, adrs, entries, discoveredIds])

  const showWikiBar = typeFilter === 'all' || typeFilter === 'wiki'

  const styles = {
    root: { display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, width: '100%' },
    topBar: {
      display: 'flex',
      gap: 12,
      alignItems: 'center',
      padding: '10px 16px',
      background: theme.surface,
      borderBottom: `1px solid ${theme.border}`,
      flexWrap: 'wrap',
    },
    label: {
      fontSize: 12,
      color: theme.textMuted,
      textTransform: 'uppercase',
      letterSpacing: 0.5,
    },
    select: {
      background: theme.surfaceInset,
      color: theme.text,
      border: `1px solid ${theme.border}`,
      borderRadius: 4,
      padding: '4px 8px',
      fontSize: 13,
      minWidth: 140,
    },
    panes: { flex: 1, display: 'flex', minHeight: 0 },
    left: {
      width: '42%',
      minWidth: 300,
      borderRight: `1px solid ${theme.border}`,
      overflowY: 'auto',
    },
    right: { flex: 1, padding: '14px 16px', overflowY: 'auto' },
    row: (active) => ({
      padding: '8px 14px',
      borderLeft: `3px solid ${active ? theme.accent : 'transparent'}`,
      background: active ? theme.surfaceInset : 'transparent',
      cursor: 'pointer',
    }),
    chip: (kind) => ({
      display: 'inline-block',
      fontSize: 10,
      letterSpacing: 0.5,
      padding: '1px 6px',
      borderRadius: 3,
      marginRight: 6,
      color: kind === 'adr' ? '#ffcb6b' : '#82aaff',
      border: `1px solid ${kind === 'adr' ? '#ffcb6b55' : '#82aaff55'}`,
    }),
    rowTitle: { color: theme.textBright, fontSize: 13 },
    rowMeta: { color: theme.textMuted, fontSize: 11, marginTop: 2 },
    body: {
      fontSize: 13,
      lineHeight: 1.55,
      color: theme.text,
      background: theme.surfaceInset,
      border: `1px solid ${theme.border}`,
      borderRadius: 4,
      padding: 14,
    },
    title: { color: theme.textBright, fontSize: 14, margin: 0 },
    meta: { color: theme.textMuted, fontSize: 12, margin: '4px 0 12px' },
  }

  const isActive = (row) =>
    selected && selected.type === row.type && String(selected.id) === String(row.id)

  return (
    <div data-testid="atlas-articles-view" style={styles.root}>
      <div style={styles.topBar}>
        <span style={styles.label}>Type</span>
        <select
          aria-label="Type"
          style={styles.select}
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
        >
          <option value="all">All</option>
          <option value="adrs">ADRs</option>
          <option value="wiki">Wiki entries</option>
        </select>
        {showWikiBar && (
          <>
            <span style={styles.label}>Linked</span>
            <select
              aria-label="Linked to term"
              style={styles.select}
              value={linkFilter}
              onChange={(e) => setLinkFilter(e.target.value)}
            >
              <option value="all">All</option>
              <option value="linked">Linked to a term</option>
              <option value="discovered">Discovered (orphan)</option>
            </select>
            <WikiTopBar
              repos={repos}
              selectedRepo={selectedRepo}
              onRepoChange={setSelectedRepo}
              filters={wikiFilters}
              onFiltersChange={setWikiFilters}
            />
          </>
        )}
      </div>
      <div style={styles.panes}>
        <div style={styles.left}>
          {merged.length === 0 ? (
            <div
              style={{
                padding: 24,
                color: theme.textMuted,
                fontSize: 13,
                textAlign: 'center',
              }}
            >
              No articles
            </div>
          ) : (
            merged.map((row) => (
              <div
                key={row.key}
                role="button"
                tabIndex={0}
                style={styles.row(isActive(row))}
                onClick={() =>
                  setSelected({ type: row.type, id: row.id, repo: row.repo })
                }
              >
                <div>
                  <span style={styles.chip(row.type)}>
                    {row.type === 'adr' ? 'ADR' : 'WIKI'}
                  </span>
                  <span style={styles.rowTitle}>{row.title}</span>
                </div>
                <div style={styles.rowMeta}>{row.meta}</div>
              </div>
            ))
          )}
        </div>
        <div style={styles.right}>
          {bodyDetail ? (
            <div>
              <h3 style={styles.title}>
                {selected?.type === 'adr'
                  ? `ADR-${String(bodyDetail.number).padStart(4, '0')}: ${bodyDetail.title}`
                  : bodyDetail.filename}
              </h3>
              <div style={styles.meta}>
                {selected?.type === 'adr'
                  ? `${bodyDetail.status ?? ''} · ${bodyDetail.date ?? ''}`
                  : `${bodyDetail.topic} · ${bodyDetail.frontmatter?.status ?? 'unknown'}`}
              </div>
              <div style={styles.body}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {bodyDetail.body || ''}
                </ReactMarkdown>
              </div>
            </div>
          ) : (
            <div style={{ color: theme.textMuted, fontSize: 13 }}>
              Select an article to see its contents.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default ArticlesView
