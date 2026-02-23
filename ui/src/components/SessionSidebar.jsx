import React, { useState, useMemo } from 'react'
import { useHydraFlow } from '../context/HydraFlowContext'
import { theme } from '../theme'

export function SessionSidebar() {
  const { sessions, currentSessionId, selectedSessionId, selectSession, deleteSession } = useHydraFlow()
  const [expandedRepos, setExpandedRepos] = useState({})
  const [hoveredSession, setHoveredSession] = useState(null)
  const [hoveredDeleteId, setHoveredDeleteId] = useState(null)

  const repoGroups = useMemo(() => {
    const groups = {}
    for (const s of sessions) {
      ;(groups[s.repo] ??= []).push(s)
    }
    return groups
  }, [sessions])

  const toggleRepo = (repo) => {
    setExpandedRepos(prev => ({ ...prev, [repo]: prev[repo] === false }))
  }

  const handleDelete = (e, sessionId) => {
    e.stopPropagation()
    deleteSession(sessionId)
  }

  const repos = Object.keys(repoGroups)

  // Extract short repo slug (e.g. "org/repo" → "repo")
  const shortRepo = (repo) => {
    const parts = repo.split('/')
    return parts.length > 1 ? parts[parts.length - 1] : repo
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
        {repos.map(repo => {
          const repoSessions = repoGroups[repo]
          const isExpanded = expandedRepos[repo] !== false

          return (
            <div key={repo}>
              <div
                onClick={() => toggleRepo(repo)}
                style={styles.repoHeader}
              >
                <span style={styles.arrow}>{isExpanded ? '▾' : '▸'}</span>
                <span style={styles.repoName}>{repo}</span>
                <span style={styles.repoCount}>{repoSessions.length}</span>
              </div>

              {isExpanded && repoSessions.map(session => {
                const isActive = session.status === 'active'
                const isCurrent = session.id === currentSessionId
                const isSelected = session.id === selectedSessionId
                const isHovered = session.id === hoveredSession
                const issueCount = session.issues_processed?.length ?? 0

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
                        {session.issues_succeeded > 0 && (
                          <span style={styles.successCount}>{session.issues_succeeded}✓</span>
                        )}
                        {session.issues_failed > 0 && (
                          <span style={styles.failCount}>{session.issues_failed}✗</span>
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

        {repos.length === 0 && (
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
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    padding: '8px 12px',
    cursor: 'pointer',
    fontSize: 11,
    fontWeight: 600,
    color: theme.text,
  },
  arrow: {
    fontSize: 9,
    color: theme.textMuted,
    width: 12,
    textAlign: 'center',
  },
  repoName: {
    flex: 1,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  repoCount: {
    fontSize: 9,
    fontWeight: 700,
    borderRadius: 8,
    padding: '1px 6px',
    background: theme.mutedSubtle,
    color: theme.textMuted,
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
    animation: 'pulse 2s infinite',
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
