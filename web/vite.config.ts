import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

function toWsUrl(httpUrl: string) {
  if (httpUrl.startsWith('https://')) return httpUrl.replace(/^https:\/\//, 'wss://')
  if (httpUrl.startsWith('http://')) return httpUrl.replace(/^http:\/\//, 'ws://')
  return httpUrl
}

// SPA 重构: Vue 接管 / 根路径, 后端 /v1/* API 仍由 FastAPI 提供。
// dev: vite 代理 /v1, /health, /ws 到 VITE_BACKEND_URL。
// prod: vite build 到 web/dist/, FastAPI 静态 mount + SPA catch-all。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '')
  const backendUrl = (env.VITE_BACKEND_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
  const backendWs = (env.VITE_BACKEND_WS || toWsUrl(backendUrl)).replace(/\/$/, '')
  const devPort = Number(env.VITE_DEV_SERVER_PORT || 5173)

  return {
    plugins: [vue()],
    resolve: {
      alias: { '@': path.resolve(__dirname, 'src') },
    },
    server: {
      port: devPort,
      host: env.VITE_DEV_SERVER_HOST || '127.0.0.1',
      proxy: {
        '/v1': { target: backendUrl, changeOrigin: true },
        '/health': { target: backendUrl },
        '/ws': { target: backendWs, ws: true },
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
  }
})
