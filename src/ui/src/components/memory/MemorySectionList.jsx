import React, { useState } from 'react'
import { theme } from '../../theme'
import { InsightBar, StatBox, PatternCard } from './shared/insightsPrimitives'
import { EntityChip } from './EntityChip'
import { HarnessInsightsPanel } from '../HarnessInsightsPanel'

const SECTIONS = [
  { key: 'retrospective', label: 'Retrospectives', bankId: 'hydraflow-retrospectives' },
  { key: 'reviews', label: 'Review Feedback', bankId: 'hydraflow-review-insights' },
  { key: 'troubleshooting', label: 'Troubleshooting Patterns', bankId: 'hydraflow-troubleshooting' },
  { key: 'harness', label: 'Failure Patterns', bankId: 'hydraflow-harness-insights' },
  { key: 'tribal', label: 'Tribal Learnings', bankId: 'hydraflow-tribal' },
]

function textContains(value, query) {
  if (!query) return true
  return String(value || '').toLowerCase().includes(query.toLowerCase())
}

function CollapsibleSection({ label, defaultExpanded = true, children }) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  return (
    <div style={styles.section}>
      <div style={styles.sectionHeader} onClick={() => setExpanded(!expanded)}>
        <span style={styles.sectionLabel}>{label}</span>
        <span style={styles.sectionChevron}>{expanded ? '\u25B4' : '\u25BE'}</span>
      </div>
      {expanded && <div style={styles.sectionBody}>{children}</div>}
    </div>
  )
}

