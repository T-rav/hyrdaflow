import React, { useEffect, useState } from 'react'
import { ReactFlow, Background, Controls, MiniMap } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { theme } from '../../theme'
import { useGraphLayout } from './useGraphLayout'

function applyFilters(payload, filters) {
  if (!payload) return payload
  if (!filters || (!filters.kind && !filters.context && !filters.confidence)) {
    return payload
  }
  const safeNodes = Array.isArray(payload.nodes) ? payload.nodes : []
  const keep = (n) => {
    if (n.type === 'adr') {
      // ADRs survive the term-only filters (kind / confidence) since they
      // don't carry those fields. Context filter still applies via 'adrs'.
      if (filters.context && n.parent !== filters.context) return false
      return true
    }
    if (filters.kind && n.kind !== filters.kind) return false
    if (filters.context && n.parent !== filters.context) return false
    if (filters.confidence && n.confidence !== filters.confidence) return false
    return true
  }
  const visibleIds = new Set(safeNodes.filter(keep).map((n) => n.id))
  return {
    ...payload,
    nodes: safeNodes.filter((n) => visibleIds.has(n.id)),
    edges: (payload.edges || []).filter(
      (e) => visibleIds.has(e.source) && visibleIds.has(e.target),
    ),
  }
}

function mergeDiscovered(graph, discovered) {
  if (!graph || !Array.isArray(discovered) || discovered.length === 0) {
    return graph
  }
  const extraNodes = discovered.map((entry) => ({
    id: `entry-${entry.owner}-${entry.repo}-${entry.id}`,
    type: 'entry',
    name: entry.filename,
    topic: entry.topic,
    parent: 'discovered',
    owner: entry.owner,
    repo: entry.repo,
    entry_id: entry.id,
  }))
  return {
    ...graph,
    nodes: [...(graph.nodes || []), ...extraNodes],
    edges: graph.edges || [],
    contexts: [
      ...(graph.contexts || []),
      { id: 'discovered', label: 'discovered' },
    ],
  }
}

export function DomainView({ selectedNodeId, onSelectNode, filters }) {
  const [graph, setGraph] = useState(null)
  const [discovered, setDiscovered] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      fetch('/api/atlas/graph?include_entries=true').then((r) => {
        if (!r.ok) throw new Error(`status ${r.status}`)
        return r.json()
      }),
      fetch('/api/atlas/discovered').then((r) => (r.ok ? r.json() : [])),
    ])
      .then(([graphData, discoveredData]) => {
        if (cancelled) return
        setGraph(graphData)
        setDiscovered(Array.isArray(discoveredData) ? discoveredData : [])
        setError(null)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err)
        setGraph(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const merged = mergeDiscovered(graph, discovered)
  const filtered = applyFilters(merged, filters)
  const { nodes, edges } = useGraphLayout(filtered, 'domain', selectedNodeId)

  if (error) {
    return (
      <div
        data-testid="atlas-domain-view"
        style={{ padding: 24, color: theme.textMuted, fontSize: 13 }}
      >
        Unable to load graph data.
      </div>
    )
  }

  if (!graph) {
    return (
      <div
        data-testid="atlas-domain-view"
        style={{ padding: 24, color: theme.textMuted, fontSize: 13 }}
      >
        Loading…
      </div>
    )
  }

  return (
    <div
      data-testid="atlas-domain-view"
      style={{ height: '100%', width: '100%' }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodeClick={(_, n) => {
          if (n.type !== 'group') onSelectNode(n.id)
        }}
        fitView
      >
        <Background />
        <Controls />
        <MiniMap pannable zoomable />
      </ReactFlow>
    </div>
  )
}

export default DomainView
