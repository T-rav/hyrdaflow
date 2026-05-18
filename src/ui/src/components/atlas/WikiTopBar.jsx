import React from 'react'
import { theme } from '../../theme'

const TOPICS = ['architecture', 'patterns', 'gotchas', 'testing', 'dependencies']
const STATUSES = ['active', 'stale', 'superseded']

export function WikiTopBar({
  repos,
  selectedRepo,
  onRepoChange,
  filters,
  onFiltersChange,
}) {
  const styles = {
    bar: {
      display: 'flex',
      gap: 12,
      alignItems: 'center',
      padding: '10px 16px',
      background: theme.surface,
      color: theme.text,
      flexWrap: 'wrap',
    },
    label: {
      fontSize: 12,
      color: theme.textMuted,
      textTransform: 'uppercase',
      letterSpacing: 0.5,
    },
    select: {
      background: theme.surfaceInset,
      color: theme.text,
      border: `1px solid ${theme.border}`,
      borderRadius: 4,
      padding: '4px 8px',
      fontSize: 13,
      minWidth: 140,
    },
    input: {
      background: theme.surfaceInset,
      color: theme.text,
      border: `1px solid ${theme.border}`,
      borderRadius: 4,
      padding: '4px 8px',
      fontSize: 13,
      flex: 1,
      minWidth: 160,
    },
  }

  const repoValue = selectedRepo
    ? `${selectedRepo.owner}/${selectedRepo.repo}`
    : ''

  const handleRepoChange = (e) => {
    const [owner, repo] = e.target.value.split('/')
    if (owner && repo) {
      onRepoChange({ owner, repo })
    }
  }

  const setFilter = (key, value) => {
    onFiltersChange({ ...filters, [key]: value })
  }

  return (
    <div style={styles.bar}>
      <span style={styles.label}>Repo</span>
      <select
        aria-label="Wiki repo"
        style={styles.select}
        value={repoValue}
        onChange={handleRepoChange}
      >
        <option value="">Select repo…</option>
        {repos.map((r) => (
          <option key={`${r.owner}/${r.repo}`} value={`${r.owner}/${r.repo}`}>
            {r.owner}/{r.repo}
          </option>
        ))}
      </select>

      <span style={styles.label}>Topic</span>
      <select
        aria-label="Topic filter"
        style={styles.select}
        value={filters.topic}
        onChange={(e) => setFilter('topic', e.target.value)}
      >
        <option value="">All topics</option>
        {TOPICS.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>

      <span style={styles.label}>Status</span>
      <select
        aria-label="Status filter"
        style={styles.select}
        value={filters.status}
        onChange={(e) => setFilter('status', e.target.value)}
      >
        <option value="">All statuses</option>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>

      <input
        type="search"
        aria-label="Search entries"
        placeholder="Search…"
        style={styles.input}
        value={filters.q}
        onChange={(e) => setFilter('q', e.target.value)}
      />
    </div>
  )
}

export default WikiTopBar
