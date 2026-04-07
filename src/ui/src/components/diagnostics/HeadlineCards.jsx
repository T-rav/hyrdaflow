import React from 'react'
import { theme } from '../../theme'

function formatTokens(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`
  return String(n)
}

function formatPercent(n) {
  return `${Math.round(n * 100)}%`
}

export function HeadlineCards({ data, loading }) {
  if (loading) {
    return <div style={styles.loading}>Loading…</div>
  }
  if (!data) {
    return <div style={styles.loading}>No data</div>
  }

  return (
    <div style={styles.row}>
      <Card label="Total Tokens" value={formatTokens(data.total_tokens)} accent={theme.accent} />
      <Card label="Phase Runs" value={String(data.total_runs)} accent={theme.green} />
      <Card label="Cache Hit" value={formatPercent(data.cache_hit_rate)} accent={theme.cyan} />
    </div>
  )
}

function Card({ label, value, accent }) {
  return (
    <div style={{ ...styles.card, borderLeftColor: accent }}>
      <div style={styles.value}>{value}</div>
      <div style={styles.label}>{label}</div>
    </div>
  )
}

const styles = {
  row: {
    display: 'grid',
    gridTemplateColumns: 'repeat(3, 1fr)',
    gap: 16,
    marginBottom: 24,
  },
  card: {
    background: theme.surfaceInset,
    borderLeft: '4px solid',
    borderRadius: 8,
    padding: '16px 20px',
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  value: {
    fontSize: 32,
    fontWeight: 700,
    color: theme.textBright,
  },
  label: {
    fontSize: 11,
    color: theme.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  loading: {
    color: theme.textMuted,
    padding: 16,
  },
}
