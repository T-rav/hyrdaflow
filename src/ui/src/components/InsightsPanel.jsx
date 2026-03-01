import React, { useState, useEffect } from 'react'
import { theme } from '../theme'
import { useHydraFlow } from '../context/HydraFlowContext'
import { HarnessInsightsPanel } from './HarnessInsightsPanel'

const SECTIONS = [
  { key: 'harness', label: 'Failure Patterns' },
  { key: 'reviews', label: 'Review Feedback' },
  { key: 'retrospective', label: 'Retrospective' },
  { key: 'memories', label: 'Learnings' },
]

// ---------------------------------------------------------------------------
// Shared bar component
// ---------------------------------------------------------------------------

function InsightBar({ label, count, maxCount, color }) {
  const pct = maxCount > 0 ? (count / maxCount) * 100 : 0
  return (
    <div style={styles.barRow}>
      <div style={styles.barLabel}>{label}</div>
      <div style={styles.barTrack}>
        <div style={{ ...styles.barFill, width: `${pct}%`, background: color || theme.accent }} />
      </div>
      <div style={styles.barCount}>{count}</div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Generic fetch + poll hook
// ---------------------------------------------------------------------------

function usePolledData(url, intervalMs = 30000) {
  const { config } = useHydraFlow()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const cacheKey = `hydraflow:${url}:${config?.repo || 'default'}`

  useEffect(() => {
    let cancelled = false
    let hasCachedData = false

    try {
      const raw = localStorage.getItem(cacheKey)
      if (raw) {
        const parsed = JSON.parse(raw)
        if (parsed && typeof parsed === 'object') {
          hasCachedData = true
          setData(parsed)
          setLoading(false)
        }
      }
    } catch {
      // Ignore malformed cache
    }

    async function fetchData() {
      try {
        const resp = await fetch(url)
        if (resp.ok && !cancelled) {
          const payload = await resp.json()
          setData(payload)
          try {
            localStorage.setItem(cacheKey, JSON.stringify(payload))
          } catch {
            // Ignore storage write errors
          }
        }
      } catch {
        // Silently fail
      } finally {
        if (!cancelled && !hasCachedData) setLoading(false)
      }
    }
    fetchData()
    const interval = setInterval(fetchData, intervalMs)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [cacheKey, url, intervalMs])

  return { data, loading }
}

// ---------------------------------------------------------------------------
// Review Feedback sub-section
// ---------------------------------------------------------------------------

const VERDICT_COLORS = {
  approve: theme.green,
  'request-changes': theme.orange,
  comment: theme.yellow,
}

const REVIEW_CATEGORY_LABELS = {
  missing_tests: 'Missing Tests',
  type_annotations: 'Type Annotations',
  security: 'Security',
  naming: 'Naming',
  edge_cases: 'Edge Cases',
  error_handling: 'Error Handling',
  code_quality: 'Code Quality',
  lint_format: 'Lint / Format',
}

function ReviewFeedbackSection() {
  const { data, loading } = usePolledData('/api/review-insights')

  if (loading) return <div style={styles.empty}>Loading review insights...</div>
  if (!data || data.total_reviews === 0) return <div style={styles.empty}>No review data yet.</div>

  const verdictCounts = data.verdict_counts || {}
  const maxVerdict = Math.max(...Object.values(verdictCounts), 1)
  const categoryCounts = data.category_counts || {}
  const maxCat = Math.max(...Object.values(categoryCounts), 1)
  const patterns = data.patterns || []
  const fixRate = data.total_reviews > 0
    ? ((data.fixes_made_count / data.total_reviews) * 100).toFixed(0)
    : '0'

  return (
    <div style={styles.sectionContainer}>
      <div style={styles.header}>
        <span style={styles.totalBadge}>{data.total_reviews}</span>
        <span style={styles.headerText}>reviews tracked</span>
        <span style={styles.fixRatePill}>{fixRate}% needed fixes</span>
      </div>

      <div style={styles.section}>
        <div style={styles.sectionTitle}>Verdict Distribution</div>
        {Object.entries(verdictCounts)
          .sort((a, b) => b[1] - a[1])
          .map(([verdict, count]) => (
            <InsightBar
              key={verdict}
              label={verdict.replace(/_/g, ' ')}
              count={count}
              maxCount={maxVerdict}
              color={VERDICT_COLORS[verdict] || theme.accent}
            />
          ))}
      </div>

      {Object.keys(categoryCounts).length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Feedback Categories</div>
          {Object.entries(categoryCounts)
            .sort((a, b) => b[1] - a[1])
            .map(([cat, count]) => (
              <InsightBar
                key={cat}
                label={REVIEW_CATEGORY_LABELS[cat] || cat.replace(/_/g, ' ')}
                count={count}
                maxCount={maxCat}
                color={theme.orange}
              />
            ))}
        </div>
      )}

      {patterns.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Recurring Patterns</div>
          {patterns.map((p, i) => (
            <PatternCard key={i} pattern={p} />
          ))}
        </div>
      )}

      {data.proposed_categories && data.proposed_categories.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Filed Proposals</div>
          <div style={styles.tagCloud}>
            {data.proposed_categories.map((p, i) => (
              <span key={i} style={styles.proposedTag}>{p}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function PatternCard({ pattern }) {
  const [expanded, setExpanded] = useState(false)
  const label = REVIEW_CATEGORY_LABELS[pattern.category] || pattern.category

  return (
    <div style={styles.patternCard}>
      <div style={styles.patternHeader} onClick={() => setExpanded(!expanded)}>
        <span style={styles.patternDot} />
        <span style={styles.patternTitle}>{label}</span>
        <span style={styles.patternCount}>{pattern.count}x</span>
        <span style={styles.expandIcon}>{expanded ? '\u25B4' : '\u25BE'}</span>
      </div>
      {expanded && pattern.evidence && (
        <div style={styles.patternBody}>
          {pattern.evidence.map((e, i) => (
            <div key={i} style={styles.evidenceItem}>
              #{e.issue_number}
              {e.pr_number > 0 && ` (PR #${e.pr_number})`}
              {e.summary && `: ${e.summary.substring(0, 80)}`}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Retrospective sub-section
// ---------------------------------------------------------------------------

function RetrospectiveSection() {
  const { data, loading } = usePolledData('/api/retrospectives')

  if (loading) return <div style={styles.empty}>Loading retrospective data...</div>
  if (!data || data.total_entries === 0) return <div style={styles.empty}>No retrospective data yet.</div>

  const verdictCounts = data.verdict_counts || {}
  const maxVerdict = Math.max(...Object.values(verdictCounts), 1)

  return (
    <div style={styles.sectionContainer}>
      <div style={styles.header}>
        <span style={styles.totalBadge}>{data.total_entries}</span>
        <span style={styles.headerText}>retrospective entries</span>
      </div>

      <div style={styles.statsGrid}>
        <StatBox label="Plan Accuracy" value={`${data.avg_plan_accuracy}%`} />
        <StatBox label="Avg Quality Rounds" value={data.avg_quality_fix_rounds} />
        <StatBox label="Avg CI Rounds" value={data.avg_ci_fix_rounds} />
        <StatBox label="Avg Duration" value={formatDuration(data.avg_duration_seconds)} />
        <StatBox label="Reviewer Fix Rate" value={`${(data.reviewer_fix_rate * 100).toFixed(0)}%`} />
      </div>

      {Object.keys(verdictCounts).length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Review Verdicts</div>
          {Object.entries(verdictCounts)
            .sort((a, b) => b[1] - a[1])
            .map(([verdict, count]) => (
              <InsightBar
                key={verdict}
                label={verdict.replace(/_/g, ' ')}
                count={count}
                maxCount={maxVerdict}
                color={VERDICT_COLORS[verdict] || theme.accent}
              />
            ))}
        </div>
      )}

      {data.entries && data.entries.length > 0 && (
        <div style={styles.section}>
          <div style={styles.sectionTitle}>Recent Entries</div>
          <div style={styles.tableContainer}>
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>Issue</th>
                  <th style={styles.th}>PR</th>
                  <th style={styles.th}>Accuracy</th>
                  <th style={styles.th}>Quality</th>
                  <th style={styles.th}>CI</th>
                  <th style={styles.th}>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {[...data.entries].reverse().map((e, i) => (
                  <tr key={i}>
                    <td style={styles.td}>#{e.issue_number}</td>
                    <td style={styles.td}>#{e.pr_number}</td>
                    <td style={styles.td}>{e.plan_accuracy_pct}%</td>
                    <td style={styles.td}>{e.quality_fix_rounds}</td>
                    <td style={styles.td}>{e.ci_fix_rounds}</td>
                    <td style={styles.td}>{String(e.review_verdict).replace(/_/g, ' ')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function StatBox({ label, value }) {
  return (
    <div style={styles.statBox}>
      <div style={styles.statValue}>{value}</div>
      <div style={styles.statLabel}>{label}</div>
    </div>
  )
}

function formatDuration(seconds) {
  if (!seconds || seconds === 0) return '0s'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  if (m < 60) return s > 0 ? `${m}m ${s}s` : `${m}m`
  const h = Math.floor(m / 60)
  const rm = m % 60
  return rm > 0 ? `${h}h ${rm}m` : `${h}h`
}

// ---------------------------------------------------------------------------
// Learnings sub-section: collapsible inner section
// ---------------------------------------------------------------------------

function LearningsSubSection({ title, defaultExpanded, children }) {
  const [expanded, setExpanded] = useState(defaultExpanded ?? false)
  return (
    <div style={styles.subSection}>
      <div style={styles.subSectionHeader} onClick={() => setExpanded(!expanded)}>
        <span style={styles.subSectionTitle}>{title}</span>
        <span style={styles.expandIcon}>{expanded ? '\u25B4' : '\u25BE'}</span>
      </div>
      {expanded && <div style={styles.subSectionBody}>{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Troubleshooting pattern card
// ---------------------------------------------------------------------------

function TroubleshootingCard({ pattern }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div style={styles.patternCard}>
      <div style={styles.patternHeader} onClick={() => setExpanded(!expanded)}>
        <span style={styles.patternDot} />
        <span style={styles.patternTitle}>{pattern.pattern_name}</span>
        <span style={styles.langTag}>{pattern.language}</span>
        <span style={styles.patternCount}>{pattern.frequency}x</span>
        <span style={styles.expandIcon}>{expanded ? '\u25B4' : '\u25BE'}</span>
      </div>
      {expanded && (
        <div style={styles.patternBody}>
          <div style={styles.tsDetail}>
            <span style={styles.tsDetailLabel}>Cause:</span> {pattern.description}
          </div>
          <div style={styles.tsDetail}>
            <span style={styles.tsDetailLabel}>Fix:</span> {pattern.fix_strategy}
          </div>
          {pattern.source_issues && pattern.source_issues.length > 0 && (
            <div style={styles.tsDetail}>
              <span style={styles.tsDetailLabel}>Issues:</span>{' '}
              {pattern.source_issues.map((n) => `#${n}`).join(', ')}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Troubleshooting sub-section
// ---------------------------------------------------------------------------

function TroubleshootingSubSection() {
  const { data, loading } = usePolledData('/api/troubleshooting')

  if (loading) return <div style={styles.empty}>Loading troubleshooting patterns...</div>
  if (!data || data.total_patterns === 0) {
    return <div style={styles.empty}>No troubleshooting patterns recorded yet.</div>
  }

  return (
    <div style={styles.sectionContainer}>
      <div style={styles.header}>
        <span style={styles.totalBadge}>{data.total_patterns}</span>
        <span style={styles.headerText}>patterns learned</span>
      </div>
      {(data.patterns || []).map((p) => (
        <TroubleshootingCard key={`${p.language}:${p.pattern_name}`} pattern={p} />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Learnings section (wrapper with three sub-sections)
// ---------------------------------------------------------------------------

function LearningsSection() {
  const { data, loading } = usePolledData('/api/memories')
  const [memoryFilter, setMemoryFilter] = useState('')

  if (loading) return <div style={styles.empty}>Loading learnings...</div>
  if (!data || data.total_items === 0) return <div style={styles.empty}>No learnings recorded yet.</div>

  const curated = data.curated || {}
  const hasCurated =
    curated.overview ||
    (curated.architecture && curated.architecture.length > 0) ||
    (curated.key_services && curated.key_services.length > 0) ||
    (curated.standards && curated.standards.length > 0)

  const filterLower = memoryFilter.toLowerCase()
  const filteredItems = (data.items || []).filter((item) => {
    if (!filterLower) return true
    return (
      String(item.issue_number).includes(filterLower) ||
      (item.learning && item.learning.toLowerCase().includes(filterLower))
    )
  })

  return (
    <div style={styles.sectionContainer}>
      <div style={styles.header}>
        <span style={styles.totalBadge}>{data.total_items}</span>
        <span style={styles.headerText}>memory items</span>
        {data.digest_chars > 0 && (
          <span style={styles.digestPill}>{Math.round(data.digest_chars / 1000)}k chars in digest</span>
        )}
      </div>

      {hasCurated && (
        <LearningsSubSection title="Curated Knowledge" defaultExpanded>
          {curated.overview && (
            <div style={styles.section}>
              <div style={styles.sectionTitle}>Project Overview</div>
              <div style={styles.overviewText}>{curated.overview}</div>
            </div>
          )}

          {curated.architecture && curated.architecture.length > 0 && (
            <div style={styles.section}>
              <div style={styles.sectionTitle}>Architecture Notes</div>
              {curated.architecture.map((note, i) => (
                <div key={i} style={styles.learningItem}>{note}</div>
              ))}
            </div>
          )}

          {curated.key_services && curated.key_services.length > 0 && (
            <div style={styles.section}>
              <div style={styles.sectionTitle}>Key Services</div>
              <div style={styles.tagCloud}>
                {curated.key_services.map((svc, i) => (
                  <span key={i} style={styles.serviceTag}>{svc}</span>
                ))}
              </div>
            </div>
          )}

          {curated.standards && curated.standards.length > 0 && (
            <div style={styles.section}>
              <div style={styles.sectionTitle}>Standards</div>
              {curated.standards.map((std, i) => (
                <div key={i} style={styles.learningItem}>{std}</div>
              ))}
            </div>
          )}
        </LearningsSubSection>
      )}

      <LearningsSubSection title="Memory Items" defaultExpanded={false}>
        <div style={styles.section}>
          <input
            type="text"
            placeholder="Filter by issue # or text..."
            value={memoryFilter}
            onChange={(e) => setMemoryFilter(e.target.value)}
            style={styles.filterInput}
          />
          {filteredItems.length > 0 ? (
            [...filteredItems].reverse().map((item, i) => (
              <div key={i} style={styles.memoryCard}>
                <span style={styles.memoryIssue}>#{item.issue_number}</span>
                <span style={styles.memoryText}>{item.learning}</span>
              </div>
            ))
          ) : (
            <div style={styles.empty}>
              {memoryFilter ? 'No items match filter.' : 'No memory items yet.'}
            </div>
          )}
        </div>
      </LearningsSubSection>

      <LearningsSubSection title="Troubleshooting Patterns" defaultExpanded={false}>
        <TroubleshootingSubSection />
      </LearningsSubSection>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main InsightsPanel
// ---------------------------------------------------------------------------

const SECTION_COMPONENTS = {
  harness: HarnessInsightsPanel,
  reviews: ReviewFeedbackSection,
  retrospective: RetrospectiveSection,
  memories: LearningsSection,
}

function InsightsSection({ label, sectionKey, expanded, onToggle }) {
  const Component = SECTION_COMPONENTS[sectionKey]
  return (
    <div style={styles.insightsCard}>
      <div style={styles.insightsCardHeader} onClick={onToggle}>
        <span style={styles.insightsCardTitle}>{label}</span>
        <span style={styles.expandIcon}>{expanded ? '\u25B4' : '\u25BE'}</span>
      </div>
      {expanded && (
        <div style={styles.insightsCardBody}>
          <Component />
        </div>
      )}
    </div>
  )
}

export function InsightsPanel() {
  const [expandedSections, setExpandedSections] = useState({ harness: true })

  const toggle = (key) => {
    setExpandedSections(prev => ({ ...prev, [key]: !prev[key] }))
  }

  return (
    <div style={styles.scrollContent}>
      {SECTIONS.map(s => (
        <InsightsSection
          key={s.key}
          label={s.label}
          sectionKey={s.key}
          expanded={!!expandedSections[s.key]}
          onToggle={() => toggle(s.key)}
        />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = {
  scrollContent: {
    flex: 1,
    overflowY: 'auto',
    padding: 20,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  insightsCard: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    overflow: 'hidden',
  },
  insightsCardHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 16px',
    cursor: 'pointer',
    transition: 'background 0.15s',
  },
  insightsCardTitle: {
    fontSize: 13,
    fontWeight: 600,
    color: theme.textBright,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  insightsCardBody: {
    borderTop: `1px solid ${theme.border}`,
    padding: 16,
  },
  sectionContainer: {
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
  fixRatePill: {
    fontSize: 11,
    color: theme.orange,
    border: `1px solid ${theme.orange}`,
    borderRadius: 6,
    padding: '1px 6px',
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
  proposedTag: {
    fontSize: 10,
    color: theme.green,
    background: theme.greenSubtle,
    border: `1px solid ${theme.green}`,
    borderRadius: 12,
    padding: '2px 8px',
  },
  patternCard: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    overflow: 'hidden',
  },
  patternHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '8px 12px',
    cursor: 'pointer',
    transition: 'background 0.15s',
  },
  patternDot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.orange,
    flexShrink: 0,
  },
  patternTitle: {
    fontSize: 13,
    color: theme.text,
    flex: 1,
  },
  patternCount: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.orange,
  },
  expandIcon: {
    fontSize: 10,
    color: theme.textMuted,
  },
  patternBody: {
    padding: '8px 12px 12px',
    borderTop: `1px solid ${theme.border}`,
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
  statsGrid: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 12,
  },
  statBox: {
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: '8px 16px',
    minWidth: 100,
  },
  statValue: {
    fontSize: 18,
    fontWeight: 700,
    color: theme.textBright,
  },
  statLabel: {
    fontSize: 11,
    color: theme.textMuted,
    marginTop: 2,
  },
  tableContainer: {
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
    borderBottom: `1px solid ${theme.border}`,
    color: theme.textMuted,
    fontWeight: 600,
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: '0.3px',
  },
  td: {
    padding: '6px 8px',
    borderBottom: `1px solid ${theme.border}`,
    color: theme.text,
  },
  digestPill: {
    fontSize: 11,
    color: theme.accent,
    border: `1px solid ${theme.accent}`,
    borderRadius: 6,
    padding: '1px 6px',
  },
  overviewText: {
    fontSize: 12,
    color: theme.text,
    lineHeight: 1.5,
  },
  learningItem: {
    fontSize: 12,
    color: theme.text,
    paddingLeft: 12,
    borderLeft: `2px solid ${theme.border}`,
    lineHeight: 1.5,
  },
  serviceTag: {
    fontSize: 11,
    color: theme.text,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 12,
    padding: '2px 10px',
  },
  memoryCard: {
    display: 'flex',
    gap: 8,
    padding: '6px 0',
    borderBottom: `1px solid ${theme.border}`,
    alignItems: 'flex-start',
  },
  memoryIssue: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.accent,
    flexShrink: 0,
    minWidth: 48,
  },
  memoryText: {
    fontSize: 12,
    color: theme.text,
    lineHeight: 1.4,
  },
  subSection: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    overflow: 'hidden',
  },
  subSectionHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '8px 12px',
    cursor: 'pointer',
    transition: 'background 0.15s',
  },
  subSectionTitle: {
    fontSize: 12,
    fontWeight: 600,
    color: theme.textBright,
    letterSpacing: '0.3px',
  },
  subSectionBody: {
    borderTop: `1px solid ${theme.border}`,
    padding: 12,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  filterInput: {
    width: '100%',
    padding: '6px 10px',
    fontSize: 12,
    color: theme.text,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    outline: 'none',
    boxSizing: 'border-box',
    marginBottom: 8,
  },
  langTag: {
    fontSize: 10,
    color: theme.accent,
    background: theme.accentSubtle,
    border: `1px solid ${theme.accent}`,
    borderRadius: 12,
    padding: '1px 6px',
    flexShrink: 0,
  },
  tsDetail: {
    fontSize: 12,
    color: theme.text,
    lineHeight: 1.5,
    paddingLeft: 12,
    borderLeft: `2px solid ${theme.border}`,
  },
  tsDetailLabel: {
    fontWeight: 600,
    color: theme.textMuted,
  },
}

