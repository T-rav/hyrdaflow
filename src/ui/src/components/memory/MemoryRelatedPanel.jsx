import React, { useEffect, useState } from 'react'
import { theme } from '../../theme'

function endpointFor(entity) {
  if (entity.type === 'issue') return `/api/memory/issue/${entity.value}`
  if (entity.type === 'pr') return `/api/memory/pr/${entity.value}`
  return null
}

function titleFor(entity) {
  if (entity.type === 'issue') return `Issue #${entity.value}`
  if (entity.type === 'pr') return `PR #${entity.value}`
  if (entity.type === 'category') return `Category: ${entity.value}`
  if (entity.type === 'pattern') return `Pattern: ${entity.value}`
  return String(entity.value)
}

function groupByBank(items) {
  const groups = new Map()
  for (const item of items) {
    const bank = item.bank || 'unknown'
    if (!groups.has(bank)) groups.set(bank, [])
    groups.get(bank).push(item)
  }
  return Array.from(groups.entries())
}

function bankLabel(bankId) {
  return String(bankId).replace('hydraflow-', '').replace(/-/g, ' ').toUpperCase()
}

export function MemoryRelatedPanel({ entity, onClose, clientSideItems }) {
  const [state, setState] = useState({ loading: false, items: null, error: null })

  useEffect(() => {
    if (!entity) return
    const endpoint = endpointFor(entity)
    if (!endpoint) {
      setState({ loading: false, items: clientSideItems || [], error: null })
      return
    }
    setState({ loading: true, items: null, error: null })
    const controller = new AbortController()
    fetch(endpoint, { signal: controller.signal })
      .then(r => {
        if (!r.ok) throw new Error(`status ${r.status}`)
        return r.json()
      })
      .then(data => {
        setState({ loading: false, items: data.items || [], error: null })
      })
      .catch((err) => {
        if (err.name === 'AbortError') return
        setState({ loading: false, items: null, error: 'Hindsight unavailable' })
      })
    return () => controller.abort()
  }, [entity, clientSideItems])

  if (!entity) return null

  const { loading, items, error } = state
  const grouped = items ? groupByBank(items) : []

  return (
    <aside style={styles.panel} data-testid="memory-related-panel">
      <div style={styles.header}>
        <span style={styles.title}>{titleFor(entity)}</span>
        <button
          style={styles.close}
          onClick={onClose}
          data-testid="related-close"
          aria-label="Close related memories"
        >
          ×
        </button>
      </div>
      {loading && <div style={styles.empty}>Loading related memories…</div>}
      {error && <div style={styles.error}>{error}</div>}
      {!loading && !error && grouped.length === 0 && (
        <div style={styles.empty}>No related memories for {titleFor(entity)}.</div>
      )}
      {!loading && !error && grouped.map(([bank, bankItems]) => (
        <div key={bank} style={styles.bankGroup}>
          <div style={styles.bankLabel}>{bankLabel(bank)}</div>
          {bankItems.map((item, i) => (
            <div key={i} style={styles.item}>
              <div style={styles.itemContent}>{item.content}</div>
              {item.context && <div style={styles.itemContext}>{item.context}</div>}
            </div>
          ))}
        </div>
      ))}
    </aside>
  )
}

const styles = {
  panel: {
    width: 400,
    flexShrink: 0,
    borderLeft: `1px solid ${theme.border}`,
    background: theme.surface,
    overflowY: 'auto',
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderBottom: `1px solid ${theme.border}`,
    paddingBottom: 8,
  },
  title: {
    fontSize: 13,
    fontWeight: 700,
    color: theme.textBright,
  },
  close: {
    fontSize: 18,
    background: 'transparent',
    border: 'none',
    color: theme.textMuted,
    cursor: 'pointer',
    padding: '0 4px',
  },
  error: {
    fontSize: 12,
    color: theme.red,
    padding: '8px 12px',
    background: theme.redSubtle,
    borderRadius: 6,
  },
  empty: {
    fontSize: 12,
    color: theme.textMuted,
  },
  bankGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  bankLabel: {
    fontSize: 10,
    fontWeight: 700,
    color: theme.purple,
    letterSpacing: '0.5px',
  },
  item: {
    padding: 8,
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    background: theme.surfaceInset,
  },
  itemContent: {
    fontSize: 12,
    color: theme.text,
    whiteSpace: 'pre-wrap',
  },
  itemContext: {
    fontSize: 10,
    color: theme.textMuted,
    marginTop: 4,
    fontStyle: 'italic',
  },
}
