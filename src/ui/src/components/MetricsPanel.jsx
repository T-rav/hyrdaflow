import React from 'react'
import { theme } from '../theme'
import { useHydraFlow } from '../context/HydraFlowContext'
import { HarnessInsightsPanel } from './HarnessInsightsPanel'
function TrendIndicator({ current, previous, label, format }) {
  if (previous == null || current == null) return null
  const diff = current - previous
  if (Math.abs(diff) < 0.001) return null

  const isUp = diff > 0
  const arrow = isUp ? '\u2191' : '\u2193'
  const color = isUp ? theme.green : theme.red
  const formatted = format ? format(Math.abs(diff)) : Math.abs(diff)

  return (
    <span style={{ ...styles.trend, color }} title={`Change from previous snapshot`}>
      {arrow} {formatted}
    </span>
  )
}

function StatCard({ label, value, subtle, trend }) {
  return (
    <div style={subtle ? styles.cardSubtle : styles.card}>
      <div style={styles.valueRow}>
        <div style={styles.value}>{value}</div>
        {trend}
      </div>
      <div style={styles.label}>{label}</div>
    </div>
  )
}

function RateCard({ label, value, previousValue }) {
  const pct = (value * 100).toFixed(1)
  return (
    <div style={styles.rateCard}>
      <div style={styles.rateValue}>{pct}%</div>
      <div style={styles.rateLabel}>{label}</div>
      <TrendIndicator
        current={value}
        previous={previousValue}
        format={v => `${(v * 100).toFixed(1)}%`}
      />
    </div>
  )
}

function ThresholdStatus({ thresholds }) {
  if (!thresholds || thresholds.length === 0) return null
  return (
    <div style={styles.thresholdSection}>
      {thresholds.map((t, i) => (
        <div key={i} style={styles.thresholdItem}>
          <span style={styles.thresholdDot} />
          <span style={styles.thresholdText}>
            {t.metric}: {(t.value * 100).toFixed(1)}% (threshold: {(t.threshold * 100).toFixed(1)}%)
          </span>
        </div>
      ))}
    </div>
  )
}

function TimeToMerge({ data }) {
  if (!data || Object.keys(data).length === 0) return null
  const fmt = (s) => {
    if (s < 60) return `${Math.round(s)}s`
    if (s < 3600) return `${Math.round(s / 60)}m`
    return `${(s / 3600).toFixed(1)}h`
  }
  return (
    <div style={styles.row}>
      <StatCard label="Avg Time to Merge" value={fmt(data.avg)} subtle />
      <StatCard label="Median (p50)" value={fmt(data.p50)} subtle />
      <StatCard label="p90" value={fmt(data.p90)} subtle />
    </div>
  )
}

function formatTokens(n) {
  const value = Number.isFinite(n) ? n : 0
  return value.toLocaleString()
}

