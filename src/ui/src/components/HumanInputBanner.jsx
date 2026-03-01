import React, { useState } from 'react'
import { theme } from '../theme'

export function HumanInputBanner({ requests, onSubmit }) {
  const [answer, setAnswer] = useState('')
  const entries = Object.entries(requests)

  if (entries.length === 0) return null

  const [issueNum, question] = entries[0]

  const handleSubmit = () => {
    if (!answer.trim()) return
    onSubmit(issueNum, answer.trim())
    setAnswer('')
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') handleSubmit()
  }

  return (
    <div style={styles.banner}>
      <span style={styles.question}>Issue #{issueNum}: {question}</span>
      <input
        style={styles.input}
        type="text"
        placeholder="Type your response..."
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        onKeyDown={handleKeyDown}
      />
      <button style={styles.button} onClick={handleSubmit}>Send</button>
    </div>
  )
}

const styles = {
  banner: {
    display: 'flex',
    padding: '12px 16px',
    background: theme.yellowSubtle,
    borderBottom: `2px solid ${theme.yellow}`,
    alignItems: 'center',
    gap: 12,
  },
  question: { flex: 1, color: theme.yellow, fontWeight: 600, fontSize: 13 },
  input: {
    flex: 2,
    padding: '6px 12px',
    background: theme.bg,
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    color: theme.text,
    fontFamily: 'inherit',
    fontSize: 12,
  },
  button: {
    padding: '6px 16px',
    background: theme.yellow,
    color: theme.bg,
    border: 'none',
    borderRadius: 6,
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: 'inherit',
  },
}
