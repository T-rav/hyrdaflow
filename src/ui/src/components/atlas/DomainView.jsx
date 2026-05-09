import React, { useEffect, useMemo, useState } from 'react'
import { ReactFlow, Background, Controls, MiniMap } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { theme } from '../../theme'

const KIND_COLORS = {
  runner: '#7ec699',
  service: '#7aa6e0',
  port: '#c39bd3',
  adapter: '#f0b27a',
  aggregate: '#ec7063',
  entity: '#f7dc6f',
  value_object: '#aab7b8',
  domain_event: '#85c1e9',
  loop: '#bb8fce',
  bounded_context: '#82e0aa',
  invariant: '#f1948a',
  policy: '#5dade2',
}

const CONTEXT_PADDING = { x: 20, y: 32 }
const NODE_W = 160
const NODE_H = 36
const NODE_GAP_X = 16
const NODE_GAP_Y = 12

function layoutGrouped(payload) {
  const safeContexts = Array.isArray(payload?.contexts) ? payload.contexts : []
  const safeNodes = Array.isArray(payload?.nodes) ? payload.nodes : []
  const safeEdges = Array.isArray(payload?.edges) ? payload.edges : []
  const byContext = new Map()
  for (const ctx of safeContexts) {
    byContext.set(ctx.id, { ...ctx, terms: [] })
  }
  for (const node of safeNodes) {
    if (!byContext.has(node.parent)) {
      byContext.set(node.parent, { id: node.parent, label: node.parent, terms: [] })
    }
    byContext.get(node.parent).terms.push(node)
  }

  const parents = []
  const children = []
  let yCursor = 0
  for (const ctx of byContext.values()) {
    const cols = Math.max(1, Math.ceil(Math.sqrt(ctx.terms.length || 1)))
    const rows = Math.max(1, Math.ceil(ctx.terms.length / cols))
    const groupW = CONTEXT_PADDING.x * 2 + cols * NODE_W + (cols - 1) * NODE_GAP_X
    const groupH = CONTEXT_PADDING.y * 2 + rows * NODE_H + (rows - 1) * NODE_GAP_Y

    parents.push({
      id: ctx.id,
      type: 'group',
      data: { label: ctx.label },
      position: { x: 40, y: yCursor },
      style: {
        width: groupW,
        height: groupH,
        background: 'transparent',
        border: `1px dashed ${theme.border}`,
        borderRadius: 6,
        color: theme.textMuted,
        fontSize: 11,
      },
    })

    ctx.terms.forEach((term, idx) => {
      const col = idx % cols
      const row = Math.floor(idx / cols)
      children.push({
        id: term.id,
        parentId: ctx.id,
        extent: 'parent',
        position: {
          x: CONTEXT_PADDING.x + col * (NODE_W + NODE_GAP_X),
          y: CONTEXT_PADDING.y + row * (NODE_H + NODE_GAP_Y),
        },
        data: { label: term.name, kind: term.kind, confidence: term.confidence },
        style: {
          width: NODE_W,
          height: NODE_H,
          background: theme.surfaceInset,
          border: `1px ${term.confidence === 'proposed' ? 'dashed' : 'solid'} ${KIND_COLORS[term.kind] || theme.border}`,
          borderRadius: 4,
          color: theme.text,
          fontSize: 12,
          padding: 6,
        },
      })
    })

    yCursor += groupH + 24
  }

  const edges = safeEdges.map((e, i) => ({
    id: `e${i}`,
    source: e.source,
    target: e.target,
    label: e.kind,
    labelStyle: { fontSize: 10, fill: theme.textMuted },
    style: { stroke: theme.border },
  }))

  return { nodes: [...parents, ...children], edges }
}

export function DomainView({ selectedNodeId, onSelectNode }) {
  const [graph, setGraph] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    fetch('/api/atlas/graph')
      .then((r) => {
        if (!r.ok) throw new Error(`status ${r.status}`)
        return r.json()
      })
      .then((data) => {
        if (cancelled) return
        setGraph(data)
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

  const { nodes, edges } = useMemo(
    () => (graph ? layoutGrouped(graph) : { nodes: [], edges: [] }),
    [graph],
  )

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
        nodes={nodes.map((n) =>
          n.id === selectedNodeId
            ? { ...n, style: { ...n.style, boxShadow: `0 0 0 2px ${theme.accent}` } }
            : n,
        )}
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
