<template>
  <svg
    class="ic ic-refresh"
    :class="{ spin }"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
    <path d="M21 3v5h-5" />
    <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
    <path d="M3 21v-5h5" />
  </svg>
</template>

<script>
// 统一的"刷新"线性图标（Lucide refresh-cw 风格）。全局注册于 main.js，各页面直接 <IconRefresh/> 使用。
// spin=true 时图标旋转（替代原 ↻/🔄 的转动动效，如大盘云图刷新行情按钮）。
export default {
  name: 'IconRefresh',
  props: {
    size: { type: [Number, String], default: 15 },
    spin: { type: Boolean, default: false }
  }
}
</script>

<style scoped>
.ic-refresh {
  vertical-align: -0.18em;
  margin-right: 5px;
  display: inline-block;
}
.ic-refresh.spin {
  animation: ic-refresh-spin 1s linear infinite;
}
@keyframes ic-refresh-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
