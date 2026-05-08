import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import { copyFileSync, existsSync, mkdirSync } from 'fs'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true
      },
      '/health': {
        target: 'http://localhost:5000',
        changeOrigin: true
      }
    }
  },
  build: {
    emptyOutDir: true
  },
  optimizeDeps: {
    include: ['vue', 'echarts', 'vue-router']
  }
})

// 复制音效文件到dist目录
function copySoundFiles() {
  const sourceDir = path.join(__dirname, 'public', 'sounds')
  const targetDir = path.join(__dirname, 'dist', 'assets', 'sounds')
  
  if (existsSync(sourceDir)) {
    if (!existsSync(targetDir)) {
      mkdirSync(targetDir, { recursive: true })
    }
    
    const soundFiles = ['important.mp3', 'normal.mp3']
    
    soundFiles.forEach(file => {
      const sourcePath = path.join(sourceDir, file)
      const targetPath = path.join(targetDir, file)
      
      if (existsSync(sourcePath)) {
        copyFileSync(sourcePath, targetPath)
        console.log(`已复制音效文件: ${file}`)
      } else {
        console.log(`警告: 音效文件 ${file} 不存在`)
      }
    })
  }
}

// 在build完成后复制音效文件
if (process.argv.includes('build')) {
  // 等待build完成后执行
  setTimeout(() => {
    copySoundFiles()
  }, 1000)
}
