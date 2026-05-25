import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
  },
  server: {
    proxy: {
      '/api': 'http://localhost:7890',
      '/ws': {
        target: 'ws://localhost:7890',
        ws: true,
      },
      '/mcp': 'http://localhost:7890',
    },
  },
})
