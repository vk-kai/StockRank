<template>
  <svg
    class="ic ic-trending"
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
    <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" />
    <polyline points="16 7 22 7 22 13" />
  </svg>
</template>

<script>
// "量化交易"线性图标(Lucide trending-up 风格,上行折线)。
// 全局注册于 main.js,<IconTrending/> 使用。
export default {
  name: 'IconTrending',
  props: {
    size: { type: [Number, String], default: 16 }
  }
}
</script>

<style scoped>
.ic-trending {
  vertical-align: -0.22em;
  margin-right: 5px;
  display: inline-block;
}
</style>
