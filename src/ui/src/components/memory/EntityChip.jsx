import React from 'react'
import { theme } from '../../theme'

const TYPE_STYLES = {
  issue: { background: theme.accentSubtle, color: theme.accent, border: theme.accent },
  pr: { background: theme.purpleSubtle, color: theme.purple, border: theme.purple },
  category: { background: theme.surfaceInset, color: theme.textMuted, border: theme.border },
  pattern: { background: theme.surfaceInset, color: theme.textMuted, border: theme.border },
}

function renderLabel(type, value, label) {
  if (label) return label
  if (type === 'issue') return `#${value}`
  if (type === 'pr') return `PR #${value}`
  return String(value)
}

export function EntityChip({ type, value, label, onFocusEntity }) {
  const palette = TYPE_STYLES[type] || TYPE_STYLES.category

  const handleClick = (e) => {
    e.stopPropagation()
    if (onFocusEntity) onFocusEntity({ type, value })
  }

  const handleKey = (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      handleClick(e)
    }
  }

  return (
    <span
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={handleKey}
      data-testid={`entity-chip-${type}-${value}`}
      style={{
        display: 'inline-block',
        fontSize: 11,
        fontWeight: 600,
        padding: '1px 8px',
        borderRadius: 10,
        cursor: 'pointer',
        userSelect: 'none',
        background: palette.background,
        color: palette.color,
        border: `1px solid ${palette.border}`,
        letterSpacing: '0.3px',
      }}
    >
      {renderLabel(type, value, label)}
    </span>
  )
}