function RetrospectiveView({ data, searchQuery, onFocusEntity }) {
  if (!data || data.total_entries === 0) {
    return <div style={styles.empty}>No retrospective data yet.</div>
  }
  const entries = (data.entries || []).filter(
    e => textContains(e.issue_number, searchQuery)
      || textContains(e.pr_number, searchQuery)
      || textContains(e.review_verdict, searchQuery),
  )
  return (
    <>
      <div style={styles.statsGrid}>
        <StatBox label="Plan Accuracy" value={`${data.avg_plan_accuracy}%`} />
        <StatBox label="Avg Quality Rounds" value={data.avg_quality_fix_rounds} />
        <StatBox label="Avg CI Rounds" value={data.avg_ci_fix_rounds} />
        <StatBox label="Reviewer Fix Rate" value={`${(data.reviewer_fix_rate * 100).toFixed(0)}%`} />
      </div>
      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>Issue</th>
            <th style={styles.th}>PR</th>
            <th style={styles.th}>Accuracy</th>
            <th style={styles.th}>Verdict</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e, i) => (
            <tr key={i}>
              <td style={styles.td}>
                <EntityChip type="issue" value={e.issue_number} onFocusEntity={onFocusEntity} />
              </td>
              <td style={styles.td}>
                {e.pr_number > 0 && (
                  <EntityChip type="pr" value={e.pr_number} onFocusEntity={onFocusEntity} />
                )}
              </td>
              <td style={styles.td}>{e.plan_accuracy_pct}%</td>
              <td style={styles.td}>{String(e.review_verdict).replace(/_/g, ' ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function ReviewFeedbackView({ data, searchQuery, onFocusEntity }) {
  if (!data || data.total_reviews === 0) {
    return <div style={styles.empty}>No review data yet.</div>
  }
  const patterns = (data.patterns || []).filter(
    p => textContains(p.category, searchQuery)
      || textContains(p.category?.replace(/_/g, ' '), searchQuery),
  )
  return (
    <>
      {Object.entries(data.category_counts || {}).map(([cat, count]) => (
        <InsightBar
          key={cat}
          label={cat.replace(/_/g, ' ')}
          count={count}
          maxCount={Math.max(...Object.values(data.category_counts || {}), 1)}
          color={theme.orange}
        />
      ))}
      {patterns.map((p, i) => (
        <PatternCard key={i} title={p.category.replace(/_/g, ' ')} count={p.count} color={theme.orange}>
          {(p.evidence || []).map((e, j) => (
            <div key={j} style={styles.evidenceRow}>
              <EntityChip type="issue" value={e.issue_number} onFocusEntity={onFocusEntity} />
              {e.pr_number > 0 && (
                <EntityChip type="pr" value={e.pr_number} onFocusEntity={onFocusEntity} />
              )}
              {e.summary && <span style={styles.evidenceSummary}>{e.summary.substring(0, 80)}</span>}
            </div>
          ))}
        </PatternCard>
      ))}
    </>
  )
}

function TroubleshootingView({ data, searchQuery, onFocusEntity }) {
  if (!data || data.total_patterns === 0) {
    return <div style={styles.empty}>No troubleshooting patterns recorded yet.</div>
  }
  const patterns = (data.patterns || []).filter(
    p => textContains(p.pattern_name, searchQuery) || textContains(p.language, searchQuery),
  )
  return (
    <>
      {patterns.map((p) => (
        <PatternCard
          key={`${p.language}:${p.pattern_name}`}
          title={`${p.pattern_name} (${p.language})`}
          count={p.frequency}
          color={theme.orange}
        >
          <div>Cause: {p.description}</div>
          <div>Fix: {p.fix_strategy}</div>
          {(p.source_issues || []).length > 0 && (
            <div style={styles.evidenceRow}>
              {p.source_issues.map((n) => (
                <EntityChip key={n} type="issue" value={n} onFocusEntity={onFocusEntity} />
              ))}
            </div>
          )}
        </PatternCard>
      ))}
    </>
  )
}

function TribalView({ data, searchQuery, onFocusEntity }) {
  if (!data || data.total_items === 0) {
    return <div style={styles.empty}>No learnings recorded yet.</div>
  }
  const items = (data.items || []).filter(
    item => textContains(item.learning, searchQuery) || textContains(item.issue_number, searchQuery),
  )
  return (
    <>
      {items.map((item, i) => (
        <div key={i} style={styles.tribalRow}>
          <EntityChip type="issue" value={item.issue_number} onFocusEntity={onFocusEntity} />
          <span style={styles.tribalText}>{item.learning}</span>
        </div>
      ))}
    </>
  )
}

export function MemorySectionList({ data, searchQuery, bankFilter, onFocusEntity }) {
  const visibleSections = SECTIONS.filter(s => !bankFilter || s.bankId === bankFilter)

  return (
    <div style={styles.container}>
      {visibleSections.map((s) => {
        let body = null
        if (s.key === 'retrospective') body = <RetrospectiveView data={data.retrospectives} searchQuery={searchQuery} onFocusEntity={onFocusEntity} />
        else if (s.key === 'reviews') body = <ReviewFeedbackView data={data.reviewInsights} searchQuery={searchQuery} onFocusEntity={onFocusEntity} />
        else if (s.key === 'troubleshooting') body = <TroubleshootingView data={data.troubleshooting} searchQuery={searchQuery} onFocusEntity={onFocusEntity} />
        else if (s.key === 'harness') body = <HarnessInsightsPanel />
        else if (s.key === 'tribal') body = <TribalView data={data.memories} searchQuery={searchQuery} onFocusEntity={onFocusEntity} />
        return (
          <CollapsibleSection key={s.key} label={s.label}>{body}</CollapsibleSection>
        )
      })}
    </div>
  )
}

const styles = {
  container: { flex: 1, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 12 },
  section: { border: `1px solid ${theme.border}`, borderRadius: 8, background: theme.surface, overflow: 'hidden' },
  sectionHeader: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', cursor: 'pointer' },
  sectionLabel: { fontSize: 13, fontWeight: 600, color: theme.textBright, textTransform: 'uppercase', letterSpacing: '0.5px' },
  sectionChevron: { fontSize: 10, color: theme.textMuted },
  sectionBody: { borderTop: `1px solid ${theme.border}`, padding: 16, display: 'flex', flexDirection: 'column', gap: 8 },
  empty: { fontSize: 12, color: theme.textMuted },
  statsGrid: { display: 'flex', flexWrap: 'wrap', gap: 8 },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 12 },
  th: { textAlign: 'left', padding: '6px 8px', borderBottom: `1px solid ${theme.border}`, color: theme.textMuted, fontSize: 11, textTransform: 'uppercase' },
  td: { padding: '6px 8px', borderBottom: `1px solid ${theme.border}`, color: theme.text },
  evidenceRow: { display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' },
  evidenceSummary: { fontSize: 11, color: theme.textMuted },
  tribalRow: { display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', borderBottom: `1px solid ${theme.border}` },
  tribalText: { fontSize: 12, color: theme.text, lineHeight: 1.4 },
}
