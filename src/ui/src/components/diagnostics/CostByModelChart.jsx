import React, { useMemo, useState } from 'react'
import { theme } from '../../theme'

/**
 * Cost-by-model horizontal stacked bar (gap #9 — observability).
 *
 * Consumes rows from `/api/diagnostics/cost/by-model?range=<r>`. Toggles
 * between unit views ($, calls, input tokens, output tokens). Empty data
 * renders a placeholder; the parent owns the range selector.
 */

const UNITS = [
  { key: 'cost_usd', label: '$', tooltipFmt: (v) => `$${Number(v).toFixed(4)}` },
  {
    key: 'calls',
    label: 'Calls',
    tooltipFmt: (v) => Number(v).toLocaleString(),
  },
  {
    key: 'input_tokens',
    label: 'Input tokens',
    tooltipFmt: (v) => Number(v).toLocaleString(),
  },
  {
    key: 'output_tokens',
    label: 'Output tokens',
    tooltipFmt: (v) => Number(v).toLocaleString(),
  },
]

const PALETTE = [
  theme.accent,
  '#a78bfa',
  '#34d399',
  '#fbbf24',
  '#f87171',
  '#60a5fa',
  '#fb923c',
  '#c084fc',
]

function colorFor(idx) {
  return PALETTE[idx % PALETTE.length]
}

export function CostByModelChart({ rows }) {
  const [unitKey, setUnitKey] = useState('cost_usd')
  const unit = UNITS.find((u) => u.key === unitKey) || UNITS[0]

  const segments = useMemo(() => {
    if (!Array.isArray(rows) || rows.length === 0) return []
    const total = rows.reduce((acc, r) => acc + (Number(r[unitKey]) || 0), 0)
    if (total <= 0) return []
    return rows.map((r, i) => {
      const value = Number(r[unitKey]) || 0
      return {
        model: r.model,
        value,
        share: value / total,
        color: colorFor(i),
      }
    })
  }, [rows, unitKey])

  if (!Array.isArray(rows) || rows.length === 0 || segments.length === 0) {
    return (
      <div style={styles.empty}>No model spend data in range</div>
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span data-testid="cost-by-model-unit" style={styles.unitLabel}>
          {unit.label}
        </span>
        <div style={styles.unitButtons}>
          {UNITS.map((u) => (
            <button
              key={u.key}
              type="button"
              onClick={() => setUnitKey(u.key)}
              style={{
                ...styles.unitBtn,
                ...(u.key === unitKey ? styles.unitBtnActive : {}),
              }}
            >
              {u.label}
            </button>
          ))}
        </div>
      </div>

      <div style={styles.bar} role="img" aria-label="Spend share by model">
        {segments.map((s) => (
          <div
            key={s.model}
            data-testid={`seg-${s.model}`}
            title={`${s.model}: ${unit.tooltipFmt(s.value)} (${(s.share * 100).toFixed(1)}%)`}
            style={{
              ...styles.segment,
              width: `${(s.share * 100).toFixed(2)}%`,
              background: s.color,
            }}
          />
        ))}
      </div>

      <ul style={styles.legend}>
        {segments.map((s) => (
          <li key={s.model} style={styles.legendItem}>
            <span
              style={{ ...styles.legendSwatch, background: s.color }}
              aria-hidden="true"
            />
            <span style={styles.legendModel}>{s.model}</span>
            <span style={styles.legendValue}>
              {unit.tooltipFmt(s.value)} · {(s.share * 100).toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    background: theme.surfaceInset,
    borderRadius: 8,
    padding: 16,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
  },
  unitLabel: {
    fontSize: 11,
    color: theme.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  unitButtons: {
    display: 'flex',
    gap: 4,
  },
  unitBtn: {
    background: 'transparent',
    borderWidth: 1,
    borderStyle: 'solid',
    borderColor: theme.border,
    color: theme.textMuted,
    fontSize: 11,
    padding: '2px 8px',
    borderRadius: 4,
    cursor: 'pointer',
  },
  unitBtnActive: {
    background: theme.accentSubtle,
    color: theme.textBright,
    borderColor: theme.accent,
  },
  bar: {
    display: 'flex',
    width: '100%',
    height: 24,
    borderRadius: 4,
    overflow: 'hidden',
    background: theme.border,
  },
  segment: {
    height: '100%',
  },
  legend: {
    listStyle: 'none',
    padding: 0,
    margin: 0,
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
    gap: 4,
    fontSize: 11,
  },
  legendItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  legendSwatch: {
    width: 10,
    height: 10,
    borderRadius: 2,
    flexShrink: 0,
  },
  legendModel: {
    color: theme.text,
    fontFamily: 'monospace',
    flex: 1,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  legendValue: {
    color: theme.textMuted,
    fontFamily: 'monospace',
  },
  empty: {
    padding: 40,
    textAlign: 'center',
    color: theme.textMuted,
    fontSize: 11,
    background: theme.surfaceInset,
    borderRadius: 8,
  },
}
