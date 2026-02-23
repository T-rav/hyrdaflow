import React, { useState, useCallback } from 'react'
import { theme } from '../theme'

export function IntentInput({ connected, orchestratorStatus, onSubmit }) {
  const [text, setText] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const isDisabled = !connected || submitting
  const isRunning = orchestratorStatus === 'running'

  const handleSubmit = useCallback(async () => {
    const trimmed = text.trim()
    if (!trimmed || isDisabled) return
    setSubmitting(true)
    try {
      await onSubmit(trimmed)
      setText('')
    } finally {
      setSubmitting(false)
    }
  }, [text, isDisabled, onSubmit])

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }, [handleSubmit])

  return (
    <div style={styles.container}>
      <div style={styles.inputRow}>
        <input
          style={{
            ...styles.input,
            ...(isDisabled ? styles.inputDisabled : {}),
          }}
          type="text"
          placeholder={
            !connected
              ? 'Disconnected...'
              : !isRunning
                ? 'Type your intent... (start orchestrator to process)'
                : 'What would you like to build?'
          }
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isDisabled}
        />
        <button
          style={{
            ...styles.button,
            ...(isDisabled || !text.trim() ? styles.buttonDisabled : {}),
          }}
          onClick={handleSubmit}
          disabled={isDisabled || !text.trim()}
        >
          {submitting ? 'Sending...' : 'Send'}
        </button>
      </div>
    </div>
  )
}

const styles = {
  container: {
    padding: '8px 12px',
    background: theme.intentBg,
    borderBottom: `1px solid ${theme.border}`,
  },
  inputRow: {
    display: 'flex',
    gap: 8,
    alignItems: 'center',
  },
  input: {
    flex: 1,
    padding: '8px 12px',
    background: theme.surface,
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    color: theme.text,
    fontFamily: 'inherit',
    fontSize: 12,
    outline: 'none',
    transition: 'border-color 0.15s',
  },
  inputDisabled: {
    opacity: 0.5,
    cursor: 'not-allowed',
  },
  button: {
    padding: '8px 16px',
    background: theme.accent,
    color: theme.white,
    border: 'none',
    borderRadius: 6,
    fontWeight: 600,
    fontSize: 12,
    cursor: 'pointer',
    fontFamily: 'inherit',
    transition: 'opacity 0.15s',
    flexShrink: 0,
  },
  buttonDisabled: {
    opacity: 0.4,
    cursor: 'not-allowed',
  },
}
