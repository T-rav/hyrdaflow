import { defineConfig, createLogger } from 'vite'
import react from '@vitejs/plugin-react'

// Vite attaches its own `error` handler to the proxy EventEmitter after the
// user's `configure` runs, so `proxy.on('error', ...)` can't suppress the
// "ws proxy error" / "ws proxy socket error" messages; the socket-level
// error is per-request and unreachable from config entirely. The only lever
// is the logger. These errors fire when a browser socket tears down
// mid-write (HMR reload, StrictMode remount, backgrounded tab) — the
// frontend reconnects on its own.
const logger = createLogger()
const originalError = logger.error.bind(logger)
logger.error = (msg, options) => {
  if (typeof msg === 'string' && /ws proxy (?:socket )?error/.test(msg)) {
    return
  }
  originalError(msg, options)
}

export default defineConfig({
  customLogger: logger,
  plugins: [react()],
  base: '/',
  optimizeDeps: {
    include: ['html2canvas']
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    rollupOptions: {
      output: {
        assetFileNames: 'assets/[name].[hash][extname]',
        chunkFileNames: 'assets/[name].[hash].js',
        entryFileNames: 'assets/[name].[hash].js'
      }
    }
  },
  server: {
    port: 5556,
    proxy: {
      '/api': 'http://localhost:5555',
      '/ws': {
        target: 'ws://localhost:5555',
        ws: true,
      }
    }
  }
})
