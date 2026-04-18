import React, { useEffect, useState, useCallback } from 'react'
import { theme } from '../../theme'
import { useHydraFlow } from '../../context/HydraFlowContext'
import { MemoryTopBar } from './MemoryTopBar'
import { MemorySectionList } from './MemorySectionList'
import { MemoryRelatedPanel } from './MemoryRelatedPanel'

function deriveClientSideItems(entity, data) {
  if (!entity) return null
  if (entity.type === 'category') {
    const matching = (data.reviewInsights?.patterns || []).filter(p => p.category === entity.value)
    const items = []
    for (const p of matching) {
      for (const e of (p.evidence || [])) {
        items.push({
          bank: 'hydraflow-review-insights',
          content: `#${e.issue_number}${e.pr_number > 0 ? ` (PR #${e.pr_number})` : ''}${e.summary ? `: ${e.summary}` : ''}`,
        })
      }
    }
    return items
  }
  if (entity.type === 'pattern') {
    const matching = (data.troubleshooting?.patterns || []).filter(p => p.pattern_name === entity.value)
    return matching.map(p => ({
      bank: 'hydraflow-troubleshooting',
      content: `${p.pattern_name} (${p.language}) — ${p.description} — Fix: ${p.fix_strategy}`,
      context: (p.source_issues || []).length > 0 ? `Issues: ${p.source_issues.map(n => `#${n}`).join(', ')}` : undefined,
    }))
  }
  return null
}

export function MemoryExplorer() {
  const ctx = useHydraFlow()
  const [banks, setBanks] = useState([])
  const [searchQuery, setSearchQuery] = useState('')
  const [bankFilter, setBankFilter] = useState('')
  const [focusedEntity, setFocusedEntity] = useState(null)

  useEffect(() => {
    fetch('/api/memory/banks')
      .then((r) => {
        if (!r.ok) {
          console.warn('memory/banks fetch non-ok:', r.status)
          return { banks: [] }
        }
        return r.json()
      })
      .then((d) => setBanks(d.banks || []))
      .catch((err) => {
        console.warn('memory/banks fetch failed:', err)
        setBanks([])
      })
  }, [])

  const clearFocus = useCallback(() => setFocusedEntity(null), [])

  useEffect(() => {
    if (!focusedEntity) return
    const onKey = (e) => {
      if (e.key === 'Escape') clearFocus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [focusedEntity, clearFocus])

  const data = {
    memories: ctx.memories,
    retrospectives: ctx.retrospectives,
    reviewInsights: ctx.reviewInsights,
    troubleshooting: ctx.troubleshooting,
    harnessInsights: ctx.harnessInsights,
  }

  return (
    <div style={styles.root} data-testid="memory-explorer">
      <MemoryTopBar
        banks={banks}
        searchQuery={searchQuery}
        bankFilter={bankFilter}
        focusedEntity={focusedEntity}
        onSearchChange={setSearchQuery}
        onBankFilterChange={setBankFilter}
        onClearFocus={clearFocus}
      />
      <div style={styles.panes}>
        <MemorySectionList
          data={data}
          searchQuery={searchQuery}
          bankFilter={bankFilter}
          onFocusEntity={setFocusedEntity}
        />
        {focusedEntity && (
          <MemoryRelatedPanel
            entity={focusedEntity}
            onClose={clearFocus}
            clientSideItems={deriveClientSideItems(focusedEntity, data)}
          />
        )}
      </div>
    </div>
  )
}

const styles = {
  root: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    background: theme.bg,
  },
  panes: {
    flex: 1,
    display: 'flex',
    overflow: 'hidden',
  },
}
