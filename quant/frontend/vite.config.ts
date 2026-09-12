import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

function toChunkName(value: string) {
  return value
    .replace(/\.[cm]?[tj]sx?$/, '')
    .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
    .replace(/[^a-zA-Z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase()
}

export default defineConfig({
  plugins: [react()],
  base: '/TrendZen/',
  build: {
    cssCodeSplit: true,
    chunkSizeWarningLimit: 350,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalizedId = id.replace(/\\/g, '/')

          if (normalizedId.includes('/node_modules/')) {
            if (normalizedId.includes('/react/') || normalizedId.includes('/react-dom/')) {
              return 'vendor-react'
            }
            if (normalizedId.includes('/lightweight-charts/')) {
              return 'vendor-charts'
            }
            return 'vendor-misc'
          }

          const srcIndex = normalizedId.lastIndexOf('/src/')
          if (srcIndex === -1) return undefined

          const sourcePath = normalizedId.slice(srcIndex + '/src/'.length)
          if (sourcePath.startsWith('components/')) {
            const fileName = sourcePath.split('/').pop()
            return fileName ? `component-${toChunkName(fileName)}` : 'components'
          }
          if (sourcePath.startsWith('api/')) {
            return 'api'
          }
          if (sourcePath.startsWith('lib/chan')) {
            return 'lib-chan'
          }
          if (sourcePath.startsWith('lib/')) {
            return 'lib-market'
          }
          if (sourcePath.startsWith('hooks/')) {
            return 'hooks'
          }
          if (sourcePath.startsWith('types/')) {
            return 'types'
          }

          return undefined
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
