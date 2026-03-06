import React, { useState } from 'react'
import { theme } from '../theme'
import { useHydraFlow } from '../context/HydraFlowContext'

const CATEGORY_LABELS = {
  plan_validation: 'Plan Validation',
  quality_gate: 'Quality Gate',
  review_rejection: 'Review Rejection',
  ci_failure: 'CI Failure',
  hitl_escalation: 'HITL Escalation',
  implementation_error: 'Implementation Error',
}

const CATEGORY_COLORS = {
  plan_validation: theme.purple,
  quality_gate: theme.orange,
  review_rejection: theme.red,
  ci_failure: theme.red,
  hitl_escalation: theme.yellow,
  implementation_error: theme.red,
}

function CategoryBar({ category, count, maxCount }) {
  const pct = maxCount > 0 ? (count / maxCount) * 100 : 0
  const label = CATEGORY_LABELS[category] || category
  const color = CATEGORY_COLORS[category] || theme.accent

  return (
    <div style={styles.barRow}>
      <div style={styles.barLabel}>{label}</div>
      <div style={styles.barTrack}>
        <div style={{ ...styles.barFill, width: `${pct}%`, background: color }} />
      </div>
      <div style={styles.barCount}>{count}</div>
    </div>
  )
}

function SuggestionCard({ suggestion }) {
  const [expanded, setExpanded] = useState(false)
  const label = CATEGORY_LABELS[suggestion.category] || suggestion.category

  return (
    <div style={styles.suggestionCard}>
      <div
        style={styles.suggestionHeader}
        onClick={() => setExpanded(!expanded)}
      >
        <span style={styles.suggestionDot} />
        <span style={styles.suggestionTitle}>{suggestion.description}</span>
        <span style={styles.suggestionCount}>{suggestion.occurrence_count}x</span>
        <span style={styles.expandIcon}>{expanded ? '\u25B4' : '\u25BE'}</span>
      </div>
      {expanded && (
        <div style={styles.suggestionBody}>
          <div style={styles.suggestionMeta}>
            Category: {label}
            {suggestion.subcategory && ` / ${suggestion.subcategory}`}
          </div>
          <div style={styles.suggestionText}>{suggestion.suggestion}</div>
          {suggestion.evidence && suggestion.evidence.length > 0 && (
            <div style={styles.evidenceList}>
              {suggestion.evidence.slice(0, 5).map((e, i) => (
                <div key={i} style={styles.evidenceItem}>
                  #{e.issue_number}
                  {e.pr_number > 0 && ` (PR #${e.pr_number})`}
                  {e.details && `: ${e.details.substring(0, 80)}`}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function HarnessInsightsPanel() {
  const { harnessInsights: data } = useHydraFlow()

  if (!data) {
    return <div style={styles.empty}>Loading harness insights...</div>
  }

  if (data.total_failures === 0) {
    return <div style={styles.empty}>No failure patterns detected yet.</div>
  }

  const catCounts = data.category_counts || {}
  const maxCount = Math.max(...Object.values(catCounts), 1)
  const suggestions = data.suggestions || []

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.totalBadge}>{data.total_failures}</span>
        <span style={styles.headerText}>failures tracked</span>
      </div>

      <div style={styles.section}>
        <div style={styles.sectionTitle}>Failure Categories</div>
        {Object.entries(catCounts)
          .sort((a, b) => b[1] - a[1])
          .map(([cat, count]) => (
            <CategoryBar
              key={cat}
              category={cat}
              count={count}
              maxCount={maxCount}
            />
          ))}
      </div>

      {Object.keys(data.subcategory_counts || {}).length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Subcategories</div>
          <div style={styles.tagCloud}>
            {Object.entries(data.subcategory_counts)
              .sort((a, b) => b[1] - a[1])
              .map(([sub, count]) => (
                <span key={sub} style={styles.tag}>
                  {sub.replace(/_/g, ' ')} ({count})
                </span>
              ))}
          </div>
        </div>
      )}

      {suggestions.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Improvement Suggestions</div>
          {suggestions.map((s, i) => (
            <SuggestionCard key={i} suggestion={s} />
          ))}
        </div>
      )}

      {data.proposed_patterns && data.proposed_patterns.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Filed Proposals</div>
          <div style={styles.proposedList}>
            {data.proposed_patterns.map((p, i) => (
              <span key={i} style={styles.proposedTag}>{p}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
  },
  empty: {
    fontSize: 13,
    color: theme.textMuted,
    padding: '8px 0',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  totalBadge: {
    fontSize: 18,
    fontWeight: 700,
    color: theme.textBright,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: '4px 12px',
  },
  headerText: {
    fontSize: 13,
    color: theme.textMuted,
  },
  section: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  sectionTitle: {
    fontSize: 12,
    fontWeight: 600,
    color: theme.textMuted,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  barRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  barLabel: {
    fontSize: 12,
    color: theme.text,
    width: 140,
    flexShrink: 0,
  },
  barTrack: {
    flex: 1,
    height: 8,
    background: theme.surfaceInset,
    borderRadius: 4,
    overflow: 'hidden',
  },
  barFill: {
    height: '100%',
    borderRadius: 4,
    transition: 'width 0.3s',
  },
  barCount: {
    fontSize: 12,
    fontWeight: 600,
    color: theme.textBright,
    width: 32,
    textAlign: 'right',
    flexShrink: 0,
  },
  tagCloud: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
  },
  tag: {
    fontSize: 11,
    color: theme.text,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 12,
    padding: '2px 10px',
  },
  suggestionCard: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    overflow: 'hidden',
  },
  suggestionHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '8px 12px',
    cursor: 'pointer',
    transition: 'background 0.15s',
  },
  suggestionDot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.orange,
    flexShrink: 0,
  },
  suggestionTitle: {
    fontSize: 13,
    color: theme.text,
    flex: 1,
  },
  suggestionCount: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.orange,
  },
  expandIcon: {
    fontSize: 10,
    color: theme.textMuted,
  },
  suggestionBody: {
    padding: '0 12px 12px',
    borderTop: `1px solid ${theme.border}`,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    paddingTop: 8,
  },
  suggestionMeta: {
    fontSize: 11,
    color: theme.textMuted,
  },
  suggestionText: {
    fontSize: 12,
    color: theme.text,
    lineHeight: 1.5,
  },
  evidenceList: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  evidenceItem: {
    fontSize: 11,
    color: theme.textMuted,
    paddingLeft: 12,
    borderLeft: `2px solid ${theme.border}`,
  },
  proposedList: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
  },
  proposedTag: {
    fontSize: 10,
    color: theme.green,
    background: theme.greenSubtle,
    border: `1px solid ${theme.green}`,
    borderRadius: 12,
    padding: '2px 8px',
  },
}
