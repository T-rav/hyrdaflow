import React, { useEffect, useState } from 'react'
import { theme } from '../../theme'

/**
 * Inline SVG sparkline — renders a polyline from an array of numeric values.
 */
function Sparkline({ values, width = 120, height = 32, color = theme.accent }) {
  if (!values || values.length < 2) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width
      const y = height - ((v - min) / range) * (height - 4) - 2
      return `${x},${y}`
    })
    .join(' ')
  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function MetricCard({ label, points, color, lowerIsBetter }) {
  if (!points || points.length === 0) {
    return (
      <div style={styles.card}>
        <div style={styles.cardLabel}>{label}</div>
        <div style={styles.noData}>No data</div>
      </div>
    )
  }
  const values = points.map((p) => p.value)
  const latest = values[values.length - 1]
  const first = values[0]
  const delta = latest - first
  const improving = lowerIsBetter ? delta < 0 : delta > 0
  const trendColor = delta === 0 ? theme.textMuted : improving ? theme.green : theme.red

  return (
    <div style={styles.card}>
      <div style={styles.cardLabel}>{label}</div>
      <div style={styles.cardValue}>{formatValue(label, latest)}</div>
      <Sparkline values={values} color={color} />
      {values.length > 1 && (
        <div style={{ ...styles.delta, color: trendColor }}>
          {delta > 0 ? '+' : ''}
          {formatValue(label, delta)}
        </div>
      )}
    </div>
  )
}

function formatValue(label, value) {
  if (label.includes('%') || label.includes('Rate')) {
    return `${(value * 100).toFixed(1)}%`
  }
  if (label.includes('Duration')) {
    return `${value.toFixed(0)}s`
  }
  return value.toFixed(1)
}

function CohortComparison({ cohorts }) {
  if (!cohorts) return null
  const { memory_available: avail, memory_unavailable: unavail } = cohorts
  if (avail.count === 0 && unavail.count === 0) return null

  const metrics = [
    { key: 'plan_accuracy_pct', label: 'Plan Accuracy' },
    { key: 'quality_fix_rounds', label: 'Fix Rounds' },
    { key: 'first_pass_rate', label: 'First-Pass Rate' },
  ]

  return (
    <div style={styles.cohortSection}>
      <h4 style={styles.sectionSubtitle}>Memory Impact Attribution</h4>
      <div style={styles.cohortGrid}>
        <div style={styles.cohortHeader} />
        <div style={styles.cohortHeader}>With Memory ({avail.count})</div>
        <div style={styles.cohortHeader}>Without Memory ({unavail.count})</div>
        {metrics.map(({ key, label }) => (
          <React.Fragment key={key}>
            <div style={styles.cohortLabel}>{label}</div>
            <div style={styles.cohortValue}>
              {avail[key] != null ? formatCohortValue(key, avail[key]) : '-'}
            </div>
            <div style={styles.cohortValue}>
              {unavail[key] != null ? formatCohortValue(key, unavail[key]) : '-'}
            </div>
          </React.Fragment>
        ))}
      </div>
    </div>
  )
}

function formatCohortValue(key, value) {
  if (key === 'plan_accuracy_pct') return `${value.toFixed(1)}%`
  if (key === 'first_pass_rate') return `${(value * 100).toFixed(1)}%`
  return value.toFixed(1)
}

function RegressionAlerts({ regressions }) {
  if (!regressions || regressions.length === 0) return null
  return (
    <div style={styles.regressionSection}>
      <h4 style={styles.sectionSubtitle}>Regression Alerts</h4>
      {regressions.map((r, i) => (
        <div key={i} style={styles.regressionItem}>
          <span style={styles.regressionMetric}>{r.metric}</span>
          <span style={styles.regressionDetail}>
            baseline {r.baseline_mean} → recent {r.recent_mean} ({r.deviation_sigma}σ)
          </span>
        </div>
      ))}
    </div>
  )
}

export function FactoryHealthSection() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetch('/api/factory-health/summary')
      .then((r) => r.json())
      .then((d) => {
        if (!cancelled) setData(d)
      })
      .catch((err) => console.error('factory health fetch failed', err))
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (loading && !data) {
    return <div style={styles.loading}>Loading factory health…</div>
  }

  if (!data) return null

  const { rolling_averages: ra, cohorts, regressions } = data

  const metricConfigs = [
    { key: 'plan_accuracy_pct', label: 'Plan Accuracy %', color: theme.accent, lowerIsBetter: false },
    { key: 'first_pass_rate', label: 'First-Pass Rate', color: theme.green, lowerIsBetter: false },
    { key: 'quality_fix_rounds', label: 'Fix Rounds', color: theme.orange, lowerIsBetter: true },
    { key: 'ci_fix_rounds', label: 'CI Fix Rounds', color: theme.yellow, lowerIsBetter: true },
    { key: 'duration_seconds', label: 'Duration (s)', color: theme.purple, lowerIsBetter: true },
  ]

  return (
    <div style={styles.section}>
      <h3 style={styles.sectionTitle}>Factory Health Trends</h3>

      <div style={styles.metricsGrid}>
        {metricConfigs.map(({ key, label, color, lowerIsBetter }) => (
          <MetricCard
            key={key}
            label={label}
            points={ra[key] || []}
            color={color}
            lowerIsBetter={lowerIsBetter}
          />
        ))}
      </div>

      <CohortComparison cohorts={cohorts} />
      <RegressionAlerts regressions={regressions} />
    </div>
  )
}

const styles = {
  section: {
    marginTop: 24,
    marginBottom: 24,
  },
  sectionTitle: {
    color: theme.textBright,
    fontSize: 16,
    fontWeight: 700,
    margin: '0 0 16px 0',
  },
  sectionSubtitle: {
    color: theme.textBright,
    fontSize: 13,
    fontWeight: 600,
    margin: '0 0 8px 0',
  },
  metricsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
    gap: 12,
    marginBottom: 16,
  },
  card: {
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 12,
  },
  cardLabel: {
    color: theme.textMuted,
    fontSize: 11,
    marginBottom: 4,
  },
  cardValue: {
    color: theme.textBright,
    fontSize: 18,
    fontWeight: 700,
    marginBottom: 4,
  },
  delta: {
    fontSize: 11,
    marginTop: 4,
  },
  noData: {
    color: theme.textInactive,
    fontSize: 12,
  },
  loading: {
    color: theme.textMuted,
    fontSize: 12,
    padding: 16,
  },
  cohortSection: {
    marginTop: 16,
  },
  cohortGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr 1fr',
    gap: 8,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 12,
  },
  cohortHeader: {
    color: theme.textMuted,
    fontSize: 11,
    fontWeight: 600,
  },
  cohortLabel: {
    color: theme.text,
    fontSize: 12,
  },
  cohortValue: {
    color: theme.textBright,
    fontSize: 12,
    fontWeight: 600,
  },
  regressionSection: {
    marginTop: 16,
  },
  regressionItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '6px 12px',
    background: theme.redSubtle,
    border: `1px solid ${theme.red}`,
    borderRadius: 6,
    marginBottom: 4,
  },
  regressionMetric: {
    color: theme.red,
    fontSize: 12,
    fontWeight: 600,
  },
  regressionDetail: {
    color: theme.text,
    fontSize: 11,
  },
}
