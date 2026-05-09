import React, { useState } from 'react'
import { theme } from '../../theme'
import { DomainView } from './DomainView'
import { GraphView } from './GraphView'
import { DetailPanel } from './DetailPanel'
import { ArticlesView } from './ArticlesView'
import { MaintenanceView } from './MaintenanceView'

const SUBTABS = [
  { id: 'domain', label: 'Domain' },
  { id: 'graph', label: 'Graph' },
  { id: 'articles', label: 'Articles' },
  { id: 'maintenance', label: 'Maintenance' },
]

const KINDS = [
  'runner',
  'service',
  'port',
  'adapter',
  'aggregate',
  'entity',
  'value_object',
  'domain_event',
  'loop',
  'bounded_context',
  'invariant',
  'policy',
]
const CONTEXTS = ['builder', 'caretaker', 'ai-dev-team', 'shared-kernel', 'adrs']
const CONFIDENCES = ['accepted', 'proposed', 'deprecated']

function GraphFilterBar({ filters, onChange }) {
  const styles = {
    bar: {
      display: 'flex',
      gap: 12,
      alignItems: 'center',
      padding: '8px 16px',
      borderBottom: `1px solid ${theme.border}`,
      background: theme.surface,
      flexWrap: 'wrap',
      fontSize: 12,
    },
    label: {
      color: theme.textMuted,
      textTransform: 'uppercase',
      letterSpacing: 0.5,
      fontSize: 10,
    },
    select: {
      background: theme.surfaceInset,
      color: theme.text,
      border: `1px solid ${theme.border}`,
      borderRadius: 3,
      padding: '2px 6px',
      fontSize: 12,
    },
  }
  return (
    <div style={styles.bar}>
      <span style={styles.label}>Kind</span>
      <select
        aria-label="Kind"
        style={styles.select}
        value={filters.kind}
        onChange={(e) => onChange({ ...filters, kind: e.target.value })}
      >
        <option value="">All</option>
        {KINDS.map((k) => (
          <option key={k} value={k}>
            {k}
          </option>
        ))}
      </select>
      <span style={styles.label}>Context</span>
      <select
        aria-label="Context"
        style={styles.select}
        value={filters.context}
        onChange={(e) => onChange({ ...filters, context: e.target.value })}
      >
        <option value="">All</option>
        {CONTEXTS.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
      <span style={styles.label}>Confidence</span>
      <select
        aria-label="Confidence"
        style={styles.select}
        value={filters.confidence}
        onChange={(e) => onChange({ ...filters, confidence: e.target.value })}
      >
        <option value="">All</option>
        {CONFIDENCES.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
    </div>
  )
}

export function AtlasExplorer() {
  const [activeSubtab, setActiveSubtab] = useState('domain')
  const [selectedNodeId, setSelectedNodeId] = useState(null)
  const [filters, setFilters] = useState({
    kind: '',
    context: '',
    confidence: '',
  })

  const styles = {
    root: {
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      background: theme.bg,
      color: theme.text,
      minHeight: 0,
    },
    tabBar: {
      display: 'flex',
      gap: 4,
      padding: '8px 16px',
      borderBottom: `1px solid ${theme.border}`,
      background: theme.surface,
    },
    tab: (isActive) => ({
      padding: '4px 12px',
      borderRadius: 3,
      border: 'none',
      cursor: 'pointer',
      background: isActive ? theme.surfaceInset : 'transparent',
      color: isActive ? theme.textBright : theme.textMuted,
      fontSize: 13,
    }),
    content: {
      flex: 1,
      overflow: 'auto',
      minHeight: 0,
      display: 'flex',
      flexDirection: 'column',
    },
    graphRow: { flex: 1, display: 'flex', minHeight: 0 },
    canvasPane: { flex: 1, minWidth: 0, display: 'flex' },
    detailPane: {
      width: '38%',
      minWidth: 280,
      borderLeft: `1px solid ${theme.border}`,
      overflowY: 'auto',
    },
  }

  const isGraphMode = activeSubtab === 'domain' || activeSubtab === 'graph'

  return (
    <div style={styles.root}>
      <div style={styles.tabBar}>
        {SUBTABS.map((t) => (
          <button
            key={t.id}
            type="button"
            style={styles.tab(activeSubtab === t.id)}
            onClick={() => setActiveSubtab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div style={styles.content}>
        {isGraphMode && (
          <GraphFilterBar filters={filters} onChange={setFilters} />
        )}
        {activeSubtab === 'domain' && (
          <div style={styles.graphRow}>
            <div style={styles.canvasPane}>
              <DomainView
                selectedNodeId={selectedNodeId}
                onSelectNode={setSelectedNodeId}
                filters={filters}
              />
            </div>
            <div style={styles.detailPane}>
              <DetailPanel selectedNodeId={selectedNodeId} />
            </div>
          </div>
        )}
        {activeSubtab === 'graph' && (
          <div style={styles.graphRow}>
            <div style={styles.canvasPane}>
              <GraphView
                selectedNodeId={selectedNodeId}
                onSelectNode={setSelectedNodeId}
                filters={filters}
              />
            </div>
            <div style={styles.detailPane}>
              <DetailPanel selectedNodeId={selectedNodeId} />
            </div>
          </div>
        )}
        {activeSubtab === 'articles' && <ArticlesView />}
        {activeSubtab === 'maintenance' && <MaintenanceView />}
      </div>
    </div>
  )
}

export default AtlasExplorer
