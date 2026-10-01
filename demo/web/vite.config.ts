import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// The web app talks to the Engine API through /v1. In dev, /v1 is proxied to FastAPI
// (API_PROXY_TARGET, default :8000). In a deploy, VITE_API_BASE points at the API origin.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: { '/v1': { target: env.API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true } },
    },
  }
})
