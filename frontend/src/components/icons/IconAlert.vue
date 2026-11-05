<template>
  <svg
    class="ic ic-alert"
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
    <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" />
    <path d="M12 9v4" />
    <path d="M12 17h.01" />
  </svg>
</template>

<script>
// "分析失败重试"线性图标(Lucide triangle-alert 风格,警告三角)。
// 全局注册于 main.js,<IconAlert/> 使用。
export default {
  name: 'IconAlert',
  props: {
    size: { type: [Number, String], default: 16 }
  }
}
</script>

<style scoped>
.ic-alert {
  vertical-align: -0.22em;
  margin-right: 5px;
  display: inline-block;
}
</style>
