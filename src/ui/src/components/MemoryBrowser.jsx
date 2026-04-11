import React, { useState, useCallback, useEffect } from 'react'
import { theme } from '../theme'

export function MemoryBrowser() {
  const [banks, setBanks] = useState([])
  const [query, setQuery] = useState('')
  const [bankFilter, setBankFilter] = useState('')
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    fetch('/api/memory/banks')
      .then(r => r.json())
      .then(data => setBanks(data.banks || []))
      .catch(() => setBanks([]))
  }, [])

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ q: query.trim() })
      if (bankFilter) params.set('bank', bankFilter)
      const resp = await fetch(`/api/memory/search?${params}`)
      if (!resp.ok) throw new Error(`status ${resp.status}`)
      const data = await resp.json()
      setResults(data)
    } catch {
      setError('Search failed. Is Hindsight available?')
      setResults(null)
    } finally {
      setLoading(false)
    }
  }, [query, bankFilter])

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter') handleSearch()
  }, [handleSearch])

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.title}>Memory Browser</span>
        <span style={styles.subtitle}>Search Hindsight banks</span>
      </div>

      <div style={styles.searchRow}>
        <input
          style={styles.searchInput}
          type="text"
          placeholder="Search memories..."
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          data-testid="memory-search-input"
        />
        <select
          style={styles.bankSelect}
          value={bankFilter}
          onChange={e => setBankFilter(e.target.value)}
          data-testid="memory-bank-select"
        >
          <option value="">All banks</option>
          {banks.map(b => (
            <option key={b.id} value={b.id}>{b.name}</option>
          ))}
        </select>
        <button
          style={loading ? styles.searchBtnDisabled : styles.searchBtn}
          onClick={handleSearch}
          disabled={loading || !query.trim()}
          data-testid="memory-search-btn"
        >
          {loading ? 'Searching...' : 'Search'}
        </button>
      </div>

      {error && <div style={styles.error}>{error}</div>}

      {results && (
        <div style={styles.results} data-testid="memory-results">
          {results.items && results.items.length > 0 ? (
            results.items.map((item, idx) => (
              <div key={idx} style={styles.resultCard}>
                <div style={styles.resultHeader}>
                  <span style={styles.bankBadge}>{bankDisplayName(item.bank)}</span>
                  {item.relevance_score > 0 && (
                    <span style={styles.score}>
                      {(item.relevance_score * 100).toFixed(0)}% match
                    </span>
                  )}
                </div>
                <div style={styles.resultContent}>{item.content}</div>
                {item.context && (
                  <div style={styles.resultContext}>{item.context}</div>
                )}
              </div>
            ))
          ) : (
            <div style={styles.empty}>No memories found for "{results.query}"</div>
          )}
        </div>
      )}

      {!results && !error && (
        <div style={styles.empty}>
          Enter a query to search across memory banks.
        </div>
      )}
    </div>
  )
}

function bankDisplayName(bankId) {
  return bankId.replace('hydraflow-', '').replace(/-/g, ' ').toUpperCase()
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
    padding: 16,
  },
  header: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  title: {
    fontSize: 16,
    fontWeight: 700,
    color: theme.textBright,
  },
  subtitle: {
    fontSize: 12,
    color: theme.textMuted,
  },
  searchRow: {
    display: 'flex',
    gap: 8,
    alignItems: 'center',
  },
  searchInput: {
    flex: 1,
    padding: '8px 12px',
    fontSize: 13,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    color: theme.text,
    outline: 'none',
  },
  bankSelect: {
    padding: '8px 12px',
    fontSize: 13,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    color: theme.text,
    cursor: 'pointer',
  },
  searchBtn: {
    padding: '8px 16px',
    fontSize: 13,
    fontWeight: 600,
    background: theme.accent,
    color: theme.white,
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
  },
  searchBtnDisabled: {
    padding: '8px 16px',
    fontSize: 13,
    fontWeight: 600,
    background: theme.border,
    color: theme.textMuted,
    border: 'none',
    borderRadius: 6,
    cursor: 'not-allowed',
  },
  error: {
    fontSize: 12,
    color: theme.red,
    padding: '8px 12px',
    background: theme.redSubtle,
    borderRadius: 6,
  },
  results: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  resultCard: {
    padding: 12,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
  },
  resultHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  bankBadge: {
    fontSize: 10,
    fontWeight: 700,
    padding: '2px 8px',
    borderRadius: 4,
    background: theme.purpleSubtle,
    color: theme.purple,
    letterSpacing: '0.5px',
  },
  score: {
    fontSize: 11,
    color: theme.textMuted,
  },
  resultContent: {
    fontSize: 13,
    color: theme.text,
    lineHeight: 1.5,
    whiteSpace: 'pre-wrap',
  },
  resultContext: {
    fontSize: 11,
    color: theme.textMuted,
    marginTop: 8,
    fontStyle: 'italic',
  },
  empty: {
    fontSize: 13,
    color: theme.textMuted,
    padding: 24,
    textAlign: 'center',
  },
}
