import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/src/pages/layout/lib/themes/')) {
            return 'layout-themes'
          }
          if (id.includes('markdown-it') || id.includes('highlight.js')) {
            return 'layout-markdown'
          }
          if (id.includes('turndown')) {
            return 'layout-paste'
          }
          if (id.includes('/src/pages/layout/lib/wechatCompat.ts')) {
            return 'layout-wechat'
          }
          return undefined
        },
      },
    },
  },
})
