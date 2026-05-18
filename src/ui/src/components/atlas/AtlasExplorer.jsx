import React, { useEffect, useState } from 'react'
import { theme } from '../../theme'
import { DomainView } from './DomainView'
import { GraphView } from './GraphView'
import { DetailPanel } from './DetailPanel'
import { ArticlesView } from './ArticlesView'
import { MaintenanceView } from './MaintenanceView'
import {
  loadSavedViews,
  saveView,
  deleteSavedView,
} from './atlasSavedViews'

const VALID_SUBTABS = new Set(['domain', 'graph', 'articles', 'maintenance'])

function readDeepLink() {
  if (typeof window === 'undefined') return { sub: 'domain', node: null }
  const params = new URLSearchParams(window.location.search)
  const sub = params.get('atlas_sub')
  const node = params.get('atlas_node')
  return {
    sub: VALID_SUBTABS.has(sub) ? sub : 'domain',
    node: node || null,
  }
}

function writeDeepLink(sub, node) {
  if (typeof window === 'undefined') return
  const params = new URLSearchParams(window.location.search)
  // Only meddle with our own keys; leave the outer ?tab= alone.
  if (sub && sub !== 'domain') params.set('atlas_sub', sub)
  else params.delete('atlas_sub')
  if (node) params.set('atlas_node', node)
  else params.delete('atlas_node')
  const qs = params.toString()
  const next = `${window.location.pathname}${qs ? `?${qs}` : ''}${
    window.location.hash
  }`
  window.history.replaceState({}, '', next)
}

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

function GraphFilterBar({
  filters,
  onChange,
  focusMode,
  onToggleFocus,
  savedViews,
  onSaveView,
  onApplyView,
  onDeleteView,
}) {
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
      <button
        type="button"
        aria-label="Toggle focus mode"
        aria-pressed={focusMode}
        style={{
          ...styles.select,
          cursor: 'pointer',
          background: focusMode ? theme.accent : theme.surfaceInset,
          color: focusMode ? theme.bg : theme.text,
        }}
        onClick={onToggleFocus}
      >
        Focus mode
      </button>
      <span style={styles.label}>View</span>
      <select
        aria-label="Saved view"
        style={styles.select}
        value=""
        onChange={(e) => {
          const v = e.target.value
          if (!v) return
          if (v === '__save__') onSaveView()
          else if (v.startsWith('__delete__:'))
            onDeleteView(v.slice('__delete__:'.length))
          else onApplyView(v)
        }}
      >
        <option value="">Apply view…</option>
        {Object.keys(savedViews).map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
        <option disabled>──────────</option>
        <option value="__save__">Save current as…</option>
        {Object.keys(savedViews).map((name) => (
          <option key={`del-${name}`} value={`__delete__:${name}`}>
            Delete: {name}
          </option>
        ))}
      </select>
    </div>
  )
}

export function AtlasExplorer() {
  const initial = readDeepLink()
  const [activeSubtab, setActiveSubtab] = useState(initial.sub)
  const [selectedNodeId, setSelectedNodeId] = useState(initial.node)
  const [filters, setFilters] = useState({
    kind: '',
    context: '',
    confidence: '',
  })
  const [focusMode, setFocusMode] = useState(false)
  const [savedViews, setSavedViews] = useState(() => loadSavedViews())

  // Sync deep-link state to URL whenever the sub-tab or selection changes.
  useEffect(() => {
    writeDeepLink(activeSubtab, selectedNodeId)
  }, [activeSubtab, selectedNodeId])

  // Esc clears selection. '/' focuses the search input on Articles when
  // active. Both work without modifier keys; ignore when typing in inputs.
  useEffect(() => {
    const onKey = (e) => {
      const t = e.target
      const typing =
        t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')
      if (e.key === 'Escape' && selectedNodeId) {
        setSelectedNodeId(null)
        // Don't preventDefault while typing — let the browser's native
        // "clear input" Esc behavior still fire so users keep both gestures.
        if (!typing) e.preventDefault()
        return
      }
      if (e.key === '/' && !typing && activeSubtab === 'articles') {
        const search = document.querySelector(
          '[data-testid="atlas-articles-view"] input[type="search"]',
        )
        if (search) {
          search.focus()
          e.preventDefault()
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [activeSubtab, selectedNodeId])

  const handleSaveView = () => {
    const name = window.prompt('Save view as:')
    if (!name) return
    const updated = saveView(name, filters)
    setSavedViews(updated)
  }
  const handleApplyView = (name) => {
    const view = savedViews[name]
    if (view) setFilters(view)
  }
  const handleDeleteView = (name) => {
    const updated = deleteSavedView(name)
    setSavedViews(updated)
  }

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
          <GraphFilterBar
            filters={filters}
            onChange={setFilters}
            focusMode={focusMode}
            onToggleFocus={() => setFocusMode((v) => !v)}
            savedViews={savedViews}
            onSaveView={handleSaveView}
            onApplyView={handleApplyView}
            onDeleteView={handleDeleteView}
          />
        )}
        {activeSubtab === 'domain' && (
          <div style={styles.graphRow}>
            <div style={styles.canvasPane}>
              <DomainView
                selectedNodeId={selectedNodeId}
                onSelectNode={setSelectedNodeId}
                filters={filters}
                focusMode={focusMode}
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
                focusMode={focusMode}
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
