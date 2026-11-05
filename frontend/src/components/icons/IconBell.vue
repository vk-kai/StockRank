<template>
  <svg
    class="ic ic-bell"
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
    <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
    <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
  </svg>
</template>

<script>
// "异动预警"线性图标(Lucide bell 风格,铃铛)。
// 全局注册于 main.js,<IconBell/> 使用。
export default {
  name: 'IconBell',
  props: {
    size: { type: [Number, String], default: 16 }
  }
}
</script>

<style scoped>
.ic-bell {
  vertical-align: -0.22em;
  margin-right: 5px;
  display: inline-block;
}
</style>
