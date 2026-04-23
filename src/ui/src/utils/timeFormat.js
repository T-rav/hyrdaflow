export function formatRelative(iso) {
  if (!iso) return ''
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const diffSec = Math.floor((Date.now() - t) / 1000)
  if (diffSec < 30) return 'just now'
  if (diffSec < 60) return `${diffSec}s ago`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
  return `${Math.floor(diffSec / 86400)}d ago`
}

export function formatDuration(startIso, endIso) {
  if (!startIso || !endIso) return ''
  const start = Date.parse(startIso)
  const end = Date.parse(endIso)
  if (Number.isNaN(start) || Number.isNaN(end)) return ''
  const diffSec = Math.floor((end - start) / 1000)
  if (diffSec < 0) return ''
  if (diffSec < 60) return `${diffSec}s`
  const totalMin = Math.floor(diffSec / 60)
  if (totalMin < 60) return `${totalMin}min`
  const hours = Math.floor(totalMin / 60)
  const mins = totalMin % 60
  return mins === 0 ? `${hours}h` : `${hours}h ${mins}min`
}
