import React, { useCallback, useEffect, useState } from 'react'
import { theme } from '../../theme'
import { CostByModelChart } from './CostByModelChart'
import { FactoryCostSummary } from './FactoryCostSummary'
import { PerLoopCostTable } from './PerLoopCostTable'
import { WaterfallView } from './WaterfallView'

/**
 * Factory Cost sub-tab (§4.11p2 Task 14).
 *
 * Composition container that orchestrates the three cost components:
 *   - FactoryCostSummary — top-line 24h KPIs
 *   - PerLoopCostTable   — sortable per-loop rows for the range
 *   - WaterfallView      — per-issue phase waterfall
 *
 * An operator can either click a top-issue link (surfaces expensive
 * issues from `/cost/top-issues`) or type an issue number directly into
 * the control bar to drive the WaterfallView.
 */

export function FactoryCostTab({ range = '7d' }) {
  const [rolling24h, setRolling24h] = useState(null)
  const [rollingError, setRollingError] = useState(null)
  const [topIssues, setTopIssues] = useState([])
  const [loopsCost, setLoopsCost] = useState([])
  const [costByModel, setCostByModel] = useState([])
  const [selectedIssue, setSelectedIssue] = useState(null)
  const [waterfallPayload, setWaterfallPayload] = useState(null)
  const [waterfallError, setWaterfallError] = useState(null)
  const [waterfallInput, setWaterfallInput] = useState('')

  useEffect(() => {
    let cancelled = false
    const q = `?range=${encodeURIComponent(range)}`
    Promise.allSettled([
      fetch('/api/diagnostics/cost/rolling-24h').then((r) => r.json()),
      fetch(`/api/diagnostics/cost/top-issues${q}&limit=10`).then((r) => r.json()),
      fetch(`/api/diagnostics/loops/cost${q}`).then((r) => r.json()),
      fetch(`/api/diagnostics/cost/by-model${q}`).then((r) => r.json()),
    ]).then((results) => {
      if (cancelled) return
      const [rolling, top, loops, byModel] = results
      if (rolling.status === 'fulfilled') {
        setRolling24h(rolling.value)
        setRollingError(null)
      } else {
        setRolling24h(null)
        setRollingError(rolling.reason)
      }
      setTopIssues(
        top.status === 'fulfilled' && Array.isArray(top.value) ? top.value : [],
      )
      setLoopsCost(
        loops.status === 'fulfilled' && Array.isArray(loops.value) ? loops.value : [],
      )
      setCostByModel(
        byModel.status === 'fulfilled' && Array.isArray(byModel.value) ? byModel.value : [],
      )
    })
    return () => {
      cancelled = true
    }
  }, [range])

  const loadWaterfall = useCallback(async (issueNumber) => {
    const n = Number(issueNumber)
    if (!n || !Number.isFinite(n) || n <= 0) {
      setWaterfallError(new Error('Enter a positive issue number'))
      setWaterfallPayload(null)
      return
    }
    setSelectedIssue(n)
    setWaterfallError(null)
    try {
      const r = await fetch(`/api/diagnostics/issue/${n}/waterfall`)
      if (!r.ok) {
        throw new Error(`waterfall ${r.status}`)
      }
      setWaterfallPayload(await r.json())
    } catch (err) {
      setWaterfallError(err)
      setWaterfallPayload(null)
    }
  }, [])

  const handleTopIssueClick = useCallback(
    (row) => {
      setWaterfallInput(String(row.issue))
      loadWaterfall(row.issue)
    },
    [loadWaterfall],
  )

  const handleInputSubmit = (ev) => {
    ev.preventDefault()
    loadWaterfall(waterfallInput.trim())
  }

  return (
    <div style={styles.wrap}>
      <FactoryCostSummary rolling24h={rolling24h} error={rollingError} />

      <section style={styles.section}>
        <h3 style={styles.h3}>Cost by Model ({range})</h3>
        <CostByModelChart rows={costByModel} />
      </section>

      <section style={styles.section}>
        <h3 style={styles.h3}>Per-Loop Cost ({range})</h3>
        <PerLoopCostTable rows={loopsCost} />
      </section>

      <div style={styles.gridTwo}>
        <section style={styles.section}>
          <h3 style={styles.h3}>Top Issues ({range})</h3>
          {topIssues.length === 0 ? (
            <div style={styles.empty}>No issues in range</div>
          ) : (
            <ul style={styles.ul}>
              {topIssues.map((row) => (
                <li key={row.issue} style={styles.li}>
                  <button
                    type="button"
                    style={styles.link}
                    onClick={() => handleTopIssueClick(row)}
                  >
                    #{row.issue}
                  </button>
                  <span style={styles.liMeta}>
                    ${Number(row.cost_usd || 0).toFixed(4)} ·{' '}
                    {Number(row.wall_clock_seconds || 0)}s
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section style={styles.section}>
          <h3 style={styles.h3}>
            Waterfall
            {selectedIssue ? ` — Issue #${selectedIssue}` : ''}
          </h3>
          <form onSubmit={handleInputSubmit} style={styles.form}>
            <input
              type="number"
              min="1"
              placeholder="Issue number"
              value={waterfallInput}
              onChange={(e) => setWaterfallInput(e.target.value)}
              style={styles.input}
            />
            <button type="submit" style={styles.btn}>
              Load
            </button>
          </form>
          {waterfallError ? (
            <div style={styles.error}>{String(waterfallError.message || waterfallError)}</div>
          ) : (
            <WaterfallView payload={waterfallPayload} />
          )}
        </section>
      </div>
    </div>
  )
}

const styles = {
  wrap: {
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
  },
  section: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  gridTwo: {
    display: 'grid',
    gridTemplateColumns: '1fr 2fr',
    gap: 16,
    alignItems: 'flex-start',
  },
  h3: {
    fontSize: 13,
    fontWeight: 600,
    color: theme.textBright,
    margin: 0,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  ul: {
    listStyle: 'none',
    padding: 0,
    margin: 0,
    background: theme.surfaceInset,
    borderRadius: 8,
    overflow: 'hidden',
  },
  li: {
    padding: '6px 12px',
    fontSize: 12,
    display: 'flex',
    gap: 8,
    alignItems: 'center',
    borderBottom: `1px solid ${theme.border}`,
  },
  liMeta: {
    color: theme.textMuted,
    fontFamily: 'monospace',
  },
  link: {
    background: 'transparent',
    border: 'none',
    color: theme.accent,
    cursor: 'pointer',
    padding: 0,
    fontSize: 12,
    textDecoration: 'underline',
    fontFamily: 'inherit',
  },
  form: {
    display: 'flex',
    gap: 8,
    alignItems: 'center',
  },
  input: {
    background: theme.surfaceInset,
    color: theme.text,
    border: `1px solid ${theme.border}`,
    padding: '4px 8px',
    fontSize: 12,
    borderRadius: 4,
    width: 140,
  },
  btn: {
    background: theme.accentSubtle,
    color: theme.textBright,
    border: `1px solid ${theme.border}`,
    padding: '4px 12px',
    fontSize: 12,
    borderRadius: 4,
    cursor: 'pointer',
  },
  empty: {
    padding: 16,
    textAlign: 'center',
    color: theme.textMuted,
    fontSize: 11,
    background: theme.surfaceInset,
    borderRadius: 8,
  },
  error: {
    padding: 12,
    color: theme.red,
    fontSize: 12,
    background: theme.surfaceInset,
    borderRadius: 8,
  },
}
