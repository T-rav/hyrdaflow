import React, { useCallback, useEffect, useRef, useState } from 'react'
import { theme } from '../theme'

const _repoRowBase = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  width: '100%',
  padding: '8px 10px',
  border: 'none',
  borderBottom: `1px solid ${theme.border}`,
  color: theme.text,
  textAlign: 'left',
  gap: 8,
}

export function GitHubRepoPicker({ onSelect, disabled }) {
  const [query, setQuery] = useState('')
  const [repos, setRepos] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [cloning, setCloningSlug] = useState(null)
  const [hoveredSlug, setHoveredSlug] = useState(null)
  const debounceRef = useRef(null)

  const fetchRepos = useCallback(async (searchQuery) => {
    setLoading(true)
    setError('')
    try {
      const params = searchQuery ? `?query=${encodeURIComponent(searchQuery)}` : ''
      const res = await fetch(`/api/github/repos${params}`)
      if (!res.ok) {
        let errorMsg = `status ${res.status}`
        try { const body = await res.json(); if (body.error) errorMsg = body.error } catch { /* ignore */ }
        setError(errorMsg)
        setRepos([])
        return
      }
      const data = await res.json()
      setRepos(data.repos || [])
    } catch (err) {
      setError(err.message || 'Failed to fetch repos')
      setRepos([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchRepos('')
  }, [fetchRepos])

  const handleQueryChange = useCallback((e) => {
    const val = e.target.value
    setQuery(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => fetchRepos(val), 300)
  }, [fetchRepos])

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  const handleSelect = useCallback(async (repo) => {
    const owner = repo.owner?.login || ''
    const name = repo.name || ''
    const slug = `${owner}/${name}`
    if (!slug || slug === '/') return
    setCloningSlug(slug)
    setError('')
    try {
      const res = await fetch('/api/github/clone', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slug }),
      })
      if (!res.ok) {
        let errorMsg = `status ${res.status}`
        try { const body = await res.json(); if (body.error) errorMsg = body.error } catch { /* ignore */ }
        setError(errorMsg)
        setCloningSlug(null)
        return
      }
      setCloningSlug(null)
      onSelect?.(slug)
    } catch (err) {
      setError(err.message || 'Clone failed')
      setCloningSlug(null)
    }
  }, [onSelect])

  return (
    <div style={styles.container} data-testid="github-repo-picker">
      <input
        type="text"
        value={query}
        onChange={handleQueryChange}
        placeholder="Search your GitHub repos…"
        style={styles.searchInput}
        disabled={disabled || !!cloning}
        data-testid="github-repo-search"
      />
      {error && <div style={styles.error}>{error}</div>}
      <div style={styles.repoList}>
        {loading && !cloning && (
          <div style={styles.centeredRow}>Loading repos…</div>
        )}
        {!loading && repos.length === 0 && !error && (
          <div style={styles.centeredRow}>No repos found</div>
        )}
        {repos.map((repo) => {
          const owner = repo.owner?.login || ''
          const name = repo.name || ''
          const slug = `${owner}/${name}`
          const isCloning = cloning === slug
          return (
            <button
              key={slug}
              type="button"
              onClick={() => handleSelect(repo)}
              onMouseEnter={() => setHoveredSlug(slug)}
              onMouseLeave={() => setHoveredSlug(null)}
              disabled={!!cloning || disabled}
              style={isCloning ? styles.repoRowCloning : hoveredSlug === slug ? styles.repoRowHover : styles.repoRow}
              data-testid={`github-repo-item-${slug}`}
            >
              <div style={styles.repoInfo}>
                <span style={styles.repoName}>{slug}</span>
                {repo.description && (
                  <span style={styles.repoDesc}>{repo.description}</span>
                )}
              </div>
              <span style={styles.repoAction}>
                {isCloning ? 'Cloning…' : 'Add'}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  searchInput: {
    width: '100%',
    boxSizing: 'border-box',
    padding: '8px 10px',
    borderRadius: 6,
    border: `1px solid ${theme.border}`,
    background: theme.bg,
    color: theme.text,
    fontSize: 12,
  },
  error: {
    color: theme.red,
    fontSize: 11,
  },
  repoList: {
    maxHeight: 240,
    overflowY: 'auto',
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    background: theme.bg,
  },
  centeredRow: {
    padding: '12px 10px',
    fontSize: 11,
    color: theme.textMuted,
    textAlign: 'center',
  },
  repoRow: { ..._repoRowBase, background: 'transparent', cursor: 'pointer' },
  repoRowHover: { ..._repoRowBase, background: theme.mutedSubtle, cursor: 'pointer' },
  repoRowCloning: { ..._repoRowBase, background: theme.accentSubtle, cursor: 'wait' },
  repoInfo: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    minWidth: 0,
    flex: 1,
  },
  repoName: {
    fontSize: 12,
    fontWeight: 600,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  repoDesc: {
    fontSize: 10,
    color: theme.textMuted,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  repoAction: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.accent,
    flexShrink: 0,
  },
}
