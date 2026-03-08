import React, { useCallback, useEffect, useState } from 'react'
import { useHydraFlow } from '../context/HydraFlowContext'
import { theme } from '../theme'

export function RegisterRepoDialog({ isOpen, onClose }) {
  const { addRepoBySlug, addRepoByPath } = useHydraFlow()
  const [slug, setSlug] = useState('')
  const [path, setPath] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!isOpen) {
      setSlug('')
      setPath('')
      setError('')
      setSubmitting(false)
      return
    }
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, onClose])

  const handleSubmit = useCallback(async (event) => {
    event.preventDefault()
    if (submitting) return
    const trimmedSlug = slug.trim()
    const trimmedPath = path.trim()
    if (!trimmedSlug && !trimmedPath) {
      setError('Enter a GitHub slug or repo path')
      return
    }
    setSubmitting(true)
    setError('')
    let result
    if (trimmedSlug) {
      result = await addRepoBySlug(trimmedSlug)
    } else {
      result = await addRepoByPath(trimmedPath)
    }
    setSubmitting(false)
    if (!result?.ok) {
      setError(result?.error || 'Registration failed')
      return
    }
    onClose?.()
  }, [slug, path, submitting, addRepoBySlug, addRepoByPath, onClose])

  if (!isOpen) return null

  return (
    <div style={styles.overlay} onClick={(e) => { if (e.target === e.currentTarget) onClose?.() }} data-testid="register-repo-overlay">
      <div style={styles.card}>
        <div style={styles.cardHeader}>
          <span style={styles.title}>Register Repo</span>
          <button type="button" style={styles.closeBtn} onClick={onClose} aria-label="Close register repo dialog">×</button>
        </div>
        <p style={styles.subtitle}>
          Provide a GitHub slug (owner/repo) to start an existing repo,
          or point to a local path to register it with the supervisor.
        </p>
        <form onSubmit={handleSubmit}>
          <label style={styles.label} htmlFor="register-slug">GitHub slug</label>
          <input
            id="register-slug"
            type="text"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="owner/repo"
            style={styles.input}
            autoFocus
          />
          <div style={styles.orDivider}>or</div>
          <label style={styles.label} htmlFor="register-path">Filesystem path</label>
          <input
            id="register-path"
            type="text"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="/Users/me/projects/repo"
            style={styles.input}
          />
          {error && <div style={styles.error}>{error}</div>}
          <div style={styles.actions}>
            <button type="button" onClick={onClose} style={styles.cancelBtn}>Cancel</button>
            <button
              type="submit"
              style={!slug.trim() && !path.trim() ? styles.submitDisabled : styles.submitBtn}
              disabled={submitting || (!slug.trim() && !path.trim())}
              data-testid="register-submit"
            >
              {submitting ? 'Registering…' : 'Register Repo'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

const styles = {
  overlay: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.65)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
  },
  card: {
    width: 420,
    background: theme.surface,
    borderRadius: 12,
    border: `1px solid ${theme.border}`,
    padding: 20,
    boxShadow: '0 12px 32px rgba(0,0,0,0.45)',
  },
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  title: {
    fontSize: 16,
    fontWeight: 700,
    color: theme.textBright,
  },
  closeBtn: {
    border: 'none',
    background: 'transparent',
    fontSize: 20,
    color: theme.textMuted,
    cursor: 'pointer',
  },
  subtitle: {
    fontSize: 12,
    color: theme.textMuted,
    marginBottom: 12,
  },
  label: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.textMuted,
    display: 'block',
    marginBottom: 4,
  },
  input: {
    width: '100%',
    boxSizing: 'border-box',
    padding: '8px 10px',
    borderRadius: 6,
    border: `1px solid ${theme.border}`,
    background: theme.bg,
    color: theme.text,
    fontSize: 12,
    marginBottom: 12,
  },
  orDivider: {
    textTransform: 'uppercase',
    fontSize: 10,
    color: theme.textMuted,
    textAlign: 'center',
    marginBottom: 12,
  },
  error: {
    color: theme.red,
    fontSize: 11,
    marginBottom: 12,
  },
  actions: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: 12,
  },
  cancelBtn: {
    border: `1px solid ${theme.border}`,
    background: 'transparent',
    color: theme.text,
    borderRadius: 6,
    padding: '6px 12px',
    cursor: 'pointer',
  },
  submitBtn: {
    border: 'none',
    background: theme.accent,
    color: theme.bg,
    borderRadius: 6,
    padding: '6px 16px',
    fontWeight: 700,
    cursor: 'pointer',
  },
  submitDisabled: {
    border: 'none',
    background: theme.surfaceInset,
    color: theme.textMuted,
    borderRadius: 6,
    padding: '6px 16px',
    fontWeight: 700,
    cursor: 'not-allowed',
  },
}
