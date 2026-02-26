import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const indexHtmlPath = resolve(__dirname, '..', '..', 'index.html')

describe('Dashboard index stream-pulse contract', () => {
  const indexHtml = readFileSync(indexHtmlPath, 'utf8')

  it('defines the stream-pulse keyframes exactly once', () => {
    const occurrences = (indexHtml.match(/@keyframes\s+stream-pulse/g) || []).length
    expect(occurrences).toBe(1)
  })

  it('preserves the expected opacity steps for stream-pulse', () => {
    expect(indexHtml).toContain('0%, 100% { opacity: 1; }')
    expect(indexHtml).toContain('50% { opacity: 0.4; }')
  })
})
