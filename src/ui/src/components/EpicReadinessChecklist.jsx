import React from 'react'
import { theme } from '../theme'

/**
 * Derives readiness checks from epic data.
 * Returns an array of { label, passed, detail } objects.
 */
export function deriveReadiness(epic) {
  const children = epic.children || []
  const total = epic.total_children || children.length || 0
  const merged = epic.merged_children || 0
  const readiness = epic.readiness || {}

  const approvedCount = readiness.approved_count ?? 0
  const totalCount = readiness.total_count ?? total

  return [
    {
      key: 'implemented',
      label: 'All sub-issues implemented',
      passed: readiness.all_implemented ?? (total > 0 && merged === total),
      detail: `${merged}/${total}`,
    },
    {
      key: 'approved',
      label: 'All PRs approved',
      passed: readiness.all_approved ?? false,
      detail: `${approvedCount}/${totalCount}`,
    },
    {
      key: 'ci',
      label: 'CI passing on all approved PRs',
      passed: readiness.ci_passing ?? false,
    },
    {
      key: 'conflicts',
      label: 'No merge conflicts',
      passed: readiness.no_conflicts ?? false,
      warning: readiness.no_conflicts === false,
    },
    {
      key: 'changelog',
      label: 'Changelog generated',
      passed: readiness.changelog_generated ?? false,
    },
    {
      key: 'version',
      label: 'Version determined',
      passed: readiness.version_determined ?? false,
      detail: readiness.version || '',
    },
  ]
}

/**
 * EpicReadinessChecklist — shows release readiness checks for bundled/bundled_hitl epics.
 *
 * Props:
 *   epic: epic object with readiness data
 */
export function EpicReadinessChecklist({ epic }) {
  const checks = deriveReadiness(epic)
  const allPassed = checks.every(c => c.passed)

  return (
    <div style={styles.container} data-testid="readiness-checklist">
      <div style={styles.header}>
        <span style={styles.title}>Release Readiness</span>
        {allPassed && <span style={styles.readyBadge}>Ready</span>}
      </div>
      <div style={styles.list}>
        {checks.map(check => (
          <div key={check.key} style={styles.item} data-testid={`check-${check.key}`}>
            <span style={check.passed ? styles.checkPass : check.warning ? styles.checkWarn : styles.checkPending}>
              {check.passed ? '✓' : check.warning ? '⚠' : '○'}
            </span>
            <span style={check.passed ? styles.labelPass : styles.labelPending}>
              {check.label}
            </span>
            {check.detail && (
              <span style={styles.detail}>{check.detail}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

const checkBase = {
  fontSize: 12,
  fontWeight: 700,
  width: 16,
  textAlign: 'center',
  flexShrink: 0,
}

const styles = {
  container: {
    padding: '8px 0',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 8,
  },
  title: {
    fontSize: 11,
    fontWeight: 700,
    color: theme.text,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  readyBadge: {
    fontSize: 9,
    fontWeight: 700,
    padding: '1px 8px',
    borderRadius: 8,
    background: theme.greenSubtle,
    color: theme.green,
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  item: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  checkPass: { ...checkBase, color: theme.green },
  checkPending: { ...checkBase, color: theme.textMuted },
  checkWarn: { ...checkBase, color: theme.yellow },
  labelPass: {
    fontSize: 11,
    color: theme.text,
  },
  labelPending: {
    fontSize: 11,
    color: theme.textMuted,
  },
  detail: {
    fontSize: 10,
    color: theme.textMuted,
    marginLeft: 'auto',
  },
}
