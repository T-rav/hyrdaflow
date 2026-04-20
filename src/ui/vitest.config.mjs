import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    // e2e/*.spec.js files run under Playwright (see `npm run screenshot`),
    // never via vitest. Expanding this glob if we add subdirs is intentional.
    exclude: ['e2e/**/*.spec.js', 'node_modules/**'],
  },
})
