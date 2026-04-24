import React, { useEffect, useState } from 'react'
import { theme } from '../../theme'

/**
 * Per-issue cost waterfall visualisation (§4.11p2 Task 13).
 *
 * Two modes:
 *   (1) Controlled — pass a `payload` prop (the response body of
 *       `/api/diagnostics/issue/{issue}/waterfall`) and this component
 *       renders it verbatim. Parents that already fetched the waterfall
 *       use this path.
 *   (2) Self-fetching — pass `issueNumber` and the component fetches
 *       `/api/diagnostics/issue/{issueNumber}/waterfall` itself. This
 *       matches the Task-13 spec where the component takes an
 *       `issueNumber` prop.
 *
 * The payload shape (from Plan 6b-1):
 *   { issue, title, labels, total: {cost_usd, tokens_in, tokens_out,
 *                                  wall_clock_seconds, ...},
 *     phases: [{ phase, cost_usd, tokens_in, tokens_out,
 *                wall_clock_seconds, actions }],
 *     missing_phases: [] }
 */

function fmtUsd(n) {
  const num = Number(n) || 0
  return `$${num.toFixed(4)}`
}

function fmtSeconds(n) {
  const num = Number(n) || 0
  if (num < 60) return `${Math.round(num)}s`
  const m = Math.floor(num / 60)
  const s = Math.round(num % 60)
  return `${m}m ${s}s`
}

export function WaterfallView({ payload, issueNumber }) {
  const [fetched, setFetched] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  // Self-fetch mode — only when parent did not supply `payload` and an
  // `issueNumber` prop is present.
  useEffect(() => {
    if (payload !== undefined) return
    if (!issueNumber) return
    let cancelled = false
    setLoading(true)
    setError(null)
    fetch(`/api/diagnostics/issue/${encodeURIComponent(issueNumber)}/waterfall`)
      .then((r) => {
        if (!r.ok) throw new Error(`waterfall ${r.status}`)
        return r.json()
      })
      .then((body) => {
        if (!cancelled) setFetched(body)
      })
      .catch((err) => {
        if (!cancelled) setError(err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [payload, issueNumber])

  const effective = payload !== undefined ? payload : fetched

  if (error) {
    return <div style={styles.error}>Failed to load waterfall: {String(error)}</div>
  }
  if (loading && !effective) {
    return <div style={styles.empty}>Loading waterfall…</div>
  }
  if (!effective) {
    return (
      <div style={styles.empty}>
        Select an issue to view its cost waterfall.
      </div>
    )
  }

  const phases = Array.isArray(effective.phases) ? effective.phases : []
  if (phases.length === 0) {
    return <div style={styles.empty}>No telemetry for this issue.</div>
  }

  const maxCost = Math.max(...phases.map((p) => Number(p.cost_usd) || 0), 0.0001)
  const total = effective.total || {}
  const missing = Array.isArray(effective.missing_phases) ? effective.missing_phases : []

  return (
    <div style={styles.wrap}>
      <div style={styles.title}>
        Issue #{effective.issue}
        {effective.title ? ` — ${effective.title}` : ''}
      </div>
      <div style={styles.total}>
        Total: {fmtUsd(total.cost_usd)} · tokens in{' '}
        {Number(total.tokens_in || 0).toLocaleString()} · tokens out{' '}
        {Number(total.tokens_out || 0).toLocaleString()} · wall{' '}
        {fmtSeconds(total.wall_clock_seconds)}
      </div>

      <div style={styles.bars} role="list">
        {phases.map((p) => {
          const cost = Number(p.cost_usd) || 0
          const pct = (cost / maxCost) * 100
          return (
            <div key={p.phase} style={styles.barRow} role="listitem">
              <div style={styles.phaseLabel}>{p.phase}</div>
              <div style={styles.track}>
                <div style={{ ...styles.bar, width: `${pct}%` }} />
              </div>
              <div style={styles.costLabel}>{fmtUsd(cost)}</div>
              <div style={styles.wallLabel}>{fmtSeconds(p.wall_clock_seconds)}</div>
            </div>
          )
        })}
      </div>

      {missing.length > 0 && (
        <div style={styles.missing}>
          Missing: {missing.join(', ')}
        </div>
      )}
    </div>
  )
}

const styles = {
  wrap: {
    background: theme.surfaceInset,
    borderRadius: 8,
    padding: 16,
  },
  title: {
    fontSize: 14,
    fontWeight: 600,
    color: theme.textBright,
    marginBottom: 4,
  },
  total: {
    fontSize: 12,
    color: theme.textMuted,
    marginBottom: 12,
  },
  bars: {
    display: 'grid',
    gap: 6,
  },
  barRow: {
    display: 'grid',
    gridTemplateColumns: '100px 1fr 90px 70px',
    alignItems: 'center',
    gap: 8,
    fontSize: 12,
  },
  phaseLabel: {
    color: theme.text,
    textTransform: 'capitalize',
  },
  track: {
    height: 12,
    background: theme.surface,
    borderRadius: 4,
    overflow: 'hidden',
  },
  bar: {
    height: '100%',
    background: theme.accent,
    borderRadius: 4,
  },
  costLabel: {
    textAlign: 'right',
    color: theme.text,
    fontFamily: 'monospace',
  },
  wallLabel: {
    textAlign: 'right',
    color: theme.textMuted,
    fontFamily: 'monospace',
  },
  missing: {
    marginTop: 12,
    fontSize: 11,
    color: theme.textMuted,
  },
  empty: {
    padding: 24,
    textAlign: 'center',
    color: theme.textMuted,
    fontSize: 12,
    background: theme.surfaceInset,
    borderRadius: 8,
  },
  error: {
    padding: 16,
    color: theme.red,
    fontSize: 12,
    background: theme.surfaceInset,
    borderRadius: 8,
  },
}
