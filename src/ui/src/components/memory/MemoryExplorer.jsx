import React, { useEffect, useState, useCallback } from 'react'
import { theme } from '../../theme'
import { useHydraFlow } from '../../context/HydraFlowContext'
import { MemoryTopBar } from './MemoryTopBar'
import { MemorySectionList } from './MemorySectionList'
import { MemoryRelatedPanel } from './MemoryRelatedPanel'

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
          <MemoryRelatedPanel entity={focusedEntity} onClose={clearFocus} />
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
