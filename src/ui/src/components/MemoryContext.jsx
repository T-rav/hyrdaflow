import React, { useState, useEffect, useCallback } from 'react'
import { theme } from '../theme'

/**
 * Displays memory context for a specific issue.
 * Used in both HITL expanded rows and StreamCard expanded views.
 */
export function MemoryContext({ issueNumber, variant }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)

  const endpoint = variant === 'hitl'
    ? `/api/memory/hitl/${issueNumber}`
    : `/api/memory/issue/${issueNumber}`

  const loadMemory = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const resp = await fetch(endpoint)
      if (!resp.ok) throw new Error(`status ${resp.status}`)
      const payload = await resp.json()
      setData(payload)
    } catch {
      setError('Could not load memory context.')
    } finally {
      setLoading(false)
    }
  }, [endpoint])

  useEffect(() => {
    if (expanded && !data && !loading) {
      loadMemory()
    }
  }, [expanded, data, loading, loadMemory])

  const toggle = useCallback(() => setExpanded(v => !v), [])

  const items = data?.items || []
  const hasItems = items.length > 0

  return (
    <div style={styles.container} data-testid={`memory-context-${issueNumber}`}>
      <div
        style={styles.header}
        onClick={toggle}
        role="button"
        tabIndex={0}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle() } }}
      >
        <span style={styles.headerLabel}>Memory Context</span>
        {hasItems && <span style={styles.countBadge}>{items.length}</span>}
        <span style={styles.arrow}>{expanded ? '\u25BE' : '\u25B8'}</span>
      </div>

      {expanded && (
        <div style={styles.body}>
          {loading && <div style={styles.loading}>Loading memory context...</div>}
          {error && <div style={styles.error}>{error}</div>}
          {!loading && !error && !hasItems && (
            <div style={styles.empty}>No relevant memories found.</div>
          )}
          {!loading && hasItems && items.map((item, idx) => (
            <div key={idx} style={styles.item}>
              <div style={styles.itemHeader}>
                <span style={styles.bankBadge}>
                  {item.bank.replace('hydraflow-', '').replace(/-/g, ' ').toUpperCase()}
                </span>
                {item.relevance_score > 0 && (
                  <span style={styles.score}>
                    {(item.relevance_score * 100).toFixed(0)}%
                  </span>
                )}
              </div>
              <div style={styles.content}>{item.content}</div>
              {item.context && (
                <div style={styles.context}>{item.context}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const styles = {
  container: {
    borderTop: `1px solid ${theme.border}`,
    marginTop: 8,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '8px 0',
    cursor: 'pointer',
    userSelect: 'none',
  },
  headerLabel: {
    fontSize: 12,
    fontWeight: 600,
    color: theme.textMuted,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  countBadge: {
    fontSize: 10,
    fontWeight: 700,
    padding: '1px 6px',
    borderRadius: 8,
    background: theme.purpleSubtle,
    color: theme.purple,
  },
  arrow: {
    fontSize: 12,
    color: theme.textMuted,
    marginLeft: 'auto',
  },
  body: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    paddingBottom: 8,
  },
  loading: {
    fontSize: 12,
    color: theme.textMuted,
    padding: '8px 0',
  },
  error: {
    fontSize: 12,
    color: theme.red,
    padding: '4px 8px',
    background: theme.redSubtle,
    borderRadius: 4,
  },
  empty: {
    fontSize: 12,
    color: theme.textMuted,
    padding: '4px 0',
  },
  item: {
    padding: 8,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
  },
  itemHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  bankBadge: {
    fontSize: 9,
    fontWeight: 700,
    padding: '1px 6px',
    borderRadius: 4,
    background: theme.purpleSubtle,
    color: theme.purple,
    letterSpacing: '0.5px',
  },
  score: {
    fontSize: 10,
    color: theme.textMuted,
  },
  content: {
    fontSize: 12,
    color: theme.text,
    lineHeight: 1.4,
    whiteSpace: 'pre-wrap',
  },
  context: {
    fontSize: 11,
    color: theme.textMuted,
    marginTop: 4,
    fontStyle: 'italic',
  },
}
