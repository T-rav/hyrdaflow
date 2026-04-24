import React, { useMemo, useState } from 'react'
import { theme } from '../../theme'

/**
 * Per-loop cost dashboard table for the Factory Cost tab (§4.11p2 Task 12).
 *
 * Consumes rows from `/api/diagnostics/loops/cost?range=<r>`. Columns are
 * sortable — click a header to toggle ascending/descending on that key.
 * Rows whose `tick_cost_avg_usd` is ≥ 2× the prior period's average are
 * highlighted in red, surfacing cost spikes at a glance. An inline-SVG
 * sparkline visualises recent per-tick cost trend when the payload
 * includes `sparkline_points`.
 */

const COLUMNS = [
  { key: 'loop', label: 'Loop', numeric: false },
  { key: 'cost_usd', label: 'Cost (USD)', numeric: true, digits: 4 },
  { key: 'llm_calls', label: 'LLM Calls', numeric: true, digits: 0 },
  { key: 'ticks', label: 'Ticks', numeric: true, digits: 0 },
  { key: 'tick_cost_avg_usd', label: 'Avg $/Tick', numeric: true, digits: 4 },
  { key: 'wall_clock_seconds', label: 'Wall (s)', numeric: true, digits: 0 },
]

function isSpike(row) {
  const cur = Number(row && row.tick_cost_avg_usd) || 0
  const prev = Number(row && row.tick_cost_avg_usd_prev_period) || 0
  return prev > 0 && cur >= 2 * prev
}

function compareRows(a, b, key, dir) {
  const av = a ? a[key] : undefined
  const bv = b ? b[key] : undefined
  const aNum = typeof av === 'number'
  const bNum = typeof bv === 'number'
  let delta
  if (aNum && bNum) {
    delta = av - bv
  } else {
    delta = String(av ?? '').localeCompare(String(bv ?? ''))
  }
  return dir === 'asc' ? delta : -delta
}

function fmtCell(value, col) {
  if (!col.numeric) return value ?? ''
  const num = Number(value) || 0
  if (col.digits > 0) {
    return num.toLocaleString(undefined, {
      minimumFractionDigits: Math.min(col.digits, 2),
      maximumFractionDigits: col.digits,
    })
  }
  return num.toLocaleString(undefined, { maximumFractionDigits: 0 })
}

function Sparkline({ points, name }) {
  if (!Array.isArray(points) || points.length === 0) return null
  const w = 120
  const h = 24
  const max = Math.max(...points, 0.0001)
  const step = points.length > 1 ? w / (points.length - 1) : 0
  const coords = points
    .map((v, i) => `${(i * step).toFixed(1)},${(h - (Number(v) / max) * h).toFixed(1)}`)
    .join(' ')
  return (
    <svg
      data-testid={`sparkline-${name}`}
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      style={{ display: 'block' }}
    >
      <polyline
        fill="none"
        stroke={theme.accent}
        strokeWidth="1.5"
        points={coords}
      />
    </svg>
  )
}

export function PerLoopCostTable({ rows, onRowClick }) {
  const [sortKey, setSortKey] = useState('cost_usd')
  const [sortDir, setSortDir] = useState('desc')

  const handleHeaderClick = (key) => {
    if (key === sortKey) {
      setSortDir((prev) => (prev === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const sorted = useMemo(() => {
    if (!Array.isArray(rows) || rows.length === 0) return []
    const copy = [...rows]
    copy.sort((a, b) => compareRows(a, b, sortKey, sortDir))
    return copy
  }, [rows, sortKey, sortDir])

  if (!rows || rows.length === 0) {
    return <div style={styles.empty}>No loop cost data in range</div>
  }

  const arrow = sortDir === 'desc' ? ' ▼' : ' ▲'

  return (
    <div style={styles.container}>
      <table style={styles.table}>
        <thead>
          <tr>
            {COLUMNS.map((c) => (
              <th
                key={c.key}
                scope="col"
                style={{
                  ...styles.th,
                  ...(c.numeric ? styles.thRight : {}),
                }}
                onClick={() => handleHeaderClick(c.key)}
              >
                {c.label}
                {sortKey === c.key ? arrow : ''}
              </th>
            ))}
            <th scope="col" style={styles.th}>Trend</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const spike = isSpike(row)
            return (
              <tr
                key={row.loop}
                data-testid="per-loop-row"
                data-loop={row.loop}
                data-spike={String(spike)}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                style={{
                  ...styles.tr,
                  ...(spike ? styles.trSpike : {}),
                  ...(onRowClick ? styles.trClickable : {}),
                }}
              >
                {COLUMNS.map((c) => (
                  <td
                    key={c.key}
                    style={{
                      ...styles.td,
                      ...(c.numeric ? styles.tdRight : {}),
                      ...(spike && c.key === 'tick_cost_avg_usd'
                        ? styles.tdSpike
                        : {}),
                    }}
                  >
                    {fmtCell(row[c.key], c)}
                  </td>
                ))}
                <td style={styles.td}>
                  <Sparkline points={row.sparkline_points} name={row.loop} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

const styles = {
  container: {
    background: theme.surfaceInset,
    borderRadius: 8,
    padding: 16,
    overflowX: 'auto',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: 12,
  },
  th: {
    textAlign: 'left',
    padding: '6px 8px',
    color: theme.textMuted,
    fontSize: 10,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    borderBottom: `1px solid ${theme.border}`,
    cursor: 'pointer',
    userSelect: 'none',
  },
  thRight: {
    textAlign: 'right',
  },
  tr: {
    transition: 'background 0.15s',
  },
  trClickable: {
    cursor: 'pointer',
  },
  trSpike: {
    background: theme.redSubtle,
  },
  td: {
    padding: '8px',
    color: theme.text,
    borderBottom: `1px solid ${theme.border}`,
  },
  tdRight: {
    textAlign: 'right',
    fontFamily: 'monospace',
  },
  tdSpike: {
    color: theme.red,
    fontWeight: 600,
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
