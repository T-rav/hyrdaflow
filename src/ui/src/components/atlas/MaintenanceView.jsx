import React, { useCallback, useEffect, useState } from 'react'
import { theme } from '../../theme'

export function MaintenanceView() {
  const [status, setStatus] = useState(null)
  const [health, setHealth] = useState(null)
  const [termLoops, setTermLoops] = useState(null)

  const refresh = useCallback(() => {
    fetch('/api/wiki/maintenance/status')
      .then((r) => (r.ok ? r.json() : null))
      .then(setStatus)
      .catch(() => setStatus(null))
    fetch('/api/wiki/health')
      .then((r) => (r.ok ? r.json() : null))
      .then(setHealth)
      .catch(() => setHealth(null))
    fetch('/api/atlas/term-loops/status')
      .then((r) => (r.ok ? r.json() : null))
      .then(setTermLoops)
      .catch(() => setTermLoops(null))
  }, [])

  useEffect(() => {
    refresh()
    const iv = setInterval(refresh, 30_000)
    return () => clearInterval(iv)
  }, [refresh])

  const post = async (path, body = {}) => {
    await fetch(`/api/wiki/admin/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    refresh()
  }

  const styles = {
    root: {
      padding: 16,
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 14,
      color: theme.text,
      fontSize: 12,
      width: '100%',
    },
    card: {
      border: `1px solid ${theme.border}`,
      borderRadius: 4,
      padding: 12,
    },
    label: {
      color: theme.textMuted,
      fontSize: 10,
      letterSpacing: 0.5,
      textTransform: 'uppercase',
    },
    grid: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      rowGap: 4,
      columnGap: 8,
      marginTop: 6,
    },
    btn: {
      background: theme.surface,
      border: `1px solid ${theme.border}`,
      borderRadius: 3,
      padding: '4px 10px',
      color: theme.text,
      cursor: 'pointer',
      fontSize: 12,
    },
    btnRow: { display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap' },
    actions: {
      gridColumn: 'span 2',
      border: `1px solid ${theme.border}`,
      borderRadius: 4,
      padding: 12,
    },
  }

  const queueDepth = status?.queue_depth ?? 0
  const intervalSeconds = status?.interval_seconds ?? '—'
  const autoMerge = String(status?.auto_merge ?? '—')
  const coalesce = String(status?.coalesce ?? '—')
  const prUrl = status?.open_pr_url

  return (
    <div data-testid="atlas-maintenance-view" style={styles.root}>
      <div style={styles.card}>
        <div style={styles.label}>Run status</div>
        <div style={styles.grid}>
          <span style={{ color: theme.textMuted }}>Queue depth</span>
          <span>{queueDepth}</span>
          <span style={{ color: theme.textMuted }}>Open PR</span>
          <span>
            {prUrl ? (
              <a
                href={prUrl}
                target="_blank"
                rel="noreferrer"
                style={{ color: theme.accent }}
              >
                {prUrl.split('/').slice(-2).join('/')}
              </a>
            ) : (
              '—'
            )}
          </span>
          <span style={{ color: theme.textMuted }}>Interval</span>
          <span>{intervalSeconds}s</span>
          <span style={{ color: theme.textMuted }}>Auto-merge</span>
          <span>{autoMerge}</span>
          <span style={{ color: theme.textMuted }}>Coalesce</span>
          <span>{coalesce}</span>
        </div>
        <div style={styles.btnRow}>
          <button type="button" style={styles.btn} onClick={() => post('run-now', {})}>
            Run now
          </button>
        </div>
      </div>

      <div style={styles.card}>
        <div style={styles.label}>Health</div>
        <div style={{ marginTop: 6 }}>
          <div>
            <span style={{ color: theme.textMuted }}>Wiki store: </span>
            {health?.store ?? '—'}
            {typeof health?.repos === 'number' && (
              <span style={{ color: theme.textMuted }}> · {health.repos} repos</span>
            )}
          </div>
          <div>
            <span style={{ color: theme.textMuted }}>Tribal store: </span>
            {health?.tribal ?? '—'}
          </div>
        </div>
      </div>

      <div style={{ ...styles.card, gridColumn: 'span 2' }}>
        <div style={styles.label}>Term loops</div>
        <div
          style={{
            marginTop: 6,
            display: 'grid',
            gridTemplateColumns: '1fr 1fr 1fr',
            gap: 12,
          }}
        >
          {['term_proposer', 'term_pruner', 'edge_proposer'].map((name) => {
            const loop = termLoops?.[name]
            const loopStatus = loop?.status ?? 'unknown'
            const lastRun = loop?.last_run
            const loopPrUrl = loop?.last_pr_url
            const count = loop?.last_action_count
            return (
              <div
                key={name}
                style={{
                  border: `1px solid ${theme.border}`,
                  borderRadius: 3,
                  padding: 8,
                }}
              >
                <div style={{ color: theme.textBright }}>{name}</div>
                <div style={{ color: theme.textMuted, fontSize: 10 }}>
                  status: {loopStatus}
                </div>
                <div style={{ color: theme.textMuted, fontSize: 10 }}>
                  last run: {lastRun ? lastRun.split('T')[0] : '—'}
                </div>
                {loopPrUrl && (
                  <a
                    href={loopPrUrl}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: theme.accent, fontSize: 10 }}
                  >
                    last PR
                  </a>
                )}
                {typeof count === 'number' && (
                  <div style={{ color: theme.textMuted, fontSize: 10 }}>
                    actions: {count}
                  </div>
                )}
              </div>
            )
          })}
        </div>
        <div style={{ color: theme.textMuted, fontSize: 10, marginTop: 6 }}>
          From <code>/api/atlas/term-loops/status</code>. Read-only;
          loops are governed by the System tab toggles.
        </div>
      </div>

      <div style={styles.actions}>
        <div style={styles.label}>Admin actions</div>
        <div style={styles.btnRow}>
          <button
            type="button"
            style={styles.btn}
            onClick={() => post('rebuild-index', { owner: '', repo: '' })}
          >
            Rebuild index
          </button>
          <button
            type="button"
            style={styles.btn}
            onClick={() => post('force-compile', { owner: '', repo: '', topic: '' })}
          >
            Force compile
          </button>
        </div>
        <div style={{ color: theme.textMuted, fontSize: 10, marginTop: 6 }}>
          These actions enqueue a MaintenanceTask onto RepoWikiLoop's queue.
          Owner/repo fields are placeholders in P1 — wired to a form in a follow-up.
        </div>
      </div>
    </div>
  )
}

export default MaintenanceView
