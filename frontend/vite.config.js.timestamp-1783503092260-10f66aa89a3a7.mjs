// vite.config.js
import { defineConfig } from "file:///D:/%E4%BB%A3%E7%A0%81/Trend%20tools/%E6%95%B0%E6%8D%AE%E5%A4%A7%E7%9B%98/StockRank/frontend/node_modules/vite/dist/node/index.js";
import vue from "file:///D:/%E4%BB%A3%E7%A0%81/Trend%20tools/%E6%95%B0%E6%8D%AE%E5%A4%A7%E7%9B%98/StockRank/frontend/node_modules/@vitejs/plugin-vue/dist/index.mjs";
import path from "path";
import { copyFileSync, existsSync, mkdirSync } from "fs";
var __vite_injected_original_dirname = "D:\\\u4EE3\u7801\\Trend tools\\\u6570\u636E\u5927\u76D8\\StockRank\\frontend";
var vite_config_default = defineConfig({
  plugins: [vue()],
  server: {
    port: 3e3,
    proxy: {
      "/api": {
        target: "http://localhost:5000",
        changeOrigin: true
      },
      "/health": {
        target: "http://localhost:5000",
        changeOrigin: true
      }
    }
  },
  build: {
    emptyOutDir: true
  },
  optimizeDeps: {
    include: ["vue", "echarts", "vue-router"]
  }
});
function copySoundFiles() {
  const sourceDir = path.join(__vite_injected_original_dirname, "public", "sounds");
  const targetDir = path.join(__vite_injected_original_dirname, "dist", "assets", "sounds");
  if (existsSync(sourceDir)) {
    if (!existsSync(targetDir)) {
      mkdirSync(targetDir, { recursive: true });
    }
    const soundFiles = ["important.mp3", "normal.mp3"];
    soundFiles.forEach((file) => {
      const sourcePath = path.join(sourceDir, file);
      const targetPath = path.join(targetDir, file);
      if (existsSync(sourcePath)) {
        copyFileSync(sourcePath, targetPath);
        console.log(`\u5DF2\u590D\u5236\u97F3\u6548\u6587\u4EF6: ${file}`);
      } else {
        console.log(`\u8B66\u544A: \u97F3\u6548\u6587\u4EF6 ${file} \u4E0D\u5B58\u5728`);
      }
    });
  }
}
if (process.argv.includes("build")) {
  setTimeout(() => {
    copySoundFiles();
  }, 1e3);
}
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcuanMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCJEOlxcXFxcdTRFRTNcdTc4MDFcXFxcVHJlbmQgdG9vbHNcXFxcXHU2NTcwXHU2MzZFXHU1OTI3XHU3NkQ4XFxcXFN0b2NrUmFua1xcXFxmcm9udGVuZFwiO2NvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9maWxlbmFtZSA9IFwiRDpcXFxcXHU0RUUzXHU3ODAxXFxcXFRyZW5kIHRvb2xzXFxcXFx1NjU3MFx1NjM2RVx1NTkyN1x1NzZEOFxcXFxTdG9ja1JhbmtcXFxcZnJvbnRlbmRcXFxcdml0ZS5jb25maWcuanNcIjtjb25zdCBfX3ZpdGVfaW5qZWN0ZWRfb3JpZ2luYWxfaW1wb3J0X21ldGFfdXJsID0gXCJmaWxlOi8vL0Q6LyVFNCVCQiVBMyVFNyVBMCU4MS9UcmVuZCUyMHRvb2xzLyVFNiU5NSVCMCVFNiU4RCVBRSVFNSVBNCVBNyVFNyU5QiU5OC9TdG9ja1JhbmsvZnJvbnRlbmQvdml0ZS5jb25maWcuanNcIjtpbXBvcnQgeyBkZWZpbmVDb25maWcgfSBmcm9tICd2aXRlJ1xyXG5pbXBvcnQgdnVlIGZyb20gJ0B2aXRlanMvcGx1Z2luLXZ1ZSdcclxuaW1wb3J0IHBhdGggZnJvbSAncGF0aCdcclxuaW1wb3J0IHsgY29weUZpbGVTeW5jLCBleGlzdHNTeW5jLCBta2RpclN5bmMgfSBmcm9tICdmcydcclxuXHJcbmV4cG9ydCBkZWZhdWx0IGRlZmluZUNvbmZpZyh7XHJcbiAgcGx1Z2luczogW3Z1ZSgpXSxcclxuICBzZXJ2ZXI6IHtcclxuICAgIHBvcnQ6IDMwMDAsXHJcbiAgICBwcm94eToge1xyXG4gICAgICAnL2FwaSc6IHtcclxuICAgICAgICB0YXJnZXQ6ICdodHRwOi8vbG9jYWxob3N0OjUwMDAnLFxyXG4gICAgICAgIGNoYW5nZU9yaWdpbjogdHJ1ZVxyXG4gICAgICB9LFxyXG4gICAgICAnL2hlYWx0aCc6IHtcclxuICAgICAgICB0YXJnZXQ6ICdodHRwOi8vbG9jYWxob3N0OjUwMDAnLFxyXG4gICAgICAgIGNoYW5nZU9yaWdpbjogdHJ1ZVxyXG4gICAgICB9XHJcbiAgICB9XHJcbiAgfSxcclxuICBidWlsZDoge1xyXG4gICAgZW1wdHlPdXREaXI6IHRydWVcclxuICB9LFxyXG4gIG9wdGltaXplRGVwczoge1xyXG4gICAgaW5jbHVkZTogWyd2dWUnLCAnZWNoYXJ0cycsICd2dWUtcm91dGVyJ11cclxuICB9XHJcbn0pXHJcblxyXG4vLyBcdTU5MERcdTUyMzZcdTk3RjNcdTY1NDhcdTY1ODdcdTRFRjZcdTUyMzBkaXN0XHU3NkVFXHU1RjU1XHJcbmZ1bmN0aW9uIGNvcHlTb3VuZEZpbGVzKCkge1xyXG4gIGNvbnN0IHNvdXJjZURpciA9IHBhdGguam9pbihfX2Rpcm5hbWUsICdwdWJsaWMnLCAnc291bmRzJylcclxuICBjb25zdCB0YXJnZXREaXIgPSBwYXRoLmpvaW4oX19kaXJuYW1lLCAnZGlzdCcsICdhc3NldHMnLCAnc291bmRzJylcclxuICBcclxuICBpZiAoZXhpc3RzU3luYyhzb3VyY2VEaXIpKSB7XHJcbiAgICBpZiAoIWV4aXN0c1N5bmModGFyZ2V0RGlyKSkge1xyXG4gICAgICBta2RpclN5bmModGFyZ2V0RGlyLCB7IHJlY3Vyc2l2ZTogdHJ1ZSB9KVxyXG4gICAgfVxyXG4gICAgXHJcbiAgICBjb25zdCBzb3VuZEZpbGVzID0gWydpbXBvcnRhbnQubXAzJywgJ25vcm1hbC5tcDMnXVxyXG4gICAgXHJcbiAgICBzb3VuZEZpbGVzLmZvckVhY2goZmlsZSA9PiB7XHJcbiAgICAgIGNvbnN0IHNvdXJjZVBhdGggPSBwYXRoLmpvaW4oc291cmNlRGlyLCBmaWxlKVxyXG4gICAgICBjb25zdCB0YXJnZXRQYXRoID0gcGF0aC5qb2luKHRhcmdldERpciwgZmlsZSlcclxuICAgICAgXHJcbiAgICAgIGlmIChleGlzdHNTeW5jKHNvdXJjZVBhdGgpKSB7XHJcbiAgICAgICAgY29weUZpbGVTeW5jKHNvdXJjZVBhdGgsIHRhcmdldFBhdGgpXHJcbiAgICAgICAgY29uc29sZS5sb2coYFx1NURGMlx1NTkwRFx1NTIzNlx1OTdGM1x1NjU0OFx1NjU4N1x1NEVGNjogJHtmaWxlfWApXHJcbiAgICAgIH0gZWxzZSB7XHJcbiAgICAgICAgY29uc29sZS5sb2coYFx1OEI2Nlx1NTQ0QTogXHU5N0YzXHU2NTQ4XHU2NTg3XHU0RUY2ICR7ZmlsZX0gXHU0RTBEXHU1QjU4XHU1NzI4YClcclxuICAgICAgfVxyXG4gICAgfSlcclxuICB9XHJcbn1cclxuXHJcbi8vIFx1NTcyOGJ1aWxkXHU1QjhDXHU2MjEwXHU1NDBFXHU1OTBEXHU1MjM2XHU5N0YzXHU2NTQ4XHU2NTg3XHU0RUY2XHJcbmlmIChwcm9jZXNzLmFyZ3YuaW5jbHVkZXMoJ2J1aWxkJykpIHtcclxuICAvLyBcdTdCNDlcdTVGODVidWlsZFx1NUI4Q1x1NjIxMFx1NTQwRVx1NjI2N1x1ODg0Q1xyXG4gIHNldFRpbWVvdXQoKCkgPT4ge1xyXG4gICAgY29weVNvdW5kRmlsZXMoKVxyXG4gIH0sIDEwMDApXHJcbn1cclxuIl0sCiAgIm1hcHBpbmdzIjogIjtBQUEyVyxTQUFTLG9CQUFvQjtBQUN4WSxPQUFPLFNBQVM7QUFDaEIsT0FBTyxVQUFVO0FBQ2pCLFNBQVMsY0FBYyxZQUFZLGlCQUFpQjtBQUhwRCxJQUFNLG1DQUFtQztBQUt6QyxJQUFPLHNCQUFRLGFBQWE7QUFBQSxFQUMxQixTQUFTLENBQUMsSUFBSSxDQUFDO0FBQUEsRUFDZixRQUFRO0FBQUEsSUFDTixNQUFNO0FBQUEsSUFDTixPQUFPO0FBQUEsTUFDTCxRQUFRO0FBQUEsUUFDTixRQUFRO0FBQUEsUUFDUixjQUFjO0FBQUEsTUFDaEI7QUFBQSxNQUNBLFdBQVc7QUFBQSxRQUNULFFBQVE7QUFBQSxRQUNSLGNBQWM7QUFBQSxNQUNoQjtBQUFBLElBQ0Y7QUFBQSxFQUNGO0FBQUEsRUFDQSxPQUFPO0FBQUEsSUFDTCxhQUFhO0FBQUEsRUFDZjtBQUFBLEVBQ0EsY0FBYztBQUFBLElBQ1osU0FBUyxDQUFDLE9BQU8sV0FBVyxZQUFZO0FBQUEsRUFDMUM7QUFDRixDQUFDO0FBR0QsU0FBUyxpQkFBaUI7QUFDeEIsUUFBTSxZQUFZLEtBQUssS0FBSyxrQ0FBVyxVQUFVLFFBQVE7QUFDekQsUUFBTSxZQUFZLEtBQUssS0FBSyxrQ0FBVyxRQUFRLFVBQVUsUUFBUTtBQUVqRSxNQUFJLFdBQVcsU0FBUyxHQUFHO0FBQ3pCLFFBQUksQ0FBQyxXQUFXLFNBQVMsR0FBRztBQUMxQixnQkFBVSxXQUFXLEVBQUUsV0FBVyxLQUFLLENBQUM7QUFBQSxJQUMxQztBQUVBLFVBQU0sYUFBYSxDQUFDLGlCQUFpQixZQUFZO0FBRWpELGVBQVcsUUFBUSxVQUFRO0FBQ3pCLFlBQU0sYUFBYSxLQUFLLEtBQUssV0FBVyxJQUFJO0FBQzVDLFlBQU0sYUFBYSxLQUFLLEtBQUssV0FBVyxJQUFJO0FBRTVDLFVBQUksV0FBVyxVQUFVLEdBQUc7QUFDMUIscUJBQWEsWUFBWSxVQUFVO0FBQ25DLGdCQUFRLElBQUksK0NBQVksSUFBSSxFQUFFO0FBQUEsTUFDaEMsT0FBTztBQUNMLGdCQUFRLElBQUksMENBQVksSUFBSSxxQkFBTTtBQUFBLE1BQ3BDO0FBQUEsSUFDRixDQUFDO0FBQUEsRUFDSDtBQUNGO0FBR0EsSUFBSSxRQUFRLEtBQUssU0FBUyxPQUFPLEdBQUc7QUFFbEMsYUFBVyxNQUFNO0FBQ2YsbUJBQWU7QUFBQSxFQUNqQixHQUFHLEdBQUk7QUFDVDsiLAogICJuYW1lcyI6IFtdCn0K
