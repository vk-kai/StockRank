<template>
  <svg
    class="ic ic-treemap"
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
    <rect width="7" height="9" x="3" y="3" rx="1" />
    <rect width="7" height="5" x="14" y="3" rx="1" />
    <rect width="7" height="9" x="14" y="12" rx="1" />
    <rect width="7" height="5" x="3" y="16" rx="1" />
  </svg>
</template>

<script>
// "大盘云图"线性图标（Lucide layout-dashboard 风格，大小不一的方块=热力图/云图）。
// 全局注册于 main.js，<IconTreemap/> 使用。
export default {
  name: 'IconTreemap',
  props: {
    size: { type: [Number, String], default: 16 }
  }
}
</script>

<style scoped>
.ic-treemap {
  vertical-align: -0.22em;
  margin-right: 5px;
  display: inline-block;
}
</style>
