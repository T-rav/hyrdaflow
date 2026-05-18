// Compute the 1-hop neighbourhood of `selectedId` in the given graph payload.
// Returns a Set including the selected node itself plus every node connected
// by an incoming or outgoing edge. When `selectedId` is null, returns null
// so callers can short-circuit the focus-fade pass.

export function computeFocusSet(payload, selectedId) {
  if (!payload || !selectedId) return null
  const edges = Array.isArray(payload.edges) ? payload.edges : []
  const neighbours = new Set([selectedId])
  for (const edge of edges) {
    if (edge.source === selectedId) neighbours.add(edge.target)
    if (edge.target === selectedId) neighbours.add(edge.source)
  }
  return neighbours
}
