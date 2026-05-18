import '@testing-library/jest-dom'

// jsdom doesn't ship ResizeObserver; React Flow (used by Atlas DomainView)
// requires it. Polyfill globally so any component test rendering React Flow
// (directly or transitively via App) doesn't crash with ReferenceError.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}
