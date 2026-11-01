# -*- coding: utf-8 -*-
"""本地 个人Agent/web/index.html → StockRank 前端 AgentAvatar.vue 转换器

本地主战场迭代 index.html(单文件版), 本脚本把它机械转换成 Vue3 组件:
- CSS: :root/body 选择器 → .agent-page 组件根容器(scoped)
- HTML: body 内容 → template(剔除 <script>)
- JS: 全部包进 onMounted; fetch('/api/…') 改 /api/agent/…; 内联 onclick 引用的
  函数挂到 window(Vue 组件内函数不在全局作用域); echarts 走 npm import
转换是确定性的, 可重复执行(sync_agent_code.py 每次同步会重跑)。
手动改本组件会被覆盖 —— 要改前端请改本地 web/index.html 后同步。

用法: python backend/scripts/agent_build_vue.py [本地个人Agent目录]
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..'))
OUT_VUE = os.path.join(REPO, 'frontend', 'src', 'AgentAvatar.vue')
DEFAULT_LOCAL = r'C:\Users\Administrator\Desktop\WeChatExport\个人Agent'

# 内联事件(onclick 等)引用的函数 → 挂 window; 'this' 是原生内联表达式, 跳过
_EV_RE = re.compile(r'\bon(?:click|dblclick|change|input|submit|keydown)\s*=\s*.([a-zA-Z_$][\w$]*)')


def convert(local_dir):
    src = open(os.path.join(local_dir, 'web', 'index.html'), encoding='utf-8').read()

    css = re.search(r'<style>([\s\S]*?)</style>', src).group(1)
    css = re.sub(r'(?m)^(\s*)(:root|body)(\s*\{)', r'\1.agent-page\3', css).strip()

    body = src[re.search(r'<body[^>]*>', src).end():src.rfind('</body>')]
    scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', body)
    js = '\n'.join(s for s in scripts if s.strip()).strip()
    html = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', body).strip()
    assert '</script' not in js, 'JS 中含 </script>, 无法嵌入 SFC'

    js = js.replace("'/api/", "'/api/agent/").replace('"/api/', '"/api/agent/')

    handlers = sorted({n for n in _EV_RE.findall(src) if n != 'this'})
    expose = '\n'.join(f'  window.{n} = {n};' for n in handlers)

    vue = f'''<!-- ⚠ 本文件由 backend/scripts/agent_build_vue.py 从本地 个人Agent/web/index.html 自动生成 -->
<!-- 手动修改会在下次同步时被覆盖; 要改前端请改本地 web/index.html 后跑同步脚本 -->
<template>
<div class="agent-page">
{html}
</div>
</template>

<script setup>
import {{ onMounted }} from 'vue'
import * as echarts from 'echarts'

onMounted(() => {{
{js}

  // ---- 内联 onclick/ondblclick 属性走全局作用域: 把组件内函数挂到 window ----
{expose}
}})
</script>

<style scoped>
{css}
</style>
'''
    os.makedirs(os.path.dirname(OUT_VUE), exist_ok=True)
    with open(OUT_VUE, 'w', encoding='utf-8') as f:
        f.write(vue)
    print(f'AgentAvatar.vue 已生成: {len(vue)} 字符 | 事件函数挂载: {len(handlers)} 个')
    print('  handlers:', ', '.join(handlers))


if __name__ == '__main__':
    local = sys.argv[1] if len(sys.argv) > 1 else os.environ.get('AGENT_LOCAL_DIR', DEFAULT_LOCAL)
    convert(local)
