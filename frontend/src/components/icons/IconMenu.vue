<template>
  <svg
    class="ic ic-menu"
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
    <line x1="4" x2="20" y1="6" y2="6" />
    <line x1="4" x2="20" y1="12" y2="12" />
    <line x1="4" x2="20" y1="18" y2="18" />
  </svg>
</template>

<script>
// "更多"线性图标(Lucide menu 风格,三横线)。
// 全局注册于 main.js,<IconMenu/> 使用。
export default {
  name: 'IconMenu',
  props: {
    size: { type: [Number, String], default: 16 }
  }
}
</script>

<style scoped>
.ic-menu {
  vertical-align: -0.22em;
  margin-right: 5px;
  display: inline-block;
}
</style>
