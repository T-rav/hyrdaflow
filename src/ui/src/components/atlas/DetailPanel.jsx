import React from 'react'
import { theme } from '../../theme'
import { TermDetailPanel } from './TermDetailPanel'
import { AdrDetailPanel } from './AdrDetailPanel'

/**
 * Routes the selected-node detail render to the right panel by id shape:
 *   "adr-<n>" → AdrDetailPanel
 *   anything else → TermDetailPanel
 *
 * Lives at this level so DomainView and GraphView can share selection state
 * without each owning its own panel routing.
 */
export function DetailPanel({ selectedNodeId }) {
  if (!selectedNodeId) {
    return (
      <div
        style={{
          padding: '14px 16px',
          fontSize: 13,
          color: theme.textMuted,
        }}
      >
        Pick a node in the graph to see details.
      </div>
    )
  }
  if (/^adr-\d+$/.test(selectedNodeId)) {
    return <AdrDetailPanel selectedNodeId={selectedNodeId} />
  }
  return <TermDetailPanel selectedNodeId={selectedNodeId} />
}

export default DetailPanel
