const Module = require('module')
const path = require('path')

const STATIC_ALIASES = [
  ['@exodus/bytes/encoding-lite.js', './shims/encoding-lite.cjs'],
  ['@exodus/bytes/encoding.js', './shims/encoding.cjs'],
  ['@exodus/bytes/whatwg.js', './shims/whatwg.cjs'],
  ['@exodus/bytes/base64.js', './shims/base64.cjs'],
  ['@csstools/css-calc', './shims/css-calc.cjs'],
  ['@csstools/css-calc/dist/index.mjs', './shims/css-calc.cjs'],
  ['@csstools/css-tokenizer', './shims/css-tokenizer.cjs'],
  ['@csstools/css-tokenizer/dist/index.mjs', './shims/css-tokenizer.cjs'],
  ['@csstools/css-color-parser', './shims/css-color-parser.cjs'],
  ['@csstools/css-color-parser/dist/index.mjs', './shims/css-color-parser.cjs'],
  ['@csstools/css-parser-algorithms', './shims/css-parser-algorithms.cjs'],
  ['@csstools/css-parser-algorithms/dist/index.mjs', './shims/css-parser-algorithms.cjs'],
  ['parse5', './shims/parse5.cjs'],
  ['parse5/dist/index.js', './shims/parse5.cjs'],
]

const resolvedAliases = new Map()
for (const [request, relPath] of STATIC_ALIASES) {
  resolvedAliases.set(request, path.resolve(__dirname, relPath))
}

const originalResolve = Module._resolveFilename

Module._resolveFilename = function patchedResolve(request, parent, isMain, options) {
  const shim = resolvedAliases.get(request)
  if (shim) {
    return shim
  }
  return originalResolve.call(this, request, parent, isMain, options)
}
