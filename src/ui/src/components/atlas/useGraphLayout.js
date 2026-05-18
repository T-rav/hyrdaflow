import { useMemo } from 'react'
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
} from 'd3-force'
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

const CONTEXT_COLORS = {
  builder: '#7ec699',
  caretaker: '#bb8fce',
  'ai-dev-team': '#7aa6e0',
  'shared-kernel': '#aab7b8',
  adrs: '#888888',
}

const CONTEXT_PADDING = { x: 20, y: 32 }
const NODE_W = 160
const NODE_H = 36
const NODE_GAP_X = 16
const NODE_GAP_Y = 12

function nodeStyle(node, selected) {
  if (node.type === 'adr') {
    return {
      width: NODE_W,
      height: NODE_H,
      background: '#1a1d24',
      border: `1px solid ${selected ? theme.accent : '#666'}`,
      borderRadius: 2,
      color: theme.text,
      fontSize: 12,
      padding: 6,
    }
  }
  if (node.type === 'entry') {
    // Entry nodes are leaves — smaller, lower-contrast. Discovered (orphan)
    // entries get dashed borders so the bot-generated evidence reads as
    // secondary signal next to the curated term/ADR vocabulary.
    const dashed = node.parent === 'discovered'
    return {
      width: 100,
      height: 24,
      background: dashed ? 'transparent' : theme.surfaceInset,
      border: `1px ${dashed ? 'dashed' : 'solid'} ${
        selected ? theme.accent : '#555'
      }`,
      borderRadius: 2,
      color: dashed ? theme.textMuted : theme.text,
      fontSize: 10,
      padding: 4,
      opacity: dashed ? 0.7 : 1,
    }
  }
  return {
    width: NODE_W,
    height: NODE_H,
    background: theme.surfaceInset,
    border: `1px ${node.confidence === 'proposed' ? 'dashed' : 'solid'} ${
      KIND_COLORS[node.kind] || theme.border
    }`,
    borderRadius: 4,
    color: theme.text,
    fontSize: 12,
    padding: 6,
    boxShadow: selected ? `0 0 0 2px ${theme.accent}` : undefined,
  }
}

function buildEdges(rawEdges) {
  return rawEdges.map((e, i) => ({
    id: `e${i}`,
    source: e.source,
    target: e.target,
    label: e.kind,
    labelStyle: { fontSize: 10, fill: theme.textMuted },
    style: {
      stroke:
        e.kind === 'relates_to' || e.kind === 'evidence_for'
          ? '#666'
          : theme.border,
      strokeDasharray:
        e.kind === 'relates_to' || e.kind === 'evidence_for'
          ? '4,2'
          : undefined,
    },
  }))
}

function applyFocusDim(flowNode, focusSet) {
  if (!focusSet) return flowNode
  if (focusSet.has(flowNode.id)) return flowNode
  // Dim non-neighbours but keep them visible. Group containers are
  // unchanged so the bounded-context boxes still anchor the layout.
  if (flowNode.type === 'group') return flowNode
  return {
    ...flowNode,
    style: { ...(flowNode.style || {}), opacity: 0.18 },
  }
}

function layoutDomain(payload, selectedId, focusSet) {
  const safeContexts = Array.isArray(payload?.contexts) ? payload.contexts : []
  const safeNodes = Array.isArray(payload?.nodes) ? payload.nodes : []
  const safeEdges = Array.isArray(payload?.edges) ? payload.edges : []

  const byContext = new Map()
  for (const ctx of safeContexts) {
    byContext.set(ctx.id, { ...ctx, terms: [] })
  }
  for (const node of safeNodes) {
    if (!byContext.has(node.parent)) {
      byContext.set(node.parent, {
        id: node.parent,
        label: node.parent,
        terms: [],
      })
    }
    byContext.get(node.parent).terms.push(node)
  }

  const parents = []
  const children = []
  let yCursor = 0
  for (const ctx of byContext.values()) {
    if (ctx.terms.length === 0) {
      continue
    }
    const cols = Math.max(1, Math.ceil(Math.sqrt(ctx.terms.length)))
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

    ctx.terms.forEach((node, idx) => {
      const col = idx % cols
      const row = Math.floor(idx / cols)
      children.push({
        id: node.id,
        parentId: ctx.id,
        extent: 'parent',
        position: {
          x: CONTEXT_PADDING.x + col * (NODE_W + NODE_GAP_X),
          y: CONTEXT_PADDING.y + row * (NODE_H + NODE_GAP_Y),
        },
        data: { label: node.name, kind: node.kind, type: node.type },
        style: nodeStyle(node, node.id === selectedId),
      })
    })

    yCursor += groupH + 24
  }

  const allNodes = [...parents, ...children].map((n) =>
    applyFocusDim(n, focusSet),
  )
  return { nodes: allNodes, edges: buildEdges(safeEdges) }
}

function layoutForce(payload, selectedId, focusSet) {
  const safeNodes = Array.isArray(payload?.nodes) ? payload.nodes : []
  const safeEdges = Array.isArray(payload?.edges) ? payload.edges : []
  if (safeNodes.length === 0) return { nodes: [], edges: [] }

  // d3-force mutates a copy of the input; we never mutate caller data.
  const simNodes = safeNodes.map((n) => ({ ...n }))
  const simLinks = safeEdges.map((e) => ({ source: e.source, target: e.target }))

  const sim = forceSimulation(simNodes)
    .force(
      'link',
      forceLink(simLinks)
        .id((d) => d.id)
        .distance(120)
        .strength(0.5),
    )
    .force('charge', forceManyBody().strength(-220))
    .force('center', forceCenter(0, 0))
    .force('collide', forceCollide(NODE_W / 2 + 8))
    .stop()

  // Run the simulation synchronously to convergence (small graph).
  for (let i = 0; i < 200; i += 1) sim.tick()

  const flowNodes = simNodes.map((n) => {
    const ctxColor = CONTEXT_COLORS[n.parent] || theme.border
    const baseStyle = nodeStyle(n, n.id === selectedId)
    // Entry nodes keep the dashed/discovered styling computed by nodeStyle —
    // overriding their border here would erase the Discovered-bucket signal
    // (orphans become visually indistinguishable from linked entries).
    const border =
      n.type === 'entry'
        ? baseStyle.border
        : `1px ${n.confidence === 'proposed' ? 'dashed' : 'solid'} ${ctxColor}`
    return {
      id: n.id,
      position: { x: n.x ?? 0, y: n.y ?? 0 },
      data: { label: n.name, kind: n.kind, type: n.type },
      style: { ...baseStyle, border },
    }
  })

  const dimmed = flowNodes.map((n) => applyFocusDim(n, focusSet))
  return { nodes: dimmed, edges: buildEdges(safeEdges) }
}

export function useGraphLayout(payload, mode, selectedId, focusSet) {
  return useMemo(() => {
    if (!payload) return { nodes: [], edges: [] }
    if (mode === 'force') return layoutForce(payload, selectedId, focusSet)
    return layoutDomain(payload, selectedId, focusSet)
  }, [payload, mode, selectedId, focusSet])
}
