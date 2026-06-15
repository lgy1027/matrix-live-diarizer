import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

// SPA 重构: Vue 接管 / 根路径, 后端 /v1/* API 仍由 FastAPI 提供
// dev: vite 5173 → proxy /v1, /health, /ws → 127.0.0.1:8000
// prod: vite build 到 web/dist/, FastAPI 静态 mount + SPA catch-all
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    port: 5173,
    host: '127.0.0.1',
    proxy: {
      '/v1': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000' },
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          'vue-vendor': ['vue', 'vue-router', 'pinia', 'vue-i18n'],
          'axios-vendor': ['axios'],
        },
      },
    },
  },
})
