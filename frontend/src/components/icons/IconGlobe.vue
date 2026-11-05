<template>
  <svg
    class="ic ic-globe"
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
    <circle cx="12" cy="12" r="10" />
    <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
    <path d="M2 12h20" />
  </svg>
</template>

<script>
// "全球股市"线性图标(Lucide globe 风格,地球+经纬线)。
// 全局注册于 main.js,<IconGlobe/> 使用。
export default {
  name: 'IconGlobe',
  props: {
    size: { type: [Number, String], default: 16 }
  }
}
</script>

<style scoped>
.ic-globe {
  vertical-align: -0.22em;
  margin-right: 5px;
  display: inline-block;
}
</style>
