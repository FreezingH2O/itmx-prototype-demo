import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The web app talks to the Engine API through /v1 (proxied to FastAPI on :8000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/v1': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
  },
})
