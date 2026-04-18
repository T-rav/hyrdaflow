import React from 'react'
import { theme } from '../../theme'

function focusLabel(entity) {
  if (entity.type === 'issue') return `#${entity.value}`
  if (entity.type === 'pr') return `PR #${entity.value}`
  if (entity.type === 'category') return `cat:${entity.value}`
  if (entity.type === 'pattern') return `pat:${entity.value}`
  return String(entity.value)
}

export function MemoryTopBar({
  banks,
  searchQuery,
  bankFilter,
  focusedEntity,
  onSearchChange,
  onBankFilterChange,
  onClearFocus,
}) {
  return (
    <div style={styles.bar} data-testid="memory-top-bar">
      <input
        type="text"
        placeholder="Search memories..."
        value={searchQuery}
        onChange={(e) => onSearchChange(e.target.value)}
        style={styles.search}
        data-testid="memory-search-input"
      />
      <select
        value={bankFilter}
        onChange={(e) => onBankFilterChange(e.target.value)}
        style={styles.bankSelect}
        data-testid="memory-bank-select"
      >
        <option value="">All banks</option>
        {banks.map((b) => (
          <option key={b.id} value={b.id}>{b.name}</option>
        ))}
      </select>
      {focusedEntity && (
        <span style={styles.focusPill} data-testid="memory-focus-pill">
          Focus: {focusLabel(focusedEntity)}
          <button
            style={styles.focusClear}
            onClick={onClearFocus}
            data-testid="memory-focus-clear"
            aria-label="Clear focus"
          >
            ×
          </button>
        </span>
      )}
    </div>
  )
}

const styles = {
  bar: {
    display: 'flex',
    gap: 8,
    alignItems: 'center',
    padding: '12px 16px',
    borderBottom: `1px solid ${theme.border}`,
    background: theme.surface,
  },
  search: {
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
  focusPill: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '4px 10px',
    borderRadius: 14,
    background: theme.accentSubtle,
    color: theme.accent,
    border: `1px solid ${theme.accent}`,
    fontSize: 12,
    fontWeight: 600,
  },
  focusClear: {
    background: 'transparent',
    border: 'none',
    color: theme.accent,
    cursor: 'pointer',
    fontSize: 14,
    padding: 0,
  },
}
