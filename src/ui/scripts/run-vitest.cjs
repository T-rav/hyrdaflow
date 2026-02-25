#!/usr/bin/env node

const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const args = process.argv.slice(2)
const projectRoot = path.resolve(__dirname, '..')
const registerShim = path.join(projectRoot, 'src/test/register-encoding-lite.cjs')
const vitestBin = path.join(projectRoot, 'node_modules/vitest/vitest.mjs')
const vitestJsdomChunk = path.join(
  projectRoot,
  'node_modules/vitest/dist/chunks/index.CyBMJtT7.js',
)

const existingNodeOptions = process.env.NODE_OPTIONS ? `${process.env.NODE_OPTIONS} ` : ''
const patchedNodeOptions = `${existingNodeOptions}--require=${registerShim}`.trim()

function ensureJsdomPatch() {
  let content
  try {
    content = fs.readFileSync(vitestJsdomChunk, 'utf8')
  } catch (err) {
    console.warn('[hf] warning: unable to patch Vitest jsdom chunk', err)
    return
  }
  if (!content.includes('runScripts = "dangerously"')) {
    return
  }
  const patched = content.replace(/runScripts = "dangerously"/g, 'runScripts = void 0')
  fs.writeFileSync(vitestJsdomChunk, patched, 'utf8')
}

ensureJsdomPatch()

const child = spawn(process.execPath, [vitestBin, ...args], {
  stdio: 'inherit',
  env: {
    ...process.env,
    NODE_OPTIONS: patchedNodeOptions,
  },
})

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal)
  } else {
    process.exit(code ?? 0)
  }
})

child.on('error', (err) => {
  console.error(err)
  process.exit(1)
})
