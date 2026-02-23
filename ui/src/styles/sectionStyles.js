import { PIPELINE_STAGES } from '../constants'

const sectionHeaderBase = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '8px 12px',
  margin: '8px 8px 4px',
  cursor: 'pointer',
  userSelect: 'none',
  borderRadius: 6,
  transition: 'background 0.15s',
}

export const sectionLabelBase = {
  fontSize: 11,
  fontWeight: 600,
  textTransform: 'uppercase',
  letterSpacing: '0.5px',
}

const sectionCountBase = {
  fontSize: 11,
  fontWeight: 600,
  marginLeft: 'auto',
}

// Note: `${s.color}33` appends a hex alpha suffix to the CSS variable reference string
// (e.g. `var(--accent)33`). After browser CSS variable substitution this becomes a valid
// 8-digit hex color (e.g. `#58a6ff33`, ~20% opacity) — but only because all stage color
// CSS variables in index.html are defined as 6-digit hex values.
// If any variable is changed to rgb() / hsl() format, these borders will silently break.
export const sectionHeaderStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, {
    ...sectionHeaderBase,
    background: s.subtleColor,
    border: `1px solid ${s.color}33`,
    borderLeft: `3px solid ${s.color}`,
  }])
)

export const sectionLabelStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, {
    ...sectionLabelBase,
    color: s.color,
  }])
)

export const sectionCountStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, {
    ...sectionCountBase,
    color: s.color,
  }])
)
