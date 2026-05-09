import React, { useEffect, useState } from 'react'
import { theme } from '../../theme'

export function TermDetailPanel({ selectedNodeId }) {
  const [term, setTerm] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!selectedNodeId) {
      setTerm(null)
      setError(null)
      return
    }
    let cancelled = false
    fetch(`/api/atlas/terms/${encodeURIComponent(selectedNodeId)}`)
      .then((r) => {
        if (!r.ok) throw new Error(`status ${r.status}`)
        return r.json()
      })
      .then((data) => {
        if (cancelled) return
        setTerm(data)
        setError(null)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err)
        setTerm(null)
      })
    return () => {
      cancelled = true
    }
  }, [selectedNodeId])

  const styles = {
    root: {
      padding: '14px 16px',
      fontSize: 12,
      lineHeight: 1.5,
      color: theme.text,
    },
    hint: { color: theme.textMuted, fontSize: 13 },
    label: {
      color: theme.textMuted,
      fontSize: 10,
      letterSpacing: 0.5,
      textTransform: 'uppercase',
    },
    name: { color: theme.textBright, fontSize: 15, marginTop: 4 },
    rule: {
      border: 'none',
      borderTop: `1px solid ${theme.border}`,
      margin: '12px 0',
    },
    chip: {
      display: 'inline-block',
      padding: '1px 6px',
      marginRight: 4,
      marginBottom: 4,
      borderRadius: 3,
      border: `1px solid ${theme.border}`,
      fontSize: 11,
      color: theme.textMuted,
    },
    edgeRow: { color: theme.text, marginBottom: 2 },
  }

  if (!selectedNodeId) {
    return (
      <div style={styles.root}>
        <div style={styles.hint}>Pick a node in the graph to see details.</div>
      </div>
    )
  }
  if (error) {
    return (
      <div style={styles.root}>
        <div style={styles.hint}>Unable to load term details.</div>
      </div>
    )
  }
  if (!term) {
    return (
      <div style={styles.root}>
        <div style={styles.hint}>Loading…</div>
      </div>
    )
  }

  return (
    <div style={styles.root}>
      <div style={styles.label}>Selected term</div>
      <div style={styles.name}>{term.name}</div>
      <div style={{ color: theme.textMuted }}>
        {term.kind} · {term.bounded_context} · {term.confidence}
      </div>
      <div style={{ marginTop: 6 }}>
        <code style={{ color: theme.accent }}>{term.code_anchor}</code>
      </div>
      <hr style={styles.rule} />
      <div style={styles.label}>Definition</div>
      <p>{term.definition}</p>
      {term.invariants.length > 0 && (
        <>
          <hr style={styles.rule} />
          <div style={styles.label}>Invariants</div>
          <ul style={{ paddingLeft: 18, margin: 0 }}>
            {term.invariants.map((inv, i) => (
              <li key={i}>{inv}</li>
            ))}
          </ul>
        </>
      )}
      {term.aliases.length > 0 && (
        <>
          <hr style={styles.rule} />
          <div style={styles.label}>Aliases</div>
          <div>
            {term.aliases.map((a) => (
              <span key={a} style={styles.chip}>
                {a}
              </span>
            ))}
          </div>
        </>
      )}
      {term.proposed_by && (
        <>
          <hr style={styles.rule} />
          <div style={styles.label}>Provenance</div>
          <div>
            Proposed by{' '}
            <code style={{ color: theme.accent }}>{term.proposed_by}</code>
            {term.proposed_at && <> on {term.proposed_at.split('T')[0]}</>}
          </div>
          {term.proposal_signals && term.proposal_signals.length > 0 && (
            <div style={{ color: theme.textMuted, marginTop: 2 }}>
              signals: {term.proposal_signals.join(', ')}
              {typeof term.proposal_imports_seen === 'number' && (
                <> · imports seen: {term.proposal_imports_seen}</>
              )}
            </div>
          )}
        </>
      )}
      <hr style={styles.rule} />
      <div style={styles.label}>Edges ({term.edges.length})</div>
      {term.edges.length === 0 ? (
        <div style={{ color: theme.textMuted }}>None</div>
      ) : (
        term.edges.map((e, i) => (
          <div key={i} style={styles.edgeRow}>
            →{e.kind}{' '}
            <span style={{ color: theme.textBright }}>
              {e.target_name || e.target_id}
            </span>
          </div>
        ))
      )}
      <hr style={styles.rule} />
      <div style={styles.label}>Evidence ({term.evidence.length})</div>
      {term.evidence.length === 0 ? (
        <div style={{ color: theme.textMuted, fontStyle: 'italic' }}>
          No wiki entries linked. The migration script
          (<code>scripts/migrate_entries_to_term_evidence.py</code>)
          populates this list.
        </div>
      ) : (
        term.evidence.map((id) => (
          <div key={id} style={styles.edgeRow}>
            <code style={{ color: theme.textBright }}>entry-{id}</code>
          </div>
        ))
      )}
    </div>
  )
}

export default TermDetailPanel
