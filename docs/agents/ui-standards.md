# UI Development Standards

The React dashboard (`ui/`) uses inline styles in JSX. Follow these conventions.

## Layout

- **CSS Grid** for page-level layout (`App.jsx`), **Flexbox** for component internals
- Sidebar is fixed at `280px`; set `flexShrink: 0` on fixed-width panels and connectors
- Set `minWidth` on containers to prevent content overlap at narrow viewports

## DRY principle

- Shared constants (`ACTIVE_STATUSES`, `PIPELINE_STAGES`) live in `ui/src/constants.js` — never duplicate.
- Type definitions in `ui/src/types.js`.
- Colors are CSS custom properties in `ui/index.html` `:root`, accessed via `ui/src/theme.js` — always use `theme.*` tokens, never raw hex or rgb values.
- Extract shared styles to reusable objects when used 3+ times.

## Style consistency

- Define `const styles = {}` at file bottom; pre-compute variants (active/inactive, lit/dim) outside the component to avoid object spread in render loops. See `Header.jsx` `pillStyles` for the reference pattern.
- Spacing scale: multiples of 4px (4, 8, 12, 16, 20, 24, 32).
- Font size scale: 9, 10, 11, 12, 13, 14, 16, 18.
- New colors must be added to both `ui/index.html` `:root` and `ui/src/theme.js`.

## Component patterns

- Check for existing components before creating new ones — pill badges in `Header.jsx`, status badges in `StreamCard.jsx`, tables in `ReviewTable.jsx`.
- Prefer extending existing components over parallel implementations.
- Interactive elements need hover and focus states (`cursor: 'pointer'`, `transition`).
- Derive stage-related UI from `PIPELINE_STAGES` in `constants.js`.
