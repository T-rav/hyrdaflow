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

function TimeToMerge({ data, dataTestId }) {
  if (!data || Object.keys(data).length === 0) return null
  const fmt = (s) => {
    if (s < 60) return `${Math.round(s)}s`
    if (s < 3600) return `${Math.round(s / 60)}m`
    return `${(s / 3600).toFixed(1)}h`
  }
  return (
    <div className="metrics-grid" data-testid={dataTestId}>
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

function SectionCard({ title, children, fullWidth = false }) {
  const className = fullWidth ? 'metrics-section-card metrics-section-card--full' : 'metrics-section-card'
  return (
    <section className={className}>
      <h3 style={styles.heading}>{title}</h3>
      {children}
    </section>
  )
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
  const lifetimeIssuesCompleted = Number(lifetime.issues_completed ?? 0)
  const lifetimePrsMerged = Number(lifetime.prs_merged ?? 0)
  const githubTotalClosed = Number(github.total_closed ?? 0)
  const githubTotalMerged = Number(github.total_merged ?? 0)
  const githubOpenIssueTotal = Object.values(openByLabel).reduce((a, b) => a + Number(b || 0), 0)

  const timeToMerge = metrics?.time_to_merge || {}
  const thresholds = metrics?.thresholds || []
  const inferenceLifetime = metrics?.inference_lifetime || {}
  const inferenceSession = metrics?.inference_session || {}

  const hasGithub = githubMetrics !== null && githubMetrics !== undefined
  const githubLooksUnavailable = hasGithub
    && githubOpenIssueTotal === 0
    && githubTotalClosed === 0
    && githubTotalMerged === 0
    && (lifetimeIssuesCompleted > 0 || lifetimePrsMerged > 0)
  const useGithubTotals = hasGithub && !githubLooksUnavailable
  const hasSession = sessionTriaged > 0 || sessionPlanned > 0 ||
    sessionImplemented > 0 || sessionReviewed > 0 || mergedCount > 0
  const hasLifetime = useGithubTotals || lifetimeIssuesCompleted > 0 ||
    lifetimePrsMerged > 0

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

  const sections = [
    {
      key: 'lifetime',
      title: 'Lifetime',
      content: (
        <div className="metrics-grid" data-testid="metrics-grid-lifetime">
          <StatCard
            label="Issues Completed"
            value={useGithubTotals ? githubTotalClosed : lifetimeIssuesCompleted}
            trend={<TrendIndicator
              current={current?.issues_completed}
              previous={prev?.issues_completed}
            />}
          />
          <StatCard
            label="PRs Merged"
            value={useGithubTotals ? githubTotalMerged : lifetimePrsMerged}
            trend={<TrendIndicator
              current={current?.prs_merged}
              previous={prev?.prs_merged}
            />}
          />
          {useGithubTotals && (
            <StatCard
              label="Open Issues"
              value={githubOpenIssueTotal}
            />
          )}
        </div>
      ),
      shouldRender: true,
    },
    {
      key: 'rates',
      title: 'Rates',
      content: (
        <div className="metrics-grid" data-testid="metrics-grid-rates">
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
      ),
      shouldRender: Boolean(current || prev),
    },
    {
      key: 'thresholds',
      title: 'Threshold Alerts',
      content: <ThresholdStatus thresholds={thresholds} />,
      shouldRender: thresholds.length > 0,
    },
    {
      key: 'time-to-merge',
      title: 'Time to Merge',
      content: <TimeToMerge data={timeToMerge} dataTestId="metrics-grid-time-to-merge" />,
      shouldRender: Object.keys(timeToMerge).length > 0,
    },
    {
      key: 'session',
      title: 'Session',
      content: (
        <div className="metrics-grid" data-testid="metrics-grid-session">
          <StatCard label="Triaged" value={sessionTriaged || 0} subtle />
          <StatCard label="Planned" value={sessionPlanned || 0} subtle />
          <StatCard label="Implemented" value={sessionImplemented || 0} subtle />
          <StatCard label="Reviewed" value={sessionReviewed || 0} subtle />
          <StatCard label="Merged" value={mergedCount || 0} subtle />
        </div>
      ),
      shouldRender: hasSession,
    },
    {
      key: 'inference',
      title: 'Inference',
      content: (
        <div className="metrics-grid" data-testid="metrics-grid-inference">
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
      ),
      shouldRender: true,
    },
  ]

  const sectionCards = sections
    .filter(section => section.shouldRender)
    .map(section => (
      <SectionCard key={section.key} title={section.title}>
        {section.content}
      </SectionCard>
    ))

  return (
    <div style={styles.container} data-testid="metrics-panel-root">
      <div className="metrics-sections" data-testid="metrics-sections">
        {sectionCards}
        <SectionCard title="Harness Insights" fullWidth>
          <HarnessInsightsPanel />
        </SectionCard>
      </div>
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
  card: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 20,
    background: theme.surface,
    textAlign: 'center',
  },
  cardSubtle: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 16,
    background: theme.surfaceInset,
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
