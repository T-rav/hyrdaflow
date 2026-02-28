import React, { useState, useMemo } from 'react'
import { useHydraFlow } from '../context/HydraFlowContext'
import { theme } from '../theme'
import { PULSE_ANIMATION } from '../constants'

export function SessionSidebar() {
  const {
    sessions,
    currentSessionId,
    selectedSessionId,
    stageStatus,
    selectSession,
    deleteSession,
    addRepoShortcut,
    removeRepoShortcut,
    supervisedRepos = [],
  } = useHydraFlow()
  const [expandedRepos, setExpandedRepos] = useState({})
  const [hoveredSession, setHoveredSession] = useState(null)
  const [hoveredDeleteId, setHoveredDeleteId] = useState(null)

  const shortRepo = (repo) => {
    const parts = (repo || '').split('/')
    return parts.length > 1 ? parts[parts.length - 1] : repo
  }

  const repoEntries = useMemo(() => {
    const entries = new Map()
    const slugIndex = new Map()

    const ensureEntry = (key, slug, displayName) => {
      if (!entries.has(key)) {
        entries.set(key, {
          key,
          slug,
          displayName,
          sessions: [],
          info: null,
        })
        if (slug) slugIndex.set(slug, key)
      }
      return entries.get(key)
    }

    for (const session of sessions) {
      const slug = shortRepo(session.repo)
      const key = slug || session.repo
      const entry = ensureEntry(key, slug, session.repo)
      entry.sessions.push(session)
    }

    for (const repo of supervisedRepos || []) {
      if (!repo) continue
      const slug = repo.slug || shortRepo(repo.path || '')
      let entryKey = (slug && slugIndex.get(slug)) || slug
      let entry = entryKey ? entries.get(entryKey) : undefined
      if (!entry) {
        entryKey = slug || repo.path || repo.slug || `repo-${entries.size + 1}`
        entry = ensureEntry(entryKey, slug, repo.slug || slug || repo.path || entryKey)
      }
      entry.info = repo
      if (slug && !slugIndex.has(slug)) {
        slugIndex.set(slug, entry.key)
      }
      if (!entry.displayName && (repo.slug || repo.path)) {
        entry.displayName = repo.slug || repo.path
      }
    }

    return Array.from(entries.values()).sort((a, b) =>
      (a.displayName || '').localeCompare(b.displayName || '')
    )
  }, [sessions, supervisedRepos])

  const toggleRepo = (repoKey) => {
    setExpandedRepos(prev => ({ ...prev, [repoKey]: prev[repoKey] === false }))
  }

  const handleDelete = (e, sessionId) => {
    e.stopPropagation()
    deleteSession(sessionId)
  }

  const repoIdentifier = (entry) => {
    if (entry.sessions.length > 0) return entry.displayName
    return entry.slug || entry.displayName
  }

  const handleAddRepo = (e, entry) => {
    e.stopPropagation()
    addRepoShortcut?.(repoIdentifier(entry))
  }

  const handleRemoveRepo = (e, entry) => {
    e.stopPropagation()
    removeRepoShortcut?.(repoIdentifier(entry))
  }

  return (
    <div style={styles.sidebar}>
      <div style={styles.header}>
        <span style={styles.headerLabel}>Sessions</span>
        {sessions.length > 0 && (
          <span style={styles.countBadge}>{sessions.length}</span>
        )}
      </div>

      <div
        onClick={() => selectSession(null)}
        style={selectedSessionId === null ? styles.allButtonActive : styles.allButton}
      >
        All
      </div>

      <div style={styles.list}>
        {repoEntries.map(entry => {
          const repoSessions = entry.sessions
          const isExpanded = expandedRepos[entry.key] !== false

          return (
            <div key={entry.key}>
              <div
                onClick={() => toggleRepo(entry.key)}
                style={styles.repoHeader}
              >
                <div style={styles.repoTitle}>
                  <span style={styles.arrow}>{isExpanded ? '▾' : '▸'}</span>
                  <div style={styles.repoText}>
                    <span style={styles.repoName}>{entry.displayName}</span>
                    {entry.info?.path && entry.info.path !== entry.displayName && (
                      <span style={styles.repoSubLabel}>{entry.info.path}</span>
                    )}
                  </div>
                </div>
                <div style={styles.repoMeta}>
                  {entry.info && (
                    <span
                      style={entry.info.running ? styles.repoStatusRunning : styles.repoStatusStopped}
                      title={entry.info.running ? 'Repo is running under hf supervisor' : 'Repo is registered but not running'}
                    >
                      {entry.info.running ? 'RUNNING' : 'STOPPED'}
                    </span>
                  )}
                  <span style={styles.repoCount}>{repoSessions.length}</span>
                </div>
                <div style={styles.repoActions}>
                  <button
                    type="button"
                    aria-label={`Add repo ${entry.displayName}`}
                    title="Add repo"
                    onClick={(e) => handleAddRepo(e, entry)}
                    style={styles.repoActionButton}
                  >
                    +
                  </button>
                  <button
                    type="button"
                    aria-label={`Remove repo ${entry.displayName}`}
                    title="Remove repo"
                    onClick={(e) => handleRemoveRepo(e, entry)}
                    style={styles.repoActionButton}
                  >
                    −
                  </button>
                </div>
              </div>

              {isExpanded && repoSessions.map(session => {
                const isActive = session.status === 'active'
                const isCurrent = session.id === currentSessionId
                const isSelected = session.id === selectedSessionId
                const isHovered = session.id === hoveredSession
                const isLiveSession = isActive && isCurrent
                const liveSucceeded = isLiveSession
                  ? (stageStatus?.workload?.done ?? session.issues_succeeded ?? 0)
                  : (session.issues_succeeded ?? 0)
                const liveFailed = isLiveSession
                  ? (stageStatus?.workload?.failed ?? session.issues_failed ?? 0)
                  : (session.issues_failed ?? 0)
                const issueCount = isLiveSession
                  ? (liveSucceeded + liveFailed)
                  : (session.issues_processed?.length ?? 0)

                let rowStyle = styles.sessionRow
                if (isCurrent && isSelected) rowStyle = sessionRowCurrentSelected
                else if (isCurrent) rowStyle = sessionRowCurrent
                else if (isSelected) rowStyle = sessionRowSelected

                return (
                  <div
                    key={session.id}
                    onClick={() => selectSession(session.id)}
                    onMouseEnter={() => setHoveredSession(session.id)}
                    onMouseLeave={() => setHoveredSession(null)}
                    style={rowStyle}
                  >
                    <span style={isActive ? styles.dotActive : styles.dotCompleted} />
                    <div style={styles.sessionInfo}>
                      <span style={styles.sessionRepo}>{shortRepo(session.repo)}</span>
                      <span style={styles.sessionTime}>
                        {session.started_at ? new Date(session.started_at).toLocaleString() : ''}
                      </span>
                      <div style={styles.sessionMeta}>
                        {issueCount > 0 && (
                          <span style={styles.issuePill}>{issueCount}</span>
                        )}
                        {liveSucceeded > 0 && (
                          <span style={styles.successCount}>{liveSucceeded}✓</span>
                        )}
                        {liveFailed > 0 && (
                          <span style={styles.failCount}>{liveFailed}✗</span>
                        )}
                      </div>
                    </div>
                    {!isActive && isHovered && (
                      <button
                        onClick={(e) => handleDelete(e, session.id)}
                        onMouseEnter={() => setHoveredDeleteId(session.id)}
                        onMouseLeave={() => setHoveredDeleteId(null)}
                        style={hoveredDeleteId === session.id ? deleteButtonHovered : styles.deleteButton}
                        aria-label="Delete session"
                        title="Delete session"
                      >
                        ×
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          )
        })}

        {repoEntries.length === 0 && (
          <div style={styles.empty}>No sessions yet</div>
        )}
      </div>
    </div>
  )
}

const styles = {
  sidebar: {
    width: 280,
    flexShrink: 0,
    borderRight: `1px solid ${theme.border}`,
    background: theme.surface,
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 12px 8px',
    borderBottom: `1px solid ${theme.border}`,
  },
  headerLabel: {
    fontSize: 12,
    fontWeight: 600,
    color: theme.textBright,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  countBadge: {
    fontSize: 10,
    fontWeight: 700,
    borderRadius: 8,
    padding: '1px 6px',
    background: theme.accentSubtle,
    color: theme.accent,
  },
  allButton: {
    padding: '8px 12px',
    fontSize: 11,
    fontWeight: 600,
    color: theme.textMuted,
    cursor: 'pointer',
    borderBottom: `1px solid ${theme.border}`,
    transition: 'background 0.15s',
  },
  allButtonActive: {
    padding: '8px 12px',
    fontSize: 11,
    fontWeight: 600,
    color: theme.accent,
    cursor: 'pointer',
    borderBottom: `1px solid ${theme.border}`,
    background: theme.accentSubtle,
    transition: 'background 0.15s',
  },
  list: {
    flex: 1,
    overflowY: 'auto',
    padding: '4px 0',
  },
  repoHeader: {
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 1fr) auto auto',
    alignItems: 'flex-start',
    gap: 6,
    padding: '8px 12px',
    cursor: 'pointer',
    fontSize: 11,
    fontWeight: 600,
    color: theme.text,
  },
  repoTitle: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: 6,
    minWidth: 0,
  },
  repoText: {
    display: 'flex',
    flexDirection: 'column',
    minWidth: 0,
  },
  repoActions: {
    display: 'flex',
    gap: 4,
    justifyContent: 'flex-end',
  },
  repoActionButton: {
    border: `1px solid ${theme.border}`,
    borderRadius: 4,
    width: 20,
    height: 20,
    fontSize: 12,
    fontWeight: 700,
    background: theme.surfaceAlt ?? theme.surface,
    color: theme.text,
    cursor: 'pointer',
  },
  arrow: {
    fontSize: 9,
    color: theme.textMuted,
    width: 12,
    textAlign: 'center',
  },
  repoName: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  repoSubLabel: {
    fontSize: 10,
    fontWeight: 500,
    color: theme.textMuted,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  repoCount: {
    fontSize: 10,
    fontWeight: 700,
    borderRadius: 8,
    padding: '0 6px',
    background: theme.surfaceAlt ?? theme.surface,
    border: `1px solid ${theme.border}`,
  },
  repoMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
  },
  repoStatusRunning: {
    fontSize: 9,
    fontWeight: 700,
    color: theme.success ?? theme.accent,
    background: theme.successSubtle ?? theme.accentSubtle,
    borderRadius: 6,
    padding: '0 6px',
  },
  repoStatusStopped: {
    fontSize: 9,
    fontWeight: 700,
    color: theme.textMuted,
    background: theme.surfaceAlt ?? theme.surface,
    borderRadius: 6,
    padding: '0 6px',
  },
  sessionRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '6px 12px 6px 28px',
    cursor: 'pointer',
    transition: 'background 0.15s',
    borderLeft: '3px solid transparent',
    position: 'relative',
  },
  dotActive: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.green,
    flexShrink: 0,
    animation: PULSE_ANIMATION,
  },
  dotCompleted: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.textMuted,
    flexShrink: 0,
    opacity: 0.5,
  },
  sessionInfo: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    minWidth: 0,
  },
  sessionRepo: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.textMuted,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  sessionTime: {
    fontSize: 10,
    color: theme.textMuted,
  },
  sessionMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  },
  issuePill: {
    fontSize: 9,
    fontWeight: 700,
    borderRadius: 8,
    padding: '1px 6px',
    background: theme.accentSubtle,
    color: theme.accent,
  },
  successCount: {
    fontSize: 9,
    color: theme.green,
  },
  failCount: {
    fontSize: 9,
    color: theme.red,
  },
  deleteButton: {
    position: 'absolute',
    right: 8,
    top: '50%',
    transform: 'translateY(-50%)',
    background: 'none',
    border: 'none',
    color: theme.textMuted,
    fontSize: 14,
    fontWeight: 700,
    cursor: 'pointer',
    padding: '0 4px',
    lineHeight: 1,
    borderRadius: 4,
    transition: 'color 0.15s, background 0.15s',
    flexShrink: 0,
  },
  empty: {
    padding: '16px 12px',
    fontSize: 11,
    color: theme.textMuted,
    textAlign: 'center',
  },
}

// Pre-computed row style variants (avoids object spread in .map())
const sessionRowSelected = { ...styles.sessionRow, background: theme.accentSubtle }
const sessionRowCurrent = { ...styles.sessionRow, borderLeft: `3px solid ${theme.accent}` }
const sessionRowCurrentSelected = { ...sessionRowCurrent, background: theme.accentSubtle }
const deleteButtonHovered = { ...styles.deleteButton, color: theme.red, background: theme.redSubtle }
