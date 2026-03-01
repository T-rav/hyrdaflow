# ADR-0020: autoApproveRow borderTop Context Awareness When Extracting Embedded Components

**Status:** Proposed
**Date:** 2026-03-01

## Context

The `autoApproveRow` style in `SystemPanel.jsx` was originally designed for use
inside `BackgroundWorkerCard` components, where `borderTop: 1px solid` acts as a
visual separator between the card's main content and an embedded toggle (e.g.,
`MemoryAutoApproveToggle` inside the `memory_sync` card, `UnstickWorkersDropdown`
inside the `pr_unsticker` card). In that embedded context, the border separates
two peer regions of the same card.

When `ProcessToggles` was extracted to its own dedicated "Processes" sub-tab, the
`ToggleRow` component (which reuses `autoApproveRow`) became the first child
under a standalone `<h3>` section heading. The first `ToggleRow`'s `borderTop`
now visually "underlines" the heading rather than separating two peer rows,
because there is no preceding sibling content to separate from.

This was identified during issue #1805 and accepted as intentional design in the
current codebase, but it highlights a broader pattern worth documenting: styles
designed for embedded/within-card contexts may produce unintended visual artifacts
when the same component is promoted to a standalone top-level context.

## Decision

Accept the current `borderTop` behavior on `autoApproveRow` when rendered as the
first item under a standalone section heading, and document the following
guidelines for future component extraction:

1. **Context-audit on extraction:** When moving a component from an embedded
   context (inside a card, list item, or collapsible section) to a standalone
   context (dedicated tab, page section), audit inherited styles for assumptions
   about surrounding DOM structure. Borders, margins, and padding that act as
   separators between siblings may produce visual artifacts when the component
   becomes a first or last child.

2. **Prefer conditional first-child styling:** If the `borderTop` behavior is
   undesirable in a future extraction, use a prop (e.g., `isFirst`) or CSS
   `:first-child` logic to suppress the border on the first item rather than
   forking the style object. This keeps the style definition centralized.

3. **Current state is acceptable:** The `autoApproveRow` border under the
   "Process Toggles" heading reads as a subtle heading underline and does not
   degrade usability. No code change is required at this time.

## Consequences

**Positive:**
- Makes the embedded-to-standalone extraction hazard explicit for future UI work.
- Prevents duplicate debugging effort when similar visual artifacts arise in
  other component extractions.
- Provides a lightweight pattern (conditional first-child suppression) that can
  be applied incrementally if the visual behavior is later deemed undesirable.

**Trade-offs:**
- Accepting the current behavior means the "Processes" tab heading has an
  unconventional underline effect that differs from other tabs.
- Future developers must consult this ADR or the style definition to understand
  why the border appears under the heading.

## Alternatives considered

1. **Remove `borderTop` from `autoApproveRow` globally.**
   Rejected: this would break the intended separator behavior inside
   `BackgroundWorkerCard` where the border separates card content from the
   embedded toggle.

2. **Create a separate `toggleRowStandalone` style without `borderTop`.**
   Rejected: adds style duplication. The conditional first-child approach is
   preferred if a change is ever needed.

3. **Add `borderTop: 'none'` override on the first `ToggleRow` in
   `ProcessToggles`.**
   Rejected for now: the current visual is acceptable and inline overrides
   reduce maintainability. If revisited, a prop-based approach is preferred.

## Related

- Source memory: #1805
- Issue: #1818
- `src/ui/src/components/SystemPanel.jsx` (`autoApproveRow` style, `ProcessToggles`, `ToggleRow`, `MemoryAutoApproveToggle`)