export function MetricsPanel() {
  const {
    metrics, lifetimeStats, githubMetrics, metricsHistory, stageStatus,
  } = useHydraFlow()
  const sessionTriaged = stageStatus?.triage?.sessionCount || 0
  const sessionPlanned = stageStatus?.plan?.sessionCount || 0
  const sessionImplemented = stageStatus?.implement?.sessionCount || 0
  const sessionReviewed = stageStatus?.review?.sessionCount || 0
  const mergedCount = stageStatus?.merged?.sessionCount || 0
  const github = githubMetrics || {}
  const openByLabel = github.open_by_label || {}
  const lifetime = metrics?.lifetime || lifetimeStats || {}

  const timeToMerge = metrics?.time_to_merge || {}
  const thresholds = metrics?.thresholds || []
  const inferenceLifetime = metrics?.inference_lifetime || {}
  const inferenceSession = metrics?.inference_session || {}

  const hasGithub = githubMetrics !== null && githubMetrics !== undefined
  const hasSession = sessionTriaged > 0 || sessionPlanned > 0 ||
    sessionImplemented > 0 || sessionReviewed > 0 || mergedCount > 0
  const hasLifetime = hasGithub || lifetime.issues_completed > 0 ||
    lifetime.prs_merged > 0

  // Extract history data
  const historyData = metricsHistory || {}
  const snapshots = historyData.snapshots || []
  const current = historyData.current
  const prev = snapshots.length > 0 ? snapshots[snapshots.length - 1] : null

  if (!hasGithub && !hasSession && !hasLifetime && !current) {
    return (
      <div style={styles.container} data-testid="metrics-panel-root">
        <div style={styles.empty}>No metrics data available yet.</div>
      </div>
    )
  }

  return (
    <div style={styles.container} data-testid="metrics-panel-root">
      <h3 style={styles.heading}>Lifetime</h3>
      <div style={styles.row}>
        <StatCard
          label="Issues Completed"
          value={github.total_closed ?? lifetime.issues_completed ?? 0}
          trend={<TrendIndicator
            current={current?.issues_completed}
            previous={prev?.issues_completed}
          />}
        />
        <StatCard
          label="PRs Merged"
          value={github.total_merged ?? lifetime.prs_merged ?? 0}
          trend={<TrendIndicator
            current={current?.prs_merged}
            previous={prev?.prs_merged}
          />}
        />
        {hasGithub && (
          <StatCard
            label="Open Issues"
            value={Object.values(openByLabel).reduce((a, b) => a + b, 0)}
          />
        )}
      </div>

      {(current || prev) && (
        <>
          <h3 style={styles.heading}>Rates</h3>
          <div style={styles.row}>
            <RateCard
              label="Merge Rate"
              value={current?.merge_rate ?? 0}
              previousValue={prev?.merge_rate}
            />
            <RateCard
              label="First-Pass Approval"
              value={current?.first_pass_approval_rate ?? 0}
              previousValue={prev?.first_pass_approval_rate}
            />
            <RateCard
              label="Quality Fix Rate"
              value={current?.quality_fix_rate ?? 0}
              previousValue={prev?.quality_fix_rate}
            />
            <RateCard
              label="HITL Escalation"
              value={current?.hitl_escalation_rate ?? 0}
              previousValue={prev?.hitl_escalation_rate}
            />
          </div>
        </>
      )}

      {thresholds.length > 0 && (
        <>
          <h3 style={styles.heading}>Threshold Alerts</h3>
          <ThresholdStatus thresholds={thresholds} />
        </>
      )}

      {Object.keys(timeToMerge).length > 0 && (
        <>
          <h3 style={styles.heading}>Time to Merge</h3>
          <TimeToMerge data={timeToMerge} />
        </>
      )}

      {hasSession && (
        <>
          <h3 style={styles.heading}>Session</h3>
          <div style={styles.row}>
            <StatCard label="Triaged" value={sessionTriaged || 0} subtle />
            <StatCard label="Planned" value={sessionPlanned || 0} subtle />
            <StatCard label="Implemented" value={sessionImplemented || 0} subtle />
            <StatCard label="Reviewed" value={sessionReviewed || 0} subtle />
            <StatCard label="Merged" value={mergedCount || 0} subtle />
          </div>
        </>
      )}

      <h3 style={styles.heading}>Inference</h3>
      <div style={styles.row}>
        <StatCard
          label="Session Tokens"
          value={formatTokens(inferenceSession.total_tokens || 0)}
          subtle
        />
        <StatCard
          label="Session Calls"
          value={formatTokens(inferenceSession.inference_calls || 0)}
          subtle
        />
        <StatCard
          label="Lifetime Tokens"
          value={formatTokens(inferenceLifetime.total_tokens || 0)}
          subtle
        />
        <StatCard
          label="Lifetime Calls"
          value={formatTokens(inferenceLifetime.inference_calls || 0)}
          subtle
        />
        <StatCard
          label="Session Pruned Chars"
          value={formatTokens(inferenceSession.pruned_chars_total || 0)}
          subtle
        />
        <StatCard
          label="Lifetime Pruned Chars"
          value={formatTokens(inferenceLifetime.pruned_chars_total || 0)}
          subtle
        />
      </div>

      <h3 style={styles.heading}>Harness Insights</h3>
      <HarnessInsightsPanel />

    </div>
  )
}

const styles = {
  container: {
    flex: 1,
    overflowY: 'auto',
    padding: 20,
  },
  heading: {
    fontSize: 16,
    fontWeight: 600,
    color: theme.textBright,
    marginBottom: 16,
    marginTop: 0,
  },
  row: {
    display: 'flex',
    gap: 16,
    marginBottom: 24,
    flexWrap: 'wrap',
  },
  card: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 20,
    background: theme.surface,
    minWidth: 140,
    textAlign: 'center',
  },
  cardSubtle: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 16,
    background: theme.surfaceInset,
    minWidth: 100,
    textAlign: 'center',
  },
  valueRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
  value: {
    fontSize: 32,
    fontWeight: 700,
    color: theme.textBright,
    marginBottom: 4,
  },
  label: {
    fontSize: 12,
    color: theme.textMuted,
    textTransform: 'capitalize',
  },
  trend: {
    fontSize: 12,
    fontWeight: 600,
  },
  empty: {
    fontSize: 13,
    color: theme.textMuted,
    padding: 20,
  },
  rateCard: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 16,
    background: theme.surface,
    minWidth: 120,
    textAlign: 'center',
  },
  rateValue: {
    fontSize: 24,
    fontWeight: 700,
    color: theme.textBright,
    marginBottom: 4,
  },
  rateLabel: {
    fontSize: 11,
    color: theme.textMuted,
    marginBottom: 4,
  },
  thresholdSection: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    marginBottom: 24,
    padding: 16,
    background: theme.surfaceInset,
    borderRadius: 8,
    border: `1px solid ${theme.red}`,
  },
  thresholdItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  thresholdDot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.red,
    flexShrink: 0,
  },
  thresholdText: {
    fontSize: 12,
    color: theme.textBright,
  },
}
