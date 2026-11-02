<!-- ⚠ 本文件由 backend/scripts/agent_build_vue.py 从本地 个人Agent/web/index.html 自动生成 -->
<!-- 手动修改会在下次同步时被覆盖; 要改前端请改本地 web/index.html 后跑同步脚本 -->
<template>
<div class="agent-page">
<aside>
  <div class="logo"><div class="av">万</div><div><b>万凯 · 个人分身</b><span>你的数字人生观察室</span></div></div>
  <nav id="nav">
    <a data-p="home" class="on"><span class="ic">🏠</span><div>首页<small>数字人生观察室</small></div></a>
    <a data-p="twin"><span class="ic">💬</span><div>数字分身<small>和另一个「自己」聊天</small></div></a>
    <a data-p="byst"><span class="ic">⚡</span><div>贾维斯<small>无所不知的私人 AI 管家 · 钢铁侠同款</small></div></a>
    <a data-p="self"><span class="ic">🪞</span><div>认识自己<small>画像 · 时间线 · 记忆搜索</small></div></a>
    <a data-p="others"><span class="ic">👥</span><div>认识他人<small>联系人 · 关系 · 关系网络</small></div></a>
    <a data-p="sim"><span class="ic">🌌</span><div>数字人生<small>虚拟推演 · 永续计划</small></div></a>
    <a data-p="data"><span class="ic">📊</span><div>数据档案<small>原始统计 · 趋势分析</small></div></a>
    <a data-p="sys"><span class="ic">⚙️</span><div>系统设置<small>模型 · 知识库 · 配置</small></div></a>
  </nav>
  <div class="foot">本地运行中<br><b>127.0.0.1:8765</b><br>所有数据留在你的电脑上</div>
</aside>

<div class="wrap">
<div id="topbar">
  <div class="q"><input id="topq" placeholder="搜索联系人、关键词，或直接问我…（回车进入记忆搜索）"></div>
  <div class="dt" id="topdt"></div>
</div>
<main>

<!-- ═══════════ 首页 ═══════════ -->
<section id="pg-home" class="page on">
  <div class="hero">
    <h1 id="greet">你好，万凯。</h1>
    <p id="greet2">今天的你，过得怎么样？</p>
    <div class="rt">过去的每一刻聊天记录<br>都是你人生的注脚</div>
  </div>
  <div id="homeErr"></div>
  <div id="homeBody" class="mut">正在读取你的生活切片…</div>
</section>

<!-- ═══════════ 数字分身(聊天) ═══════════ -->
<section id="pg-twin" class="page chatpg">
  <div class="side">
    <div class="hd"><span id="sidehd">选择联系人（按消息量排序）</span><input id="ctq" placeholder="搜索…" style="width:100%;margin-top:8px"></div>
    <div class="list" id="ctlist"></div>
  </div>
  <div class="chatwrap">
    <div class="modebar">
      <button class="mb on" data-m="dialog">🎭 模拟聊天（你演 ta，分身演我）</button>
      <button class="mb" data-m="ask">🧭 贾维斯提问（第三人称）</button>
      <button class="mb" data-m="eq">💚 高情商练习</button>
      <span class="hint" id="modehint">模拟模式：你在输入框扮演「联系人」（右侧绿泡），分身用万凯的口吻回复（左侧，带 AI 标识）</span>
      <button class="btn gray sm" id="mbMembers" style="display:none">👥 成员性格</button>
      <button class="btn gray sm" id="mbRaw">💬 原始聊天</button>
      <button class="btn gray sm" id="mbSwap" style="display:none" title="互换身份：你演万凯本人，AI 扮演这位联系人">🔄 身份互换</button>
      <button class="btn gray sm" id="clearChat" style="margin-left:auto">🗑 清空对话记忆</button>
    </div>
    <div id="roleBanner"></div>
    <div id="msgs"></div>
    <div class="inrow">
      <button class="chip" id="eqOpenBtn" style="display:none;flex-shrink:0;padding:6px 10px" title="对方还没说过话？填背景+开场草稿，生成高情商开场白">🚀 首次开场</button>
      <button class="chip" id="eqTurnBtn" style="display:none;flex-shrink:0;padding:6px 10px" title="切换这句话由谁说">🎤 她说</button>
      <textarea id="chat-in" placeholder="和你的数字分身聊聊…（Enter 发送，Shift+Enter 换行）"></textarea>
      <button class="btn" id="sendbtn">发送</button>
    </div>
    <div id="eqOpenPanel" style="display:none;padding:12px 18px;background:#fffbe9;border-top:1px solid #f0e0b8">
      <div style="font-size:12.5px;font-weight:700;color:#8a5a00;margin-bottom:6px">🚀 首次开场 · 对方一句话都没说过</div>
      <textarea id="eqOpenBg" style="width:100%;height:50px;font-size:12.5px" placeholder="她的基本背景：认识途径、职业/爱好、你对她哪点有好感…（一两句即可）"></textarea>
      <textarea id="eqOpenMine" style="width:100%;height:50px;font-size:12.5px;margin-top:6px" placeholder="你本来想发的开场白（原话）——高情商版会保留你的真实意图，只升级表达"></textarea>
      <div style="margin-top:8px;display:flex;gap:8px;align-items:center">
        <button class="btn sm" id="eqOpenGo">✨ 生成高情商开场白</button>
        <button class="btn gray sm" id="eqOpenCancel">取消</button>
        <span class="mut">生成后同样可点「🔍 诊断」对比差异</span>
      </div>
    </div>
  </div>
</section>

<!-- ═══════════ 贾维斯问答(独立页, 与全局抽屉共用同一会话) ═══════════ -->
<section id="pg-byst" class="page chatpg">
  <div class="chatwrap">
    <div class="modebar">
      <span class="hint" id="bhint">⚡ 贾维斯 —— 你的私人 AI 管家（钢铁侠同款）：读过你全部聊天记录，紧跟时事政策，能分析局势、沙盘推演。任何困境疑惑直接说，他一步步给你拆解；拿不定的事（要不要/值不值/帮我推演…）自动进入沙盘模式</span>
      <button class="btn gray sm" id="bEqGo" title="高情商练习：她说→你答→看高情商版怎么说">💚 高情商练习</button>
      <button class="btn gray sm" id="bClear" style="margin-left:auto">🗑 清空本会话</button>
    </div>
    <div id="bmsgs"></div>
    <div class="inrow" id="bAskRow">
      <textarea id="bchat-in" placeholder="例如：我和刘炀和Mi谁关系更好？现在裁员形势怎么看？我最近遇到一件事拿不定主意，帮我推演下…（Enter 发送）"></textarea>
      <button class="btn" id="bsendbtn">发送</button>
    </div>
  </div>
</section>

<!-- ═══════════ 认识自己(重构: 首屏认知摘要 + 六大模块 + 记忆搜索) ═══════════ -->
<section id="pg-self" class="page">
  <div class="selfhero">
    <div class="sheb">PERSONAL IDENTITY · 个人认知档案</div>
    <h1>万凯，重新认识自己。</h1>
    <p id="shSummary">从四年的真实交流中，理解自己的性格、行为、关系和人生变化。每个结论都能回到真实聊天记录中验证。</p>
    <div id="shTags" style="margin-top:10px"></div>
    <div class="shops">
      <button class="btn sm" id="genMe">🔄 重新生成画像</button>
      <button class="btn sm" id="genTl">🗓 重新生成时间线</button>
      <button class="btn sm" id="genSk">🛠 重新提炼技能与经历</button>
      <span class="mut" id="shMeta" style="color:#bfe6d4"></span>
    </div>
  </div>
  <div id="selfErr"></div>

  <div class="selfmod"><div class="smhd">01 · 我是什么样的人<span>人格 · 思维 · 表达</span></div>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(280px,1fr))">
      <div class="card"><h3>🧠 性格特点</h3><div id="meTraits" class="mut">加载中…</div></div>
      <div class="card"><h3>🗣 说话方式</h3><div id="meSpeak" class="mut">加载中…</div></div>
      <div class="card"><h3>✨ 优点</h3><div id="mePros" class="mut">加载中…</div></div>
    </div>
  </div>

  <div class="selfmod"><div class="smhd">02 · 我的生活是什么样的<span>兴趣 · 习惯 · 作息</span></div>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(280px,1fr))">
      <div class="card"><h3>🎯 兴趣与生活</h3><div id="meLife" class="mut">加载中…</div></div>
      <div class="card"><h3>🕐 活跃规律</h3><div id="meActive" class="mut">加载中…</div></div>
      <div class="card"><h3>✍ 表达统计<span class="sub">程序统计，非 AI 想象</span></h3><div id="styleBox" class="mut">加载中…</div></div>
    </div>
  </div>

  <div class="selfmod"><div class="smhd">03 · 我是怎样与人相处的<span>不同关系中的自己</span></div>
    <div class="card"><h3>🤝 社交风格</h3><div id="meSocial" class="mut">加载中…</div>
      <div id="styleDiff" style="margin-top:10px"></div>
      <div style="margin-top:12px"><span class="chip" data-go="others">去「认识他人」看关系网络、圈层与每个人聊了什么 →</span></div>
    </div>
  </div>

  <div class="selfmod"><div class="smhd">03.5 · 我会什么、做过什么<span>技能分类 · 这几年做的事（依据日程大事与真实聊天，非 AI 想象）</span></div>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))">
      <div class="card"><h3>🛠 我会的技能<span class="sub">有据可查，没把握的不写</span></h3><div id="skBox" class="mut">加载中…</div></div>
      <div class="card"><h3>📈 一句话</h3><div id="skOne" class="mut">—</div></div>
    </div>
    <div class="card" style="margin-top:12px"><h3>🧾 这几年做的事<span class="sub">按年份 · 详细</span></h3><div id="expBox" class="mut">加载中…</div></div>
  </div>

  <div class="selfmod"><div class="smhd">04 · 这些年我发生了什么变化<span>纵向人生叙事 · 每个事件都有原话依据</span></div>
    <div class="card"><div id="tlBox" class="mut">加载中…</div></div>
  </div>

  <div class="selfmod"><div class="smhd">05 · 我可能没有意识到的自己<span>盲区 · 重复模式 · 值得思考的问题</span></div>
    <div class="card"><div id="meBlind" class="mut">加载中…</div>
      <div style="margin-top:12px" class="orachips">
        <span class="chip" data-ora="我有哪些自己没意识到的行为模式或盲区？">我有哪些盲区？</span>
        <span class="chip" data-ora="我经常说要做、但一直没做的事有哪些？">说过没做的事</span>
        <span class="chip" data-ora="这几年我对哪些事情的看法发生了明显变化？">观点变化</span>
      </div>
      <div class="mut" style="margin-top:6px">这类问题交给贾维斯回答 —— 他会引用你自己的原话。</div>
    </div>
  </div>

  <div class="selfmod"><div class="smhd">06 · 与另一个自己对话<span>贾维斯 · 陪你四年、读过你全部记录的老朋友</span></div>
    <div class="card">
      <div class="mut" style="line-height:1.8">他不打官腔：会引用你自己的原话点醒你，也承认哪些事他「真没印象」。关于你自己、某段关系、某个拿不定的主意，都可以问他。</div>
      <div style="margin-top:12px" class="orachips">
        <span class="chip" data-ora="我是一个怎样的人？">我是一个怎样的人？</span>
        <span class="chip" data-ora="我和谁关系最好？">我和谁关系最好？</span>
        <span class="chip" data-ora="我最近和谁联系变少了？">最近和谁联系少了？</span>
        <span class="chip" data-ora="我身上有哪些自相矛盾的地方？">我的矛盾之处</span>
      </div>
      <button class="btn sm" style="margin-top:12px" onclick="openOracle()">🫧 打开贾维斯对话</button>
    </div>
  </div>

  <div class="selfmod"><div class="smhd">🔎 记忆搜索<span>精确多关键词 + BM25 近似检索 · 点击结果看上下文</span></div>
    <div class="card">
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <input id="mq" placeholder="关键词（可多个，全部命中）" style="flex:1;min-width:200px">
        <select id="mct" style="max-width:180px"><option value="">全部联系人</option></select>
        <input id="mfrom" type="date" style="width:140px"><span class="mut">至</span><input id="mto" type="date" style="width:140px">
        <label class="mut"><input type="checkbox" id="mme"> 只看我发的</label>
        <button class="btn" id="mgo">搜索</button>
        <label class="mut"><input type="checkbox" id="mfuzzy" checked> 命中太少时自动近似检索</label>
      </div>
      <div id="mres" class="mut" style="margin-top:10px">支持精确多关键词 + BM25 近似检索；点击结果可查看前后上下文。</div>
      <div id="mctx"></div>
    </div>
  </div>
</section>

<!-- ═══════════ 认识他人 ═══════════ -->
<section id="pg-others" class="page">
  <h2 class="pt">认识他人 · 关系网络</h2>
  <div class="otabs">
    <div class="tb on" data-t="net">🕸 关系网络</div>
    <div class="tb" data-t="circ">🧭 圈层与变化</div>
    <div class="tb" data-t="ppl">🔎 人物画像</div>
    <div class="tb" data-t="gf">👥 群友提炼</div>
  </div>
  <div id="othErr"></div>
  <div id="tab-gf" style="display:none"></div>
  <div id="tab-net">
    <div class="card" style="padding:10px 14px">
      <div class="years" id="yearChips"></div>
      <div class="mut" style="padding:0 8px 6px">节点大小 = 互动强度 · 颜色 = 圈层（<span style="color:#22a06b">■</span>家人 <span style="color:#3b82f6">■</span>同事/工作 <span style="color:#8b5cf6">■</span>朋友/其他 <span style="color:#e08a00">■</span>其他）· 灰色细线 = 共同群聊（仅代表同群，不代表两人真实认识）· 点击节点查看个人关系网</div>
    </div>
    <div class="netwrap">
      <div id="netbox" class="mut">加载关系图…</div>
      <div id="egobox" style="display:none">点击图中任意联系人，查看 ta 与你的关系详情。</div>
    </div>
  </div>
  <div id="tab-circ" style="display:none"></div>
  <div id="tab-ppl" style="display:none">
    <div class="card">
      <h3>人物画像
        <input id="pplQ" placeholder="🔍 搜人…" style="margin-left:12px;width:110px" title="输入名字过滤下拉列表">
        <select id="pplSel" style="max-width:240px"></select>
        <button class="btn sm" id="genPpl" style="margin-left:auto">生成 / 刷新画像</button>
      </h3>
      <div id="pplBox" class="mut">选择联系人后生成画像（AI 总结你们的关系、话题与相处方式）。</div>
    </div>
  </div>
  <div class="card qabox">
    <h3>🫧 贾维斯<span class="sub">读过你全部聊天记录的老朋友 —— 关系、圈子、拿不定的主意，都可以问他（回答基于程序统计 + 原始记录）</span></h3>
    <div>
      <span class="chip" data-ora="我这四年最重要的朋友有哪些？">最重要的朋友</span>
      <span class="chip" data-ora="谁是我工作圈和朋友圈之间的连接人物？">圈层连接人物</span>
      <span class="chip" data-ora="我和哪些人逐渐疏远了？">逐渐疏远的人</span>
      <span class="chip" data-ora="我最近一年主要和哪些人交流？">最近一年交流</span>
      <span class="chip" data-ora="我最近遇到一件事拿不定主意：（在这里补充事情）。你觉得按万凯的性格他会怎么做？这样做有什么优缺点？有没有什么不妥？">决策咨询：万凯会怎么做</span>
      <span class="chip" data-ora="我打算：（在这里补充你的计划）。你觉得万凯会怎么做？他的做法有什么不妥吗？没有的话就直说，不用硬找。">决策咨询：有不妥吗</span>
    </div>
    <div class="mut" style="margin-top:8px">点击问题会打开右侧「贾维斯」对话抽屉；他会先和你确认涉及的人，再检索真实记录回答。之前单独的关系洞察 Agent 已并入贾维斯。</div>
  </div>
</section>

<!-- ═══════════ 个人记忆页已并入「认识自己」记忆搜索 ═══════════ -->

<!-- ═══════════ 数字人生(模拟推演) ═══════════ -->
<section id="pg-sim" class="page">
  <div class="simhero">
    <div>
      <h1>🌌 数字人生 · 永续计划</h1>
      <p>基于真实人格、关系与记忆的长期模拟实验。现实中的记录会停止更新，但模拟人生可以沿着你的人生轨迹继续向前 —— 每一段虚拟经历都带推演依据与审计结果。</p>
    </div>
    <div class="simstats" id="simKpi"><div class="mut">加载中…</div></div>
  </div>
  <div class="simwarn">⚠ <b>隔离承诺</b>：虚拟内容只存于 个人Agent/simulation/ 目录，绝不写入真实知识库与聊天记录；分身对话默认完全不用虚拟数据 —— 只有当你逐条「批准」某段经历并手动打开下方融合开关时，分身才会参考它，且必带【虚拟推演】标注。虚拟联系人的言行不代表其本人。</div>
  <div class="card simops">
    <h3>🎛 推演控制</h3>
    <div class="oprow">
      <button class="btn simbtn" id="simRun1">推演 1 天</button>
      <button class="btn simbtn" id="simRun7">推演 7 天</button>
      <button class="btn simbtn" id="simRun30">推演 30 天</button>
      <button class="btn gray" id="simAudit">🛡 人格自查</button>
      <button class="btn gray" id="simExport">📦 导出时间线</button>
      <label class="simmerge"><input type="checkbox" id="simMerge"> 允许已批准的虚拟经历进入分身对话（默认关闭）</label>
    </div>
    <div id="simMsg" class="mut" style="margin-top:8px"></div>
  </div>
  <div class="card">
    <h3>🧬 人生模拟时间线<span class="sub" id="simCnt"></span></h3>
    <div id="simTl" class="mut">尚未开始推演。点击上方「推演」启动虚拟日历。</div>
  </div>
  <div class="card" id="simAuditCard" style="display:none">
    <h3>🛡 自查报告<span class="sub" id="simAuditAt"></span></h3>
    <div id="simAuditBody"></div>
  </div>
</section>

<!-- ═══════════ 数据档案 ═══════════ -->
<section id="pg-data" class="page">
  <h2 class="pt">数据档案 <span class="mut" style="font-size:12px;font-weight:400">原始统计与趋势（已从首页移出）</span></h2>
  <div id="dataErr"></div>
  <div id="dataBody">加载中…</div>
</section>

<!-- ═══════════ 系统设置 ═══════════ -->
<section id="pg-sys" class="page">
  <h2 class="pt">系统设置</h2>
  <div class="card" style="max-width:640px">
    <h3>🔄 聊天记录同步</h3>
    <div id="pipeBox" class="mut">加载中…</div>
    <div id="pipeLog" class="mut" style="margin-top:10px;display:none;background:#f7f8fa;border-radius:9px;padding:10px 12px;font-size:12px;max-height:260px;overflow-y:auto;line-height:1.8;font-family:Consolas,monospace"></div>
    <div style="margin-top:12px">
      <button class="btn" id="pipeRun">🔄 一键同步新聊天记录</button>
      <span class="mut" style="margin-left:10px;font-size:12px">第1步增量导出(只追加新消息) → 第2步自动重建知识库</span>
    </div>
  </div>
  <div class="card" style="max-width:640px">
    <h3>🤖 模型配置</h3>
    <div id="cfgBox" class="mut">加载中…</div>
  </div>
  <div class="card" style="max-width:640px">
    <h3>🧑‍🏫 人工纠正记忆<span class="sub" id="fbCnt"></span></h3>
    <div id="fbBox" class="mut">加载中…</div>
  </div>
  <div class="card" style="max-width:640px">
    <h3>🔐 隐私说明</h3>
    <div class="mut" style="line-height:1.9">
      · 全部聊天记录、知识库、缓存都在本机 <b>Desktop\WeChatExport</b> 目录，不上传任何服务器。<br>
      · 调用 AI 时，只发送当前问题 + 最近几轮对话 + 检索到的少量相关片段。<br>
      · 「数字分身」模式发送给 AI 的历史最近 8 条；「记忆分析」模式最多 30 条。<br>
      · 清空对话记忆只影响界面上下文，不会删除任何本地记录。
    </div>
  </div>
</section>

</main>
</div>

<!-- ═══════════ 贾维斯抽屉(由各页提问 chips / ego 按钮唤起; 平时从左侧菜单进贾维斯页) ═══════════ -->
<div id="oraMask"></div>
<aside id="oraDrawer">
  <div class="oraHd">
    <div><b>🫧 贾维斯</b><span class="sub2">陪你四年 · 读过你全部聊天记录</span></div>
    <span id="oraClose" style="cursor:pointer;font-size:18px;opacity:.85">✕</span>
  </div>
  <div id="dmsgs"><div class="mut" style="text-align:center;margin-top:24px">问问你的朋友吧 ——<br>关于你自己、某段关系、或一个拿不定的主意。<br><span style="font-size:11px">他会先和你确认涉及的人，再检索真实记录回答</span></div></div>
  <div class="inrow" style="padding:10px 14px">
    <textarea id="dchat-in" placeholder="例如：我和桃姐之间有什么梗？我最近是不是疏远了谁？"></textarea>
    <button class="btn" id="dsendbtn">发送</button>
  </div>
</aside>
</div>
</template>

<script setup>
import { onMounted } from 'vue'
import * as echarts from 'echarts'

onMounted(() => {
const $=s=>document.querySelector(s), $$=s=>document.querySelectorAll(s);
const esc=s=>(s==null?'':String(s)).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
/* 微信内置表情代码 → emoji 映射; 未识别的 [xx] 保持原样 */
const FACE={'微笑':'🙂','撇嘴':'😞','色':'😍','发呆':'😐','得意':'😁','流泪':'😢','害羞':'😊',
'闭嘴':'😶','睡':'😴','大哭':'😭','尴尬':'😬','发怒':'😠','调皮':'😝','呲牙':'😁','惊讶':'😲',
'难过':'🙁','酷':'😎','冷汗':'😓','抓狂':'😫','吐':'🤮','偷笑':'🤭','可爱':'🥰','白眼':'🙄',
'傲慢':'😏','饿':'😩','困':'😪','惊恐':'😨','流汗':'😅','憨笑':'😆','悠闲':'😌','奋斗':'💪',
'咒骂':'😤','疑问':'❓','嘘':'🤫','晕':'😵','折磨':'😖','骷髅':'💀','敲打':'👊','再见':'👋',
'擦汗':'😰','抠鼻':'👃','鼓掌':'👏','坏笑':'😈','右哼哼':'😒','鄙视':'😒','委屈':'🥺',
'快哭了':'🥹','阴险':'😏','亲亲':'😗','吓':'😱','可怜':'😥','菜刀':'🔪','西瓜':'🍉','啤酒':'🍺',
'篮球':'🏀','乒乓':'🏓','咖啡':'☕','饭':'🍚','猪头':'🐷','玫瑰':'🌹','凋谢':'🥀','嘴唇':'👄',
'爱心':'❤️','心碎':'💔','蛋糕':'🍰','强':'👍','弱':'👎','握手':'🤝','胜利':'✌️','抱拳':'🤲',
'勾引':'👉','拳头':'✊','OK':'👌','合十':'🙏','飞吻':'😘','便便':'💩','月亮':'🌙','太阳':'☀️',
'庆祝':'🎉','红包':'🧧','烟花':'🎆','鞭炮':'🧨','旺柴':'🐶','裂开':'🫠','吃瓜':'🍉','加油':'🔥',
'转圈':'💫','闪电':'⚡','炸弹':'💣','足球':'⚽','礼物':'🎁','拥抱':'🤗','面条':'🍜','汉堡':'🍔',
'冰淇淋':'🍦','鸡蛋':'🥚','呕吐':'🤮','吓死我了':'😱','让我看看':'👀','翻滚':'🌀'};
const wxface=t=>String(t).replace(/\[([^\[\]]{1,6})\]/g,(m,k)=>FACE[k]?`<span class="wc">${FACE[k]}</span>`:m);
const CC={'家人':'#22a06b','同事/工作':'#3b82f6','朋友/其他':'#8b5cf6','其他':'#e08a00'};
const CT={'家人':'g','同事/工作':'b','朋友/其他':'p','其他':'o'};
async function api(p,o){const r=await fetch(p,o);let j;try{j=await r.json()}catch(e){throw new Error('HTTP '+r.status)}
 if(!r.ok||j.error)throw new Error(j.error||('HTTP '+r.status));return j}
const post=(p,b)=>api(p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});

/* ───── 导航 ───── */
const LOADED={};
const LOADERS={home:loadHome,twin:loadTwin,self:loadSelf,others:loadOthers,data:loadData,sys:loadSys,sim:loadSim};
function go(p,sub){
  $$('#nav a').forEach(a=>a.classList.toggle('on',a.dataset.p===p));
  $$('.page').forEach(s=>s.classList.toggle('on',s.id==='pg-'+p));
  navDot(p,false);   // 进入页面即清除该页的红点提醒
  if(!LOADED[p]){LOADED[p]=true;LOADERS[p](sub).catch(e=>showErr('pg-'+p,e))}
  else if(sub!==undefined&&AFTERS[p])AFTERS[p](sub);
}
const AFTERS={};
function showErr(id,e){const box=document.getElementById(id);if(!box)return;
  const d=document.createElement('div');d.className='err';d.textContent='加载失败: '+e.message;box.prepend(d)}
$$('#nav a').forEach(a=>a.onclick=()=>go(a.dataset.p));
$('#topq').addEventListener('keydown',e=>{if(e.key==='Enter'){const q=e.target.value.trim();if(!q)return;
  go('self');$('#mq').value=q;doSearch();}});   // 个人记忆页已并入认识自己

/* ───── 全局提醒: 顶部 toast + 侧栏菜单红点(长任务完成后提示) ───── */
function toast(t){
  const d=document.createElement('div');d.textContent=t;
  d.style.cssText='position:fixed;left:50%;top:14%;transform:translateX(-50%);background:#1c1e21;color:#fff;padding:8px 18px;border-radius:9px;font-size:13px;z-index:9999;box-shadow:0 4px 16px rgba(0,0,0,.3);max-width:70vw;white-space:pre-wrap';
  document.body.appendChild(d);setTimeout(()=>d.remove(),3200);
}
function navDot(p,on){
  const a=document.querySelector(`#nav a[data-p="${p}"]`);if(!a)return;
  let d=a.querySelector('.ndot');
  if(on){if(!d){d=document.createElement('span');d.className='ndot';a.appendChild(d)}}
  else if(d)d.remove();
}

/* ───── 复制工具 ───── */
function copyName(n){
  const done=()=>{const t=document.createElement('div');
    t.textContent='已复制「'+n+'」';
    t.style.cssText='position:fixed;left:50%;top:14%;transform:translateX(-50%);background:#1c1e21;color:#fff;padding:7px 16px;border-radius:9px;font-size:13px;z-index:9999;box-shadow:0 4px 16px rgba(0,0,0,.3)';
    document.body.appendChild(t);setTimeout(()=>t.remove(),1600)};
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(n).then(done).catch(()=>fallbackCopy(n,done))}
  else fallbackCopy(n,done);
}
function fallbackCopy(n,done){
  const ta=document.createElement('textarea');ta.value=n;ta.style.cssText='position:fixed;opacity:0';
  document.body.appendChild(ta);ta.select();
  try{document.execCommand('copy');done()}catch(e){}
  ta.remove();
}

/* ───── 长任务等待计时: 让静态等待文案显示已等待秒数 ───── */
let _WT=null;
function startWait(el,txt){
  const t0=Date.now();
  const tick=()=>{if(!el||!el.isConnected){stopWait();return}
    el.innerHTML=esc(txt)+' <b style="color:#8a8f99">… '+((Date.now()-t0)/1000|0)+'s</b>'};
  tick();stopWait();_WT=setInterval(tick,1000);
}
function stopWait(){if(_WT){clearInterval(_WT);_WT=null}}

/* ───── 首页: 数字人生观察室 ───── */
function showRecent(name){
  const mask=document.createElement('div');
  mask.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:999;display:flex;align-items:center;justify-content:center';
  const box=document.createElement('div');
  box.style.cssText='background:#f5f6f7;border-radius:14px;width:min(560px,92vw);max-height:76vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 8px 40px rgba(0,0,0,.25)';
  box.innerHTML=`<div style="padding:12px 16px;background:#ededed;border-bottom:1px solid #e0e0e0;display:flex;justify-content:space-between;align-items:center"><b style="font-size:14px">${esc(name)} · 最近聊天 <span title="复制名称" style="cursor:pointer;font-size:12px" onclick="copyName('${esc(name).replace(/'/g,"\\'")}')">📋</span></b><span style="cursor:pointer;color:#888;font-size:18px;line-height:1" onclick="this.closest('div[style*=fixed]').remove()">✕</span></div><div class="rcbody" style="overflow-y:auto;padding:14px 18px;display:flex;flex-direction:column;gap:10px"><div class="mut">加载中…</div></div>`;
  mask.appendChild(box);
  mask.onclick=e=>{if(e.target===mask)mask.remove()};
  document.body.appendChild(mask);
  api('/api/agent/recent_chat?name='+encodeURIComponent(name)).then(r=>{
    const body=box.querySelector('.rcbody');
    if(!r.msgs||!r.msgs.length){body.innerHTML='<div class="mut">没有找到聊天记录</div>';return}
    const head=`<div class="mut" style="text-align:center">${r.total} 条消息 · ${r.span[0]||''} ~ ${r.span[1]||''} · 显示最近 ${r.msgs.length} 条</div>`;
    body.innerHTML=head+r.msgs.map(m=>{
      const me=m.s==='我';
      return `<div style="display:flex;flex-direction:${me?'row-reverse':'row'};gap:8px;align-items:flex-start">
        <div class="av" style="${me?'background:var(--g)':'background:#5b8def'}">${me?'凯':esc((m.s||'?')[0])}</div>
        <div style="max-width:75%"><div class="mut" style="text-align:${me?'right':'left'}">${m.t.slice(5,16)} · ${me?'我':esc(m.s)}</div>
        <div style="background:${me?'#95ec69':'#fff'};border-radius:10px;padding:7px 11px;font-size:13px;line-height:1.5;white-space:pre-wrap;word-break:break-word;margin-top:2px;box-shadow:0 1px 2px rgba(0,0,0,.05)">${wxface(esc(m.c))}</div></div></div>`;
    }).join('');
    body.scrollTop=body.scrollHeight;
  }).catch(e=>{box.querySelector('.rcbody').innerHTML='<div class="err">'+esc(e.message)+'</div>'});
}
async function loadHome(){
  const now=new Date(),h=now.getHours();
  $('#greet').textContent=(h<6?'夜深了':h<12?'早上好':h<14?'中午好':h<18?'下午好':'晚上好')+'，万凯。';
  const [ins,ls]=await Promise.all([api('/api/agent/home/insights'),api('/api/agent/life_stats')]);
  $('#topdt').textContent=ins.date+' · 星期'+ins.weekday;
  const t=(ins.topics||[]).slice(0,5).map(t=>t.word).join(' · ');
  const ln=ins.last_night;
  const rec=(ins.recent||[]).slice(0,3);
  const reN=(ins.reactivated||[]).length, faN=(ins.fading||[]).length;
  const late=(ls.late_sessions||[])[0];
  let html=`
  <div class="slice4">
    <div class="sl g"><div class="bigic">🌙</div><div class="slbd"><div class="tt">${ln?esc(ln.label||'昨晚最后聊天'):'昨晚最后聊天'}</div>
      ${ln?`<div class="big">${esc(ln.name)} <span style="font-size:12px;color:#57606d">${ln.time}</span></div>
      <div class="sub2">${esc(ln.preview)||'(图片/表情)'}<br>${ln.date.slice(5)} 当天聊了 ${ln.n} 条</div>`
      :'<div class="sub2">近几天没有私聊记录</div>'}</div>
    </div>
    <div class="sl b"><div class="bigic">🔥</div><div class="slbd"><div class="tt">最近联系最多</div>
      ${rec.length?rec.map(r=>`<div class="sub2"><b>${esc(r.name)}</b> · 近7天 ${r.n7} 条</div>`).join('')
        :'<div class="sub2">近7天暂无私聊</div>'}</div>
    </div>
    <div class="sl o"><div class="bigic">💬</div><div class="slbd"><div class="tt">近期常聊话题</div>
      <div style="margin-top:9px">${(ins.topics||[]).slice(0,6).map(x=>`<span class="tag" style="background:#fff;color:#8a5a00">${esc(x.word)}</span>`).join(' ')||'<div class="sub2">暂无</div>'}</div>
    </div></div>
    <div class="sl p"><div class="bigic">🔔</div><div class="slbd"><div class="tt">关系变化提醒</div>
      <div class="big">${reN+faN} 位联系人</div>
      <div class="sub2">${reN} 段关系重新活跃 · ${faN} 人正在逐渐疏远</div></div>
    </div>
  </div>
  <div class="cols"><div>`;
  html+=`
  <div class="card"><h3>02 · 最近发生了什么<span class="sub">近几日聊得最多的人与最后一条消息（程序提取，非 AI 想象）</span></h3>
    ${(ins.life_cards||[]).map(c=>`
      <div class="lc"><div class="av" style="background:${({'家人':'#22a06b','同事/工作':'#3b82f6','朋友/其他':'#8b5cf6'}[c.circle]||'#e08a00')}">${esc((c.name||'微')[0])}</div><div class="d">${c.date.slice(5)}<br>星期${c.weekday}</div>
        <div style="flex:1;min-width:0"><div class="b">${esc(c.name)} <span class="tag ${CT[c.circle]||''}">${c.circle}</span>
        <span class="mut" style="margin-left:6px">${c.n} 条 · 当天共 ${c.total} 条/${c.people} 人 · 最后 ${c.time}</span></div>
        <div class="pv">${esc(c.preview)}</div></div></div>`).join('')||'<div class="mut">近几天没有记录</div>'}
  </div>
  <div class="card"><h3>03 · 我身边的人<span class="sub">点击进入关系网络</span></h3>
    <div class="liferow" onclick="go('others')"><div class="ic" style="background:var(--cg)">💚</div>
      <div><b>一直保持联系的人</b><div class="desc">连续五年每年都有交流的长期关系（${(ins.lifers||[]).length} 人）</div></div>
      <div class="names">${(ins.lifers||[]).slice(0,4).map(l=>esc(l.name)).join(' · ')}</div></div>
    <div class="liferow" onclick="go('others','circ')"><div class="ic" style="background:var(--co)">📉</div>
      <div><b>最近逐渐疏远的人</b><div class="desc">相比峰值年，互动明显减少</div></div>
      <div class="names">${(ins.fading||[]).slice(0,3).map(f=>`<span style="cursor:pointer;border-bottom:1px dashed #999" onclick="showRecent('${esc(f.name).replace(/'/g,"\\'")}')">${esc(f.name)}</span>`).join(' · ')}</div></div>
    <div class="liferow" onclick="go('others','circ')"><div class="ic" style="background:var(--cb)">✨</div>
      <div><b>重新活跃的关系</b><div class="desc">沉寂多时后重新开始交流（按恢复稳定度分级）</div></div>
      <div class="names">${(ins.reactivated||[]).slice(0,3).map(r=>`<span style="cursor:pointer;border-bottom:1px dashed #999" onclick="showRecent('${esc(r.name).replace(/'/g,"\\'")}')">${esc(r.name)}</span>(${r.level||'已恢复'}·断联${r.gap_days}天)`).join(' · ')}</div></div>
    <div class="liferow" onclick="go('others')"><div class="ic" style="background:var(--cp)">🕸</div>
      <div><b>我的社交圈</b><div class="desc">${Object.entries(ins.circles||{}).map(([k,v])=>k+' '+v['人数']+'人').join(' · ')}</div></div>
      <div class="names">查看关系网络 →</div></div>
  </div>
  <div class="card"><h3>05 · 问问贾维斯<span class="sub">陪你四年、读过你全部聊天记录的老朋友</span></h3>
    <div class="chip" data-ask="我是什么样的人？">我是什么样的人？</div>
    <div class="chip" data-ask="我和谁关系最好？">我和谁关系最好？</div>
    <div class="chip" data-ask="这几年我有什么变化？">这几年我有什么变化？</div>
    <div class="chip" data-ask="我最近是不是和朋友联系少了？">最近和朋友联系少了吗？</div>
    <div class="chip" data-ask="我最近在关注什么？">我最近在关注什么？</div>
  </div>
  </div><div>`;
  html+=`
  <div class="card"><h3>04 · 最近的你</h3>
    ${late?`<div class="rrow"><b>🌙 最近一次深夜长聊</b><span>${esc(late.ct)} ${late.start.slice(5)} → ${late.end.slice(11)} · ${late.n}条</span></div>`:''}
    ${(ls.fading||[]).slice(0,3).map(f=>`<div class="rrow"><span>📉 ${esc(f.name)}</span><span class="mut">峰值${f.base}条 → 今年${f.now}条</span></div>`).join('')}
    ${(ls.bridges||[]).slice(0,3).map(b=>`<div class="rrow"><span>🌉 ${esc(b.name)}</span><span class="mut">连接 ${b.circles.join('/')}</span></div>`).join('')}
    <div class="mut" style="margin-top:8px">数据每天随聊天记录自动更新 · AI 深度观察可在「认识自己」生成画像后查看</div>
  </div>
  <div class="card"><h3>🏷 近期生活关键词</h3>
    <div>${(ins.topics||[]).map(x=>`<span class="chip" style="cursor:default">${esc(x.word)}<span class="mut"> ${x.n}</span></span>`).join('')}</div>
  </div>
  </div></div>`;
  $('#homeBody').innerHTML=html;
  $$('#homeBody .chip[data-ask]').forEach(c=>c.onclick=()=>openOracle(c.dataset.ask));
}

/* ───── 数字人生(模拟推演) ───── */
async function loadSim(){
  try{
    const [st,tl]=await Promise.all([api('/api/agent/sim/status'),api('/api/agent/sim/timeline')]);
    renderSim(st,tl);
  }catch(e){$('#simMsg').textContent='⚠ '+e.message}
}
function renderSim(st,tl){
  $('#simKpi').innerHTML=`
    <div class="sst"><div class="v">${st.sim_date?st.sim_date.split('-').join('.'):('待启动')}</div><div class="t">模拟时间</div></div>
    <div class="sst"><div class="v">${(st.last_real_date||'').split('-').join('.')}</div><div class="t">现实数据截止</div></div>
    <div class="sst"><div class="v">${st.count}</div><div class="t">虚拟经历</div></div>
    <div class="sst"><div class="v">${st.approved}</div><div class="t">已批准融合</div></div>
    <div class="sst"><div class="v">${st.audit.at?(st.audit.personality_ok?'良好':'需关注'):'待评估'}</div><div class="t">人格一致性</div></div>`;
  $('#simMerge').checked=!!st.merge;
  $('#simCnt').textContent=`共 ${tl.total} 条（显示最近 ${tl.entries.length} 条）`;
  $('#simTl').innerHTML=tl.entries.length?tl.entries.slice().reverse().map(e=>{
    if(e.kind==='quiet')return `<div class="sime quiet">📅 <span class="dt2">${e.date}</span> · 平静的一天（无特别交流）</div>`;
    const fl=e.flags&&e.flags.length?`<div class="warn">⚠ ${e.flags.map(esc).join('；')}</div>`:'';
    const ms=(e.messages||[]).map(m=>`<div class="m"><b>${esc(m.speaker)}:</b> ${wxface(esc(m.content))}</div>`).join('');
    const ap=e.approved?'<span class="ap">已批准融合</span>':'';
    const ops=`<div class="ops2" style="margin-top:8px">
      <button class="btn sm gray" onclick="simApprove('${e.id}',${!e.approved})">${e.approved?'撤销批准':'✅ 批准融合'}</button>
      <button class="btn sm gray" onclick="simDel('${e.id}')">删除</button></div>`;
    return `<div class="sime">
      <div><span class="dt2">${e.date}</span> <span class="who">与 ${esc(e.contact||'—')}</span>
        <span class="tag ${CT[e.circle]||''}" style="margin-left:6px">${e.kind==='event'?'事件':'日常'}</span>${ap}</div>
      <div style="margin-top:4px">${esc(e.summary)}</div>${ms}${fl}
      ${(e.basis||[]).length?`<div class="bs">🔗 依据(真实资料): ${e.basis.map(esc).join(' ；')}</div>`:'<div class="bs warn">⚠ 无推演依据</div>'}
      ${ops}</div>`;
  }).join(''):'<div class="mut">尚未开始推演。点击上方「推演」启动虚拟日历。</div>';
  if(st.audit.at){
    $('#simAuditCard').style.display='';$('#simAuditAt').textContent=st.audit.at;
    $('#simAuditBody').innerHTML=`<div>${st.audit.personality_ok?'✅ 人格一致性: 良好':'⚠ 人格一致性: 需要关注'}</div>
      <div class="mut">${st.audit.conflicts?('发现 '+st.audit.conflicts+' 处与真实事实的潜在冲突'):'未发现事实冲突'}</div>
      <div class="mut" style="margin-top:6px">${esc(st.audit.note||'')}</div>`;
  }
}
async function simRun(days){
  $$('.simbtn').forEach(b=>b.disabled=true);
  $('#simMsg').textContent=`⏳ 正在推演 ${days} 天（AI 生成中，可能需要 1-2 分钟，请勿关闭页面）…`;
  const _sw=$('#simMsg'),_tw=`⏳ 正在推演 ${days} 天（AI 生成中，可能需要 1-2 分钟，请勿关闭页面）`;
  startWait({isConnected:true,innerHTML:'',set innerHTML(v){_sw.textContent=v}},_tw);
  try{const r=await post('/api/agent/sim/step',{days});
    stopWait();$('#simMsg').textContent=`✅ 已推进虚拟日历到 ${r.sim_date}，新增 ${r.added} 条虚拟经历（均未批准，需你逐条确认才会用于分身）`;
    if(PAGE()!=='sim'){navDot('sim',true);toast(`🌌 推演完成：已推进到 ${r.sim_date}，新增 ${r.added} 条虚拟经历`)}
  }catch(e){stopWait();$('#simMsg').textContent='⚠ '+e.message;if(PAGE()!=='sim'){navDot('sim',true);toast('⚠ 推演失败: '+e.message)}}
  $$('.simbtn').forEach(b=>b.disabled=false);loadSim();
}
async function simApprove(id,ok){try{await post('/api/agent/sim/approve',{id,ok})}catch(e){}loadSim()}
async function simDel(id){try{await post('/api/agent/sim/delete',{id})}catch(e){}loadSim()}
$('#simRun1').onclick=()=>simRun(1);$('#simRun7').onclick=()=>simRun(7);$('#simRun30').onclick=()=>simRun(30);
$('#simAudit').onclick=async()=>{$('#simAudit').disabled=true;startWait($('#simMsg'),'⏳ AI 正在用真实事实反查虚拟经历');
  try{const r=await post('/api/agent/sim/audit',{});
    let t='✅ 自查完成: '+(r.note||'');
    if(r.conflicts&&r.conflicts.length)t+=`（${r.conflicts.length} 处冲突: ${r.conflicts.map(c=>c.id).join(', ')}）`;
    stopWait();$('#simMsg').textContent=t;
    if(PAGE()!=='sim'){navDot('sim',true);toast('🛡 人格自查完成，点击左侧「数字人生」查看结论')}
  }catch(e){stopWait();$('#simMsg').textContent='⚠ '+e.message;if(PAGE()!=='sim'){navDot('sim',true);toast('⚠ 自查失败: '+e.message)}}
  $('#simAudit').disabled=false;loadSim()};
$('#simExport').onclick=async()=>{try{const r=await post('/api/agent/sim/export',{});
  $('#simMsg').innerHTML=`✅ 已导出: <b>${esc(r.file)}</b>（个人Agent/simulation/exports/）`}catch(e){$('#simMsg').textContent='⚠ '+e.message}};
$('#simMerge').onchange=e=>post('/api/agent/sim/config',{merge:e.target.checked}).then(()=>{
  $('#simMsg').textContent=e.target.checked
    ?'⚠ 已开启融合: 分身对话将参考「已批准」的虚拟经历（必带虚拟推演标注）；关闭即恢复纯真实模式'
    :'已关闭融合: 分身只使用真实记忆';
}).catch(()=>{});

/* ───── 数字分身(聊天) ───── */
let CONTACTS=[],STRANGERS=[],CUR='新朋友',MODE='dialog',SENDING=false;
/* ───── 高情商练习模式: 发展对象列表/会话与主功能完全隔离 ───── */
let EQCUR='',EQTURN='girl',EQSESS={};
let EQCONTACTS=(()=>{try{return JSON.parse(localStorage.getItem('eqContacts')||'[]')}catch(e){return[]}})();
const eqSaveCts=()=>{try{localStorage.setItem('eqContacts',JSON.stringify(EQCONTACTS))}catch(e){}};
const eqSess=c=>{if(!EQSESS[c])EQSESS[c]=[];return EQSESS[c]};   // 由后端 cache/eq_chats 异步填充
const eqSave=c=>{try{localStorage.setItem('eqSess_'+c,JSON.stringify(eqSess(c).slice(-200)))}catch(e){}};
let DIR='A';   // 模拟模式方向: A=你演联系人/分身演万凯, B=身份互换(你演万凯本人/AI演联系人, 需先塑造画像)
const dkey=()=>'twinDir_'+CUR;
const dirLoad=()=>{try{return localStorage.getItem(dkey())==='B'?'B':'A'}catch(e){return 'A'}};
const dirSave=()=>{try{localStorage.setItem(dkey(),DIR)}catch(e){}};
const dn=n=>String(n).replace(/^陌生·/,'');   // 陌生访客显示名
let SESSIONS={};   // key=联系人|模式 → [{who,text,anl}] —— localStorage 持久化, F5/重开浏览器不丢
const skeyOf=(c,m,d)=>c+'|'+m+((m==='dialog'&&d==='B')?'|B':'');
const sessFor=(c,m,d)=>{const k=skeyOf(c,m,d);if(!SESSIONS[k]){
  try{SESSIONS[k]=JSON.parse(localStorage.getItem('twin_'+k)||'[]')}
  catch(e){SESSIONS[k]=[]}
  }return SESSIONS[k]};
const skey=()=>skeyOf(CUR,MODE,DIR);
const curSess=()=>sessFor(CUR,MODE,DIR);
const ssaveFor=(c,m,d)=>{try{localStorage.setItem('twin_'+skeyOf(c,m,d),JSON.stringify(sessFor(c,m,d).slice(-200)))}catch(e){}};  // 每会话最多留 200 条防膨胀
const ssave=()=>ssaveFor(CUR,MODE,DIR);
/* 向指定会话写入消息(不经 UI): AI 回复期间用户切走联系人时, 回复仍归位到原会话 */
function pushTo(c,m,d,who,text,anlHTML,extra){
  const msg=Object.assign({who,text,anl:anlHTML||null},extra||{});
  sessFor(c,m,d).push(msg);ssaveFor(c,m,d);}
const ISG=()=>{const c=CONTACTS.find(x=>x['姓名']===CUR);return !!(c&&c['类别']==='群聊')};
async function loadTwin(){
  if(!CONTACTS.length){
    const d=await api('/api/agent/contacts');
    CONTACTS=(d.contacts||[]).sort((a,b)=>(a['类别']===b['类别']?(b['总消息']||0)-(a['总消息']||0):(a['类别']==='私聊'?-1:1)));
    if(MODE!=='eq')renderCtList('');   // 从贾维斯页跳入高情商模式时, 不要用联系人列表覆盖发展对象侧栏
    $('#ctq').oninput=e=>renderCtList(e.target.value.trim());
  }
  const sel=$('#pplSel');
  if(sel&&sel.options.length<=1){CONTACTS.forEach(c=>{const o=document.createElement('option');o.value=o.textContent=c['姓名'];sel.appendChild(o)})}
}
function renderCtList(q){
  const all=[...STRANGERS.map(n=>({姓名:n,总消息:'访客'})),...CONTACTS];
  const list=all.filter(c=>!q||dn(c['姓名']).toLowerCase().includes(q.toLowerCase()));
  $('#ctlist').innerHTML=`<div class="it" id="ctAdd" style="color:#8b5cf6;font-weight:600">🌑 发起陌生访客对话…</div>`
    +(list.map(c=>{
      const stranger=c['姓名'].startsWith('陌生·');
      const isG=c['类别']==='群聊';
      return `<div class="it ${c['姓名']===CUR?'on':''}" data-n="${esc(c['姓名'])}">
    <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="双击复制名称" ondblclick="copyName('${esc(c['姓名']).replace(/'/g,"\\'")}')">${stranger?'🌑 ':isG?'👥 ':''}${esc(dn(c['姓名']))}</span>
    <span class="n">${typeof c['总消息']==='number'?((c['总消息']||0)>=10000?(c['总消息']/10000).toFixed(1)+'w':c['总消息']):c['总消息']}</span></div>`;
    }).join('')||'<div class="mut" style="padding:10px">无匹配联系人</div>');
  $$('#ctlist .it').forEach(el=>el.onclick=()=>{
    if(el.id==='ctAdd'){
      const n=(prompt('这位陌生访客叫什么名字？','')).trim();
      if(!n)return;
      CUR='陌生·'+n.slice(0,20);
      if(!STRANGERS.includes(CUR))STRANGERS.unshift(CUR);
      renderCtList($('#ctq').value.trim());renderMsgs();
      sysTip(`陌生访客「${dn(CUR)}」已上线 · 你在输入框扮演 ta，分身将第一次回应这位陌生人（基于你的真实人格，对陌生人保持距离感，不泄露朋友隐私）`);
      return;
    }
    CUR=el.dataset.n;DIR=dirLoad();renderCtList($('#ctq').value.trim());renderMsgs();setPlaceholder();updateRoleBanner();
    sysTip(MODE==='dialog'
      ?(ISG()?`已切换到群「${dn(CUR)}」· 群聊模拟：你以万凯身份在群里发消息，主要成员将按各自性格冒泡（可点「👥 成员性格」查看分析）`
        :DIR==='B'
        ?`已切换到「${dn(CUR)}」· 身份互换：你是万凯本人，对面是 ta 的 AI 分身`
        :`已切换到「${dn(CUR)}」· 模拟模式：你在输入框扮演 ${dn(CUR)}，分身用万凯的口吻回复`)
      :`已切换到「${dn(CUR)}」· 贾维斯模式：以第三人称分析你和 ${dn(CUR)} 的关系`,'role')});
}
function setPlaceholder(){
  if(MODE==='eq'){updateEqUI();return}
  $('#chat-in').placeholder=MODE==='dialog'
    ?(ISG()?'在群里发条消息，看谁冒泡…（Enter 发送）'
      :DIR==='B'?'以万凯本人的身份说句话…（Enter 发送）':`以「${dn(CUR)}」的身份给分身发条消息…（Enter 发送）`)
    :'以贾维斯身份提问，例如：我和 ta 之间有什么梗或暗号？';
}
/* ───── 高情商练习: 三方对话(她→你的原话→高情商版) + 诊断 ───── */
function pushEq(c,msg){eqSess(c).push(msg);eqSave(c);
  if(MODE==='eq'&&EQCUR===c){appendDom(msg);$('#msgs').scrollTop=1e9}}
function setEqTurn(t){EQTURN=t;updateEqUI()}
function updateEqUI(){
  const btn=$('#eqTurnBtn'),inp=$('#chat-in'),ob=$('#eqOpenBtn');
  btn.style.display=MODE==='eq'?'':'none';
  if(ob)ob.style.display=MODE==='eq'?'':'none';
  if(MODE!=='eq')return;
  btn.textContent=EQTURN==='girl'?'🎤 她说':'💬 我来答';
  btn.style.background=EQTURN==='girl'?'#efe7fb':'';
  inp.placeholder=EQTURN==='girl'
    ?`替「${EQCUR||'她'}」说一句话…（Enter 发送；点左侧按钮可切换说话人）`
    :'你本来想回什么？发送后高情商版分身同时给出它的回复（Enter）';
}
function renderEqList(q,qadd){
  const list=EQCONTACTS.filter(c=>!q||c.toLowerCase().includes(q.toLowerCase()));
  $('#sidehd').textContent='发展对象（高情商练习）';
  $('#ctlist').innerHTML=`<div class="it" id="eqAdd" style="color:#b07a10;font-weight:600">➕ 添加发展对象…</div>`
    +(qadd?`<div style="padding:4px 6px"><input id="eqNew" placeholder="称呼/备注名, 回车确认" maxlength="20"
      style="width:100%;font-size:12px;padding:6px 9px"></div>`:'')
    +(list.map(c=>`<div class="it ${c===EQCUR?'on':''}" data-n="${esc(c)}">
      <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">💚 ${esc(c)}</span>
      <span class="n" data-del="${esc(c)}" title="删除该对象及练习记录" style="cursor:pointer;color:#d98a8a">×</span></div>`).join('')
    ||(qadd?'':'<div class="mut" style="padding:10px">还没有发展对象<br>点击上方「➕ 添加」开始练习：<br>她说 → 你答 → 看高情商版怎么说</div>'));
  $$('#ctlist .it').forEach(el=>el.onclick=async()=>{
    if(el.id==='eqAdd'){renderEqList($('#ctq').value.trim(),true);$('#eqNew')&&$('#eqNew').focus();return}
    if(el.dataset.del){ // 删除对象(×)
      const n=el.dataset.del;
      if(!confirm(`删除发展对象「${n}」？后端练习记忆会一并清空`))return;
      EQCONTACTS=EQCONTACTS.filter(x=>x!==n);eqSaveCts();
      try{await post('/api/agent/eq/clear',{contact:n})}catch(e){}
      delete EQSESS[n];try{localStorage.removeItem('eqSess_'+n)}catch(e){}
      if(EQCUR===n){EQCUR='';try{localStorage.setItem('eqCur','')}catch(e){}renderMsgs()}
      renderEqList($('#ctq').value.trim());return;
    }
    EQCUR=el.dataset.n;try{localStorage.setItem('eqCur',EQCUR)}catch(e){}
    renderEqList($('#ctq').value.trim());renderMsgs();
    sysTip(`💚 已切换到「${EQCUR}」· 她说一句，你回一句，高情商版同步给出它的版本`,'role')});
  const ni=$('#eqNew');
  if(ni){
    const commit=()=>{
      const n=ni.value.trim();
      if(!n){renderEqList($('#ctq').value.trim());return}
      if(!EQCONTACTS.includes(n))EQCONTACTS.unshift(n.slice(0,20));
      eqSaveCts();EQCUR=n.slice(0,20);try{localStorage.setItem('eqCur',EQCUR)}catch(e){}
      renderEqList($('#ctq').value.trim());renderMsgs();
      sysTip(`💚 高情商练习已就位 · 对象「${EQCUR}」\n流程: 她说一句 → 你回一句 → 高情商版分身同时给出它的回复；点它气泡下的「🔍 诊断这轮」看差异`);
    };
    ni.onkeydown=e=>{if(e.key==='Enter')commit();if(e.key==='Escape')renderEqList($('#ctq').value.trim())};
    ni.onblur=()=>{setTimeout(()=>{if(document.getElementById('eqNew')&&$('#eqNew').value.trim()&&document.activeElement!==$('#eqNew'))commit()},150)};
  }
}
async function renderEqDom(){
  if(EQCUR&&!EQSESS[EQCUR]){
    try{const d=await api('/api/agent/eq/chat?contact='+encodeURIComponent(EQCUR));
      EQSESS[EQCUR]=(d.chat||[]).map(m=>({who:m.r==='eq'?'eqai':(m.r==='bg'?'eqbg':'eq'+m.r),text:m.c,strat:m.strat||''}));
    }catch(e){EQSESS[EQCUR]=[]}
  }
  const box=$('#msgs');box.innerHTML='';
  const s=eqSess(EQCUR);
  // 自动推断轮次: 最后一条是"她说的" → 该你答; 否则该她说
  EQTURN=s.length&&s[s.length-1].who==='eqgirl'?'mine':'girl';
  s.forEach(appendDom);
  updateEqUI();
  box.scrollTop=1e9;
}
async function sendEq(text){
  if(!EQCUR){toast('先在左侧「➕ 添加发展对象」');return}
  const sC=EQCUR,s=eqSess(sC);
  if(EQTURN==='girl'){pushEq(sC,{who:'eqgirl',text});setEqTurn('mine');return}
  let girl='';for(let i=s.length-1;i>=0;i--){if(s[i].who==='eqgirl'){girl=s[i].text;break}}
  if(!girl){setEqTurn('girl');updateEqUI();toast('她还没说话 —— 先点「🎤 她说」替她发一句');return}
  pushEq(sC,{who:'eqme',text});
  const tip=document.createElement('div');tip.className='typing';
  tip.innerHTML='<span style="display:inline-block;animation:simpulse 1.2s infinite">⏳</span> 高情商分身思考中…';
  $('#msgs').appendChild(tip);$('#msgs').scrollTop=1e9;
  try{
    const r=await post('/api/agent/eq/reply',{contact:sC,girl:girl,mine:text});
    tip.remove();
    pushEq(sC,{who:'eqai',text:r.reply||'(无回复)',strat:r.strategy||'',girl:girl,mine:text});
    if(EQCUR!==sC)toast(`💚 「${sC}」的高情商回复已存入原会话`);
    EQTURN='girl';updateEqUI();
  }catch(e){tip.remove();throw e}
}
async function diagnoseEq(btn,m){
  btn.disabled=true;btn.textContent='诊断中…';
  try{
    const r=await post('/api/agent/eq/diagnose',{contact:EQCUR,girl:m.girl||'',mine:m.mine||'',eq:m.text});
    let h=`<div class="eqdiag"><b>🔍 诊断 · 你的${m.girl?'原话':'开场白'}</b><br>${esc(r.comment||'—')}`;
    if((r.issues||[]).length)h+='<div style="margin-top:6px">'+r.issues.map(x=>`<div class="iss">✗ ${esc(x)}</div>`).join('')+'</div>';
    h+=`<div style="margin-top:6px"><b>高情商版好在哪：</b>${esc(r.why_better||'—')}</div>
        <div style="margin-top:6px"><b>💡 一句可迁移的原则：</b>${esc(r.principle||'—')}</div></div>`;
    btn.closest('.row').insertAdjacentHTML('afterend',h);btn.remove();
    $('#msgs').scrollTop=1e9;
  }catch(e){btn.disabled=false;btn.textContent='🔍 诊断这轮';toast('⚠ '+e.message)}
}
$('#eqTurnBtn').onclick=()=>setEqTurn(EQTURN==='girl'?'mine':'girl');
/* ───── 首次开场: 对方还没说话, 只有背景 → 高情商版开场白 ───── */
$('#eqOpenBtn').onclick=()=>{
  const p=$('#eqOpenPanel');
  p.style.display=p.style.display==='none'?'':'none';
  if(p.style.display!=='none')$('#eqOpenBg').focus();
};
$('#eqOpenCancel').onclick=()=>{$('#eqOpenPanel').style.display='none'};
$('#eqOpenGo').onclick=async()=>{
  if(!EQCUR){toast('先在左侧「➕ 添加发展对象」');return}
  const bg=$('#eqOpenBg').value.trim(),mine=$('#eqOpenMine').value.trim();
  if(!bg||!mine){toast('背景和你的开场白都要填');return}
  const sC=EQCUR,btn=$('#eqOpenGo');
  btn.disabled=true;btn.textContent='生成中…';
  const tip=document.createElement('div');tip.className='typing';
  tip.innerHTML='<span style="display:inline-block;animation:simpulse 1.2s infinite">⏳</span> 高情商分身正在构思开场白…';
  $('#msgs').appendChild(tip);$('#msgs').scrollTop=1e9;
  try{
    const r=await post('/api/agent/eq/open',{contact:sC,bg:bg,mine:mine});
    tip.remove();
    pushEq(sC,{who:'eqbg',text:bg});
    pushEq(sC,{who:'eqme',text:mine,girl:'',mine:mine});
    pushEq(sC,{who:'eqai',text:r.reply||'(无回复)',strat:r.strategy||'',girl:'',mine:mine});
    $('#eqOpenPanel').style.display='none';$('#eqOpenBg').value='';$('#eqOpenMine').value='';
    EQTURN='girl';updateEqUI();
    if(EQCUR!==sC)toast(`🚀 「${sC}」的开场白已存入原会话`);
  }catch(e){tip.remove();toast('⚠ '+((e&&(e.message||e))||'生成失败'))}
  btn.disabled=false;btn.textContent='✨ 生成高情商开场白';
};
function setMode(m){
  const changed=MODE!==m;MODE=m;
  $$('.modebar .mb').forEach(b=>b.classList.toggle('on',b.dataset.m===m));
  $('#modehint').textContent=m==='dialog'
    ?'模拟模式：你在输入框扮演「联系人」（右侧绿泡），分身用万凯的口吻回复（左侧，带 AI 标识）—— 各联系人的模拟对话独立保存'
    :m==='eq'
    ?'高情商练习：左侧选「发展对象」→ 她说一句 → 你回一句 → 高情商版分身同步给出它的版本，可点「🔍 诊断」看差异；对方还没说过话时用「🚀 首次开场」填背景引话题'
    :'贾维斯模式：你以第三者身份提问，AI 分析你和 ta 的关系并引用原话证据 —— 与模拟对话互相独立';
  if(m==='eq'){
    try{EQCUR=localStorage.getItem('eqCur')||''}catch(e){}
    renderEqList($('#ctq').value.trim());renderMsgs();
  }else{
    $('#sidehd').textContent='选择联系人（按消息量排序）';
    renderCtList($('#ctq').value.trim());
    if(changed)renderMsgs();      // 切模式 = 切到另一个独立会话, 上下文绝不互带
  }
  setPlaceholder();updateRoleBanner();
}
$$('.modebar .mb').forEach(b=>b.onclick=()=>setMode(b.dataset.m));
$('#mbRaw').onclick=()=>{if(CUR)showRecent(dn(CUR));else sysTip('先在左侧选择一个联系人')};
$('#mbMembers').onclick=async()=>{
  if(!ISG())return;
  sysTip(`正在分析「${CUR}」的主要成员性格…(首次约需 10-30 秒, 之后走缓存)`);
  try{
    const p=await api('/api/agent/group/personas?group='+encodeURIComponent(CUR));
    sysTip(`👥 群氛围: ${p.tone||'—'}\n`+(p.members||[]).map(m=>
      `【${m.name}】 发言${m.n}条(${m.pct}%) · 均${m.avg_len}字${m.late_pct>10?` · 夜猫${m.late_pct}%`:''}\n${m.persona||'(速写待生成)'}${m.style?'\n风格: '+m.style:''}`).join('\n———\n'));
    toast('👥 「'+dn(CUR)+'」成员性格分析完成');
  }catch(e){sysTip('⚠ 成员分析失败: '+e.message)}
};
$('#clearChat').onclick=async()=>{
  if(MODE==='eq'){
    if(!EQCUR){toast('先选择一位发展对象');return}
    if(!confirm(`清空与「${EQCUR}」的高情商练习记忆？`))return;
    try{await post('/api/agent/eq/clear',{contact:EQCUR})}catch(e){}
    EQSESS[EQCUR]=[];eqSave(EQCUR);renderMsgs();
    sysTip(`已清空「${EQCUR}」的高情商练习记忆 —— 重新开始`);
    return;
  }
  SESSIONS[skey()]=[];ssave();renderMsgs();
  sysTip(`已清空当前对话记忆（${MODE==='dialog'?'模拟':'贾维斯'} · ${CUR}）—— 后续不再携带之前的上下文，本地记录不受影响`)};
function appendDom(m){
  const box=$('#msgs');
  if(m.who==='sys'){const d=document.createElement('div');d.className='typing';d.textContent='· '+m.text;box.appendChild(d);box.scrollTop=1e9;return}
  const isAI=(m.who==='aime'||m.who==='ai'||m.who==='ctwin');   // aime=AI 扮演万凯, ctwin=AI 扮演联系人, ai=AI 分析师
  const row=document.createElement('div');row.className='row'+((m.who==='me'||m.who==='contact')?' me':'');
  const av=document.createElement('div');av.className='av';
  const b=document.createElement('div');b.className='bub';
  if(isAI){av.classList.add('ai');av.textContent='AI'}
  else if(m.who==='me'){av.textContent='我'}
  else{av.textContent=CUR.startsWith('陌生·')?'🌑':(CUR==='新朋友'?'ta':CUR.slice(0,1))}
  if(m.who==='ai'){ // 贾维斯: AI 记忆分析师
    const wrap=document.createElement('div');wrap.style.cssText='display:flex;flex-direction:column;max-width:600px';
    wrap.innerHTML=`<div class="who">AI 记忆分析师</div><div class="bub">${wxface(esc(m.text))}</div>`+(m.anl||'');
    row.appendChild(av);row.appendChild(wrap);
  }else if(m.who==='gmem'){ // 群成员冒泡: 左侧, 彩色头像+名字
    const sp=m.speaker||'?';
    const hue=[...sp].reduce((a,c)=>(a*31+c.charCodeAt(0))%360,7);
    av.style.background=`hsl(${hue},42%,50%)`;av.textContent=sp.slice(0,1);
    const wrap=document.createElement('div');wrap.style.cssText='display:flex;flex-direction:column;max-width:600px';
    wrap.innerHTML=`<div class="who">${esc(sp)}</div>`;
    b.innerHTML=wxface(esc(m.text));wrap.appendChild(b);
    row.appendChild(av);row.appendChild(wrap);
  }else if(m.who==='aime'){ // 模拟模式: AI 数字分身扮演万凯 —— 放左侧+AI标识, 避免截图分享时被误认为真人输入
    const wrap=document.createElement('div');wrap.style.cssText='display:flex;flex-direction:column;align-items:flex-start;max-width:560px';
    wrap.innerHTML=`<div class="who">AI 数字分身 · 万凯${m.human?' <span class="tag g" style="font-size:10px">🔧 本人确认</span>':''}</div>`;
    b.innerHTML=wxface(esc(String(m.text).replace(/\n+/g,'  ')));wrap.appendChild(b);
    row.appendChild(av);row.appendChild(wrap);
  }
  else if(m.who==='contact'){ // 模拟模式: 你本人扮演联系人 —— 右侧绿泡(真人输入侧), 与左侧 AI 生成内容区分
    const wrap=document.createElement('div');wrap.style.cssText='display:flex;flex-direction:column;align-items:flex-end;max-width:560px';
    wrap.innerHTML=`<div class="who">你扮演 · ${esc(dn(CUR))}</div>`;
    b.innerHTML=wxface(esc(m.text));wrap.appendChild(b);
    row.appendChild(av);row.appendChild(wrap);
  }
  else if(m.who==='ctwin'){ // 身份互换: AI 扮演联系人 —— 左侧白泡+AI标识, 与真人输入区分
    const wrap=document.createElement('div');wrap.style.cssText='display:flex;flex-direction:column;align-items:flex-start;max-width:560px';
    wrap.innerHTML=`<div class="who">AI 分身 · ${esc(dn(CUR))}${m.human?' <span class="tag g" style="font-size:10px">🔧 本人确认</span>':''}</div>`;
    b.innerHTML=wxface(esc(String(m.text).replace(/\n+/g,'  ')));wrap.appendChild(b);
    row.appendChild(av);row.appendChild(wrap);
  }
  else if(m.who==='eqbg'){ // 首次开场: 对象背景资料(左, 灰泡)
    av.textContent='📋';
    const wrap=document.createElement('div');wrap.style.cssText='display:flex;flex-direction:column;align-items:flex-start;max-width:560px';
    wrap.innerHTML=`<div class="who">📋 对象背景（首次开场）</div>`;
    b.style.background='#f4f6f8';b.innerHTML=wxface(esc(m.text));wrap.appendChild(b);
    row.appendChild(av);row.appendChild(wrap);
  }
  else if(m.who==='eqgirl'){ // 高情商: 你扮演的发展对象(左, 虚线泡)
    av.textContent=(EQCUR||'她').slice(0,1);
    const wrap=document.createElement('div');wrap.style.cssText='display:flex;flex-direction:column;align-items:flex-start;max-width:560px';
    wrap.innerHTML=`<div class="who">她 · ${esc(EQCUR||'发展对象')}（你扮演）</div>`;
    b.innerHTML=wxface(esc(m.text));b.classList.add('eqgirl');wrap.appendChild(b);
    row.appendChild(av);row.appendChild(wrap);
  }
  else if(m.who==='eqme'){ // 高情商: 你本来想回的原话(右绿)
    row.className='row me';
    av.textContent='我';
    const wrap=document.createElement('div');wrap.style.cssText='display:flex;flex-direction:column;align-items:flex-end;max-width:560px';
    wrap.innerHTML=`<div class="who">你的原话（发送前）</div>`;
    b.innerHTML=wxface(esc(m.text));wrap.appendChild(b);
    row.appendChild(av);row.appendChild(wrap);
  }
  else if(m.who==='eqai'){ // 高情商: AI 高情商版回复(右, 金泡+诊断按钮)
    row.className='row me eqrow';
    av.textContent='EQ';
    const wrap=document.createElement('div');wrap.style.cssText='display:flex;flex-direction:column;align-items:flex-end;max-width:560px';
    wrap.innerHTML=`<div class="who">💚 高情商版 · AI${m.strat?` <span style="color:#b07a10">— ${esc(m.strat)}</span>`:''}</div>`;
    b.innerHTML=wxface(esc(String(m.text).replace(/\n+/g,'  ')));b.classList.add('eqgold');wrap.appendChild(b);
    const tools=document.createElement('div');tools.style.cssText='margin-top:5px;text-align:right';
    const dbtn=document.createElement('button');dbtn.className='chip';dbtn.textContent='🔍 诊断这轮';
    dbtn.onclick=()=>diagnoseEq(dbtn,m);
    tools.appendChild(dbtn);wrap.appendChild(tools);
    row.appendChild(av);row.appendChild(wrap);
  }
  else if(m.who==='me'){ // 本人输入(贾维斯提问/群聊/身份互换) —— 右侧绿泡, 标注真人身份
    const wrap=document.createElement('div');wrap.style.cssText='display:flex;flex-direction:column;align-items:flex-end;max-width:560px';
    wrap.innerHTML=`<div class="who">万凯本人</div>`;
    b.innerHTML=wxface(esc(m.text));wrap.appendChild(b);
    row.appendChild(av);row.appendChild(wrap);
  }
  else{b.innerHTML=wxface(esc(m.text));row.appendChild(av);row.appendChild(b)}
  box.appendChild(row);box.scrollTop=1e9;
  if(PAGE()==='twin')updateRoleBanner();  // 任何消息落 DOM 后都同步一次身份横幅(防时序遗漏)
}
function updateRoleBanner(){
  const el=$('#roleBanner'),sw=$('#mbSwap');
  if(!el)return;
  const canSwap=PAGE()==='twin'&&MODE==='dialog'&&!ISG()&&CUR!=='新朋友'&&!CUR.startsWith('陌生·')
    &&CONTACTS.some(c=>c['姓名']===CUR);
  if(sw)sw.style.display=canSwap?'':'none';
  if(PAGE()!=='twin'){el.style.display='none';return}
  el.style.display='';
  if(MODE==='ask'){el.className='';el.innerHTML='🖥 屏幕前：<b>万凯本人</b>（提问中） · 对面：贾维斯 AI（引用真实记忆回答）'}
  else if(MODE==='eq'){
    el.className='';
    el.innerHTML=EQCUR
      ?`💚 高情商练习 · 对象：<b>${esc(EQCUR)}</b> —— 她(左) → 你的原话(右绿) → 高情商版分身(右金) · 用「🎤 她说/我答」切换本轮谁开口`
      :'💚 高情商练习 —— 先在左侧添加一位发展对象开始'}
  else if(ISG()){el.className='';el.innerHTML='🖥 屏幕前：<b>万凯本人</b>（在群里发言） · 群成员由 AI 按真实性格扮演'}
  else if(DIR==='B'){el.className='rb-b';
    el.innerHTML=`🖥 屏幕前正在输入：<b>万凯本人</b> · 对面回复：AI 分身（扮演「${esc(dn(CUR))}」，每条带 AI 标识）`}
  else{el.className='';
    el.innerHTML=`🖥 屏幕前正在输入：<b>你（扮演「${esc(dn(CUR))}」）</b> · 对面回复：AI 数字分身（万凯）`}
}
/* 身份互换: A(你演联系人) ⇄ B(你演万凯本人, AI 演联系人 —— 需先塑造联系人分身画像) */
let SWAPPING=false; // 身份互换进行中(塑造/切换), 防重复点击
$('#mbSwap').onclick=async()=>{
  if(MODE!=='dialog'||ISG()||!CUR||CUR==='新朋友')return;
  if(SENDING){toast('⚠ AI 正在回复中（或确认弹窗未处理完），等这轮对话结束再切换身份');return}
  if(SWAPPING){toast('正在切换身份，请稍候…');return}
  if(DIR==='B'){DIR='A';dirSave();sysTip(`已切换回普通模式：你扮演「${dn(CUR)}」，AI 数字分身扮演万凯`,'role');
    updateRoleBanner();setPlaceholder();renderMsgs();return}
  let st;try{st=await api('/api/agent/twin/contact/status?contact='+encodeURIComponent(CUR))}
  catch(e){sysTip('⚠ '+e.message);return}
  if(st.is_group){sysTip('群聊暂不支持身份互换');return}
  if(!st.ready){toast(`「${dn(CUR)}」的历史发言仅 ${st.total} 条，未达塑造门槛（${st.min} 条）—— 聊得再多一点再来`);return}
  if(!st.has_profile){
    SWAPPING=true;
    try{
      sysTip(`正在为「${dn(CUR)}」塑造数字分身：通读 ta 的 ${st.total} 条真实发言，提炼说话风格/口头禅/话题…（首次约 30-90 秒，塑造期间请勿发消息）`);
      await post('/api/agent/twin/contact/build',{contact:CUR});
      toast(`「${dn(CUR)}」的分身塑造完成`);
    }catch(e){sysTip('⚠ 塑造失败：'+e.message);return}
    finally{SWAPPING=false}
  }
  DIR='B';dirSave();
  sysTip(`已切换到身份互换模式：屏幕前的你是万凯本人，对面由 AI 分身扮演「${dn(CUR)}」与他对话（每条回复带 AI 标识，截图一目了然；再点一次「🔄 身份互换」可换回）`,'role');
  updateRoleBanner();setPlaceholder();renderMsgs();
};
function renderMsgs(){
  if(MODE==='eq'){renderEqDom();return}
  $('#msgs').innerHTML='';curSess().forEach(appendDom);
  const mb=$('#mbMembers');if(mb)mb.style.display=ISG()&&MODE==='dialog'?'':'none';
  updateRoleBanner()}
function pushMsg(who,text,anlHTML,extra){const m=Object.assign({who,text,anl:anlHTML||null},extra||{});curSess().push(m);appendDom(m);ssave()}
const _ROLE_TIP=/^已切换到|^已切换回|^已换回|^正在为「/;   // 身份类提示: 会话内只保留最新一条
function sysTip(t,tag){const m={who:'sys',text:t};
  if(MODE==='eq'&&EQCUR){ // 高情商模式: 提示写入当前对象的高情商会话, 不碰主功能会话
    const s=eqSess(EQCUR);if(tag){for(let i=s.length-1;i>=0;i--){if(s[i].who==='sys'&&s[i].tip===tag)s.splice(i,1)}}
    s.push(m);eqSave(EQCUR);
    if($('#msgs')){appendDom(m);$('#msgs').scrollTop=1e9}
    return}
  if(tag){m.tip=tag;const s=curSess();
    for(let i=s.length-1;i>=0;i--){if(s[i].who==='sys'&&(s[i].tip===tag||(s[i].text&&_ROLE_TIP.test(s[i].text))))s.splice(i,1)}}
  curSess().push(m);appendDom(m);ssave()}
/* ───── 人工介入: 分身拿不准时弹窗请本人拿主意(直答/选候选/直接采用) ───── */
function openIntervene(o){ // o={question,aiDraft,candidates,contact,mode,anlHTML} → Promise<最终回答|null>
  return new Promise(resolve=>{
    const mask=document.createElement('div');
    mask.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:2000;display:flex;align-items:center;justify-content:center';
    const box=document.createElement('div');
    box.style.cssText='background:#fff;border-radius:14px;width:min(560px,92vw);max-height:82vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 8px 40px rgba(0,0,0,.3)';
    const cands=(o.candidates||[]).filter(Boolean);
    box.innerHTML=`
    <div style="padding:12px 16px;background:#fdf3e8;border-bottom:1px solid #f0e0c8;display:flex;justify-content:space-between;align-items:center">
      <b style="font-size:14px;color:#8a5a00">🤔 分身拿不准，请你拿主意</b>
      <span data-a="cancel" style="cursor:pointer;color:#b08a50;font-size:18px;line-height:1">✕</span></div>
    <div style="overflow-y:auto;padding:14px 18px;font-size:13px;line-height:1.7">
      <div class="mut" style="margin-bottom:8px">关于「${esc(o.contact||'')}」的问题：<b>${esc(o.question||'')}</b></div>
      ${o.anlHTML||''}
      <div style="background:#f7f8fa;border-radius:10px;padding:10px 12px;margin-bottom:12px">
        <div class="mut" style="font-size:12px;margin-bottom:4px">AI 的猜测（可能不准确）：</div>
        <div>${wxface(esc(o.aiDraft||'(没有生成内容)'))}</div>
      </div>
      ${cands.length?`<div style="margin-bottom:12px"><div class="mut" style="font-size:12px;margin-bottom:4px">它给出的候选（选中即按该条发送）：</div>
        ${cands.map((c,i)=>`<label style="display:flex;gap:8px;align-items:flex-start;padding:6px 8px;border:1px solid var(--line);border-radius:9px;margin-bottom:5px;cursor:pointer">
          <input type="radio" name="ivc" value="${i}" style="margin-top:3px"><span>${wxface(esc(c))}</span></label>`).join('')}</div>`:''}
      <div class="mut" style="font-size:12px;margin-bottom:4px">或者你亲自回答（以你的口吻发出，并记入纠正记忆）：</div>
      <textarea id="ivAns" rows="2" placeholder="输入正确答案…（改用候选或 AI 猜测时可留空）" style="width:100%;border:1px solid var(--line);border-radius:9px;padding:8px 10px;font-size:13px;font-family:inherit;resize:vertical"></textarea>
      <div class="mut" style="font-size:11.5px;margin-top:6px">你的决定会存进知识库「人工纠正」，分身下次遇到同类问题优先照做 —— 越纠正越像你。</div>
    </div>
    <div style="display:flex;gap:8px;padding:12px 18px;border-top:1px solid var(--line)">
      <button class="btn" data-a="human" style="flex:1">✅ 用我的回答</button>
      <button class="btn gray" data-a="pick" style="flex:1">📤 用候选 / AI 猜测</button>
      <button class="btn gray" data-a="cancel">取消</button>
    </div>`;
    mask.appendChild(box);document.body.appendChild(mask);
    const ta=box.querySelector('#ivAns');ta.focus();
    const close=v=>{mask.remove();resolve(v)};
    box.querySelectorAll('button,[data-a="cancel"]').forEach(b=>b.onclick=async()=>{
      const a=b.dataset.a;
      if(a==='cancel')return close(null);
      const pick=box.querySelector('input[name="ivc"]:checked');
      const choice=a==='human'?'human':(pick?'candidate':'adopt');
      if(choice==='human'&&!ta.value.trim()){ta.style.borderColor='#e05a5a';ta.placeholder='本人的回答不能为空';ta.focus();return}
      b.disabled=true;
      try{
        const r=await post('/api/agent/interventions',{contact:o.contact||'',mode:o.mode||'dialog',
          question:o.question||'',ai_draft:o.aiDraft||'',choice,human_answer:ta.value.trim(),
          candidates:cands,candidate_index:pick?+pick.value:null});
        toast(r.memory_saved===false
          ?'✅ 已回答（本次内容对训练分身没有帮助，未存入纠正记忆）'
          :'✅ 已回答并存入人工纠正记忆 —— 越纠正越像你');
        close(r.final_reply);
      }catch(e){toast('⚠ 保存失败: '+e.message);b.disabled=false}
    });
    mask.onclick=e=>{if(e.target===mask)close(null)};
  });
}
function renderAnalysisHTML(a){
  if(!a)return '';
  let h='<details class="anl"><summary>📎 分析依据（点击展开）</summary>';
  (a['关键事实']||[]).slice(0,5).forEach(f=>{
    h+=`<div style="margin-top:7px">✦ ${esc(f['事实']||'')}<span class="mut">（${esc(f['置信']||'')}）</span>`;
    (f['证据']||[]).slice(0,2).forEach(ev=>{h+=`<div class="ev">💬 ${esc(ev['时间']||'')} · 与${esc(ev['对象']||'')} · ${esc(ev['说话人']||'')}：${esc(ev['原文']||'')}</div>`});
    if(!f['证据']||!f['证据'].length)h+='<div class="ev">⚠ 未找到原文证据</div>';
    h+='</div>';});
  if((a['不确定信息']||[]).length)h+=`<div class="mut" style="margin-top:6px">不确定: ${esc((a['不确定信息']||[]).join('；'))}</div>`;
  return h+'</details>';
}
function histFor(n){
  // 从当前独立会话派生 API history; speaker 语义: dialog=联系人/我(含AI扮演的aime), ask=我/分析师
  return curSess().filter(m=>m.who==='me'||m.who==='contact'||m.who==='ai'||m.who==='aime'||m.who==='ctwin').slice(-n).map(m=>({
    speaker: MODE==='dialog'?((m.who==='me'||m.who==='aime')?'我':CUR):(m.who==='me'?'我':'分析师'),
    content: m.text}));
}
async function send(){
  const inp=$('#chat-in'),text=inp.value.trim();
  if(!text||SENDING)return;
  if(typeof SWAPPING!=='undefined'&&SWAPPING){toast('⚠ 正在为对方塑造分身/切换身份，等几十秒后再发');return}
  SENDING=true;$('#sendbtn').disabled=true;inp.value='';
  // 高情商练习模式走独立流程, 与主分身对话完全隔离
  if(MODE==='eq'){try{await sendEq(text)}catch(e){toast('⚠ '+(e.message||e))}SENDING=false;$('#sendbtn').disabled=false;inp.focus();return}
  const isGroupDialog=ISG()&&MODE==='dialog';
  // 发送时快照: AI 回复可能耗时很久, 期间用户可能切换联系人/模式/方向 ——
  // 请求与落库全程以快照为准, 回复永远归位到发送时的会话, 不会串到后来切到的人身上
  const sCur=CUR,sMode=MODE,sDir=DIR,sIsG=isGroupDialog;
  const hist=sIsG
    ?curSess().filter(m=>m.who==='me'||m.who==='gmem').slice(-10).map(m=>({speaker:m.who==='me'?'我':m.speaker,text:m.text}))
    :histFor(MODE==='dialog'?8:30);      // push 前取, 防同句重复
  pushMsg(isGroupDialog?'me':(MODE==='dialog'?(DIR==='B'?'me':'contact'):'me'),text);
  // 思考进度 tip(不入会话): 实时显示 AI 当前阶段 + 已用时
  const tip=document.createElement('div');tip.className='typing';$('#msgs').appendChild(tip);
  const t0=Date.now();let stepTxt=isGroupDialog?'群里正在讨论…':'正在唤醒分身…';
  const draw=s=>{tip.innerHTML=`<span style="display:inline-block;animation:simpulse 1.2s infinite">⏳</span> ${esc(s)} <b class="mut">${Math.floor((Date.now()-t0)/1000)}s</b>`};
  draw(stepTxt);$('#msgs').scrollTop=1e9;
  const tick=setInterval(()=>{draw(stepTxt)},1000);
  try{
    if(sIsG){
      const resp=await fetch('/api/agent/group/chat',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({group:sCur,message:text,hist})});
      if(!resp.ok){const e=await resp.json().catch(()=>({}));throw new Error(e.error||('HTTP '+resp.status))}
      const r=await resp.json();
      clearInterval(tick);tip.remove();
      const rs=r.replies||[];
      if(CUR!==sCur||MODE!==sMode){ // 已切走: 静默写入原会话
        rs.forEach(x=>pushTo(sCur,sMode,sDir,'gmem',x.text,null,{speaker:x.speaker}));
        if(!rs.length)pushTo(sCur,sMode,sDir,'sys','(群里暂时没人冒泡)');
        toast(`👥 「${dn(sCur)}」的群聊回复已送达原会话`);
      }else{
        rs.forEach(x=>pushMsg('gmem',x.text,null,{speaker:x.speaker}));
        if(!rs.length)pushMsg('sys','(群里暂时没人冒泡)');
      }
    }else{
    const resp=await fetch('/api/agent/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({contact:sCur,mode:sMode,message:text,history:hist,stream:true,
        direction:(sMode==='dialog'&&sDir==='B')?'contact':'owner',
        persona:sMode==='ask'?'oracle':undefined})});
    if(!resp.ok){const e=await resp.json().catch(()=>({}));throw new Error(e.error||('HTTP '+resp.status))}
    const reader=resp.body.getReader(),dec=new TextDecoder();let buf='',reply='',anl=null,err=null,unsure=false,cands=[];
    while(true){
      const {done,value}=await reader.read();if(done)break;
      buf+=dec.decode(value,{stream:true});
      let i;while((i=buf.indexOf('\n'))>=0){
        const line=buf.slice(0,i).trim();buf=buf.slice(i+1);
        if(!line)continue;
        let ev;try{ev=JSON.parse(line)}catch(e){continue}
        if(ev.step){stepTxt=ev.step;draw(stepTxt)}
        if(ev.done){if(ev.error)err=ev.error;else{reply=ev.reply||'';anl=ev.analysis||null;unsure=!!ev.unsure;cands=ev.candidates||[]}}
      }
    }
    clearInterval(tick);tip.remove();
    if(err)throw new Error(err);
    // 已切走判定: 当前联系人/模式/方向与发送时不一致 → 不动当前界面, 只写回原会话
    const moved=(CUR!==sCur||MODE!==sMode||(MODE==='dialog'&&DIR!==sDir));
    if(sMode==='dialog'){
      const rwho=sDir==='B'?'ctwin':'aime';   // B=AI 扮演联系人, A=AI 扮演万凯
      if(unsure){ // 分身拿不准 → 弹窗请本人拿主意, 绝不强行回复(回答永远归位到原会话)
        const fr=await openIntervene({question:text,aiDraft:reply,candidates:cands,contact:sCur,mode:'dialog'});
        if(moved){if(fr!=null)pushTo(sCur,sMode,sDir,rwho,fr,null,{human:true});
          else pushTo(sCur,sMode,sDir,'sys','(本次没有回复：分身拿不准，而你选择暂不介入)');
          toast(`💬 「${dn(sCur)}」的回复已存入原会话`);}
        else{if(fr!=null)pushMsg(rwho,fr,null,{human:true});
          else pushMsg('sys','(本次没有回复：分身拿不准，而你选择暂不介入)');}
      }
      else if(reply){
        if(moved){pushTo(sCur,sMode,sDir,rwho,reply);toast(`💬 「${dn(sCur)}」的回复已存入原会话`)}
        else pushMsg(rwho,reply);            // AI 分身回复(明确标注 AI)
      }
    }else{
      const a=anl||{};
      const ans=(a['回答']||reply||'').trim()||'(AI 未返回回答)';
      const anlHtml=renderAnalysisHTML(a);
      if(unsure){ // 分析师没把握 → 人工介入
        if(moved){const fr=await openIntervene({question:text,aiDraft:ans,candidates:cands,contact:sCur,mode:'ask',anlHTML:anlHtml});
          if(fr!=null)pushTo(sCur,sMode,sDir,'ai',fr,anlHtml+'<div class="mut" style="margin-top:4px">🔧 本人确认的回答</div>');
          else pushTo(sCur,sMode,sDir,'sys','(已取消：分析师对这个问题没把握，等你亲自补充)');}
        else{const fr=await openIntervene({question:text,aiDraft:ans,candidates:cands,contact:sCur,mode:'ask',anlHTML:anlHtml});
          if(fr!=null)pushMsg('ai',fr,anlHtml+'<div class="mut" style="margin-top:4px">🔧 本人确认的回答</div>');
          else pushMsg('sys','(已取消：分析师对这个问题没把握，等你亲自补充)');}
      }else{
        if(moved){pushTo(sCur,sMode,sDir,'ai',ans,anlHtml);toast(`💬 「${dn(sCur)}」的贾维斯回答已存入原会话`)}
        else pushMsg('ai',ans,anlHtml);   // 贾维斯: 分析师回答+依据卡
      }
    }
    }
  }catch(e){clearInterval(tick);tip.innerHTML='⚠ '+esc(e.message);setTimeout(()=>tip.remove(),6000)}
  SENDING=false;$('#sendbtn').disabled=false;inp.focus();
}
$('#sendbtn').onclick=send;
$('#chat-in').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});

/* ───── 贾维斯问答(独立页): 与数字分身各自独立会话, 可同时进行 ───── */
let BCUR='',BSENDING=false;
const BSESS={};
const bkey=()=>'byst_'+(BCUR||'新朋友');
function bcurSess(){if(!BSESS[bkey()])BSESS[bkey()]=JSON.parse(localStorage.getItem(bkey())||'[]');return BSESS[bkey()]}
function bsave(){try{localStorage.setItem(bkey(),JSON.stringify(bcurSess()))}catch(e){}}
/* 贾维斯消息渲染: 页面(#bmsgs)与全局抽屉(#dmsgs)共用同一会话, 双端同步显示 */
const ORA={open:false};
const ORA_BOXES=()=>['#bmsgs','#dmsgs'].map(s=>$(s)).filter(Boolean);
/* 贾维斯回答排版: 转义 + **加粗** + 换行保留(sandbox 卡片等富文本走 m.html) */
function mdlite(t){
  return esc(t||'').replace(/\*\*([^*\n]+)\*\*/g,'<b>$1</b>').replace(/\n/g,'<br>');
}
function oraRow(m){
  if(m.who==='sys'){const d=document.createElement('div');d.className='typing';d.textContent='· '+m.text;return d}
  const row=document.createElement('div');row.className='row'+(m.who==='me'?' me':'');
  const av=document.createElement('div');av.className='av';
  const b=document.createElement('div');b.className='bub';
  if(m.who==='me'){av.textContent='我';b.innerHTML=wxface(esc(m.text));row.appendChild(av);row.appendChild(b)}
  else{av.classList.add('ai');av.textContent='🫧';
    const wrap=document.createElement('div');wrap.style.cssText='display:flex;flex-direction:column;max-width:600px';
    wrap.innerHTML=`<div class="who">贾维斯</div>`;
    b.innerHTML=(m.html||mdlite(m.text))+(m.anl||'');wrap.appendChild(b);
    row.appendChild(av);row.appendChild(wrap)}
  return row;
}
function bAppendDom(m){ORA_BOXES().forEach(box=>{box.appendChild(oraRow(m));box.scrollTop=1e9})}
function bRender(){ORA_BOXES().forEach(box=>{box.innerHTML='';bcurSess().forEach(m=>box.appendChild(oraRow(m)));box.scrollTop=1e9})}
/* 人物确认卡片: AI 先识别提问中涉及的人, 用户确认后再检索 */
function bConfirmCard(cands,boxSel){
  return new Promise(resolve=>{
    const box=$(boxSel||'#bmsgs');
    const card=document.createElement('div');
    card.style.cssText='margin:4px 0 12px 44px;background:#fff;border:1px solid #e8e8ea;border-radius:12px;padding:12px 14px;max-width:540px;box-shadow:0 1px 3px rgba(0,0,0,.06)';
    card.innerHTML='<div style="font-size:13px;font-weight:600;margin-bottom:6px">🧭 这个问题涉及下面这些人，帮我确认一下（可多选）：</div>'
      +cands.map((c,i)=>`<label style="display:flex;gap:8px;align-items:center;padding:5px 2px;font-size:13px;cursor:pointer">
        <input type="checkbox" checked data-i="${i}">
        <span style="font-weight:600">${esc(dn(c.name))}</span>
        <span class="mut" style="font-size:11px">${esc(c.circle||'')} · 聊过 ${c.total} 条 · 最近 ${c.last||'—'}（命中: ${esc(c.hit)}）</span></label>`).join('')
      +'<div style="display:flex;gap:8px;margin-top:10px">'
      +'<button class="btn" style="padding:6px 14px;font-size:13px" data-a="ok">✓ 就这些人，继续分析</button>'
      +'<button class="btn gray" style="padding:6px 14px;font-size:13px" data-a="skip">跳过，AI 自己判断</button></div>';
    box.appendChild(card);box.scrollTop=1e9;
    card.querySelectorAll('button').forEach(b=>b.onclick=()=>{
      if(b.dataset.a==='ok'){
        const names=[...card.querySelectorAll('input:checked')].map(x=>cands[+x.dataset.i].name);
        card.innerHTML=`<span class="mut" style="font-size:12px">✓ 已确认涉及：${esc(names.map(dn).join('、')||'（未勾选，AI 自行判断）')}</span>`;
        resolve(names.length?names:null);
      }else{
        card.innerHTML='<span class="mut" style="font-size:12px">已跳过确认，AI 将自行判断涉及的人物</span>';
        resolve(null);
      }
    });
  });
}
async function sendB(src){
  src=src||'page';
  const inp=src==='fab'?$('#dchat-in'):$('#bchat-in');
  const boxSel=src==='fab'?'#dmsgs':'#bmsgs';
  const btn=src==='fab'?$('#dsendbtn'):$('#bsendbtn');
  const text=inp.value.trim();
  if(!text||BSENDING)return;
  BSENDING=true;btn.disabled=true;inp.value='';
  const hist=bcurSess().filter(m=>m.who==='me'||m.who==='ai').slice(-10)
    .map(m=>({speaker:m.who==='me'?'我':'贾维斯',content:m.text}));   // push 前取
  bcurSess().push({who:'me',text});bAppendDom({who:'me',text});bsave();
  // 第零步: 沙盘路由 —— 拿不定主意/预测类自动切沙盘; 上一轮是沙盘时短语作追问
  const lastSb=[...bcurSess()].reverse().find(m=>m.who==='ai'&&m.sb);
  if(isSandboxQ(text)||(lastSb&&isFollowUp(text))){
    const follow=!!lastSb&&isFollowUp(text);
    const ctx=sbCtx();
    const issue=follow?(ctx.orig||lastSb.sbIssue||text):text;
    const history=follow?ctx.hist.concat([{q:text,a:''}]):[];
    const waitTxt=follow?'正在结合前面的推演继续翻你的档案…':'正在翻你的画像、技能、这几年的经历和相关聊天记录…';
    const tips=ORA_BOXES().map(x=>{const t=document.createElement('div');t.className='typing';x.appendChild(t);x.scrollTop=1e9;return t});
    const t0=Date.now();
    const draw=()=>{tips.forEach(t=>t.innerHTML=`<span style="display:inline-block;animation:simpulse 1.2s infinite">🎲</span> ${esc(waitTxt)} <b class="mut">${Math.floor((Date.now()-t0)/1000)}s</b>`)};
    draw();const tick=setInterval(draw,1000);
    try{
      const r=await post('/api/agent/sandbox',{issue,options:'',history});
      const res=r.result||r;
      clearInterval(tick);tips.forEach(t=>t.remove());
      const msg={who:'ai',sb:true,sbIssue:issue,sbEss:res.essence||'',sbAdv:res.advice||'',
                 html:renderSbHTML(res,follow?text:''),text:res.essence||'沙盘推演'};
      bcurSess().push(msg);bAppendDom(msg);bsave();
      if(!ORA.open&&PAGE()!=='byst'){navDot('byst',true);toast('🎲 沙盘推演已完成')}
    }catch(e){
      clearInterval(tick);tips.forEach(t=>{t.innerHTML='⚠ '+esc(e.message);setTimeout(()=>t.remove(),6000)});
    }
    BSENDING=false;btn.disabled=false;inp.focus();return;
  }
  // 第一步: 人物识别与确认(识别不到人时直接提问)
  let confirm_names=null;
  try{
    const w=await post('/api/agent/who',{message:text});
    if(w.candidates&&w.candidates.length)confirm_names=await bConfirmCard(w.candidates,boxSel);
  }catch(e){}
  const tip=document.createElement('div');tip.className='typing';$(boxSel).appendChild(tip);
  const t0=Date.now();let stepTxt='贾维斯正在回忆相关记录…';
  const draw=s=>{tip.innerHTML=`<span style="display:inline-block;animation:simpulse 1.2s infinite">⏳</span> ${esc(s)} <b class="mut">${Math.floor((Date.now()-t0)/1000)}s</b>`};
  draw(stepTxt);$(boxSel).scrollTop=1e9;
  const tick=setInterval(()=>{draw(stepTxt)},1000);
  try{
    const resp=await fetch('/api/agent/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({contact:'新朋友',mode:'ask',message:text,history:hist,stream:true,confirm_names,persona:'oracle'})});
    if(!resp.ok){const e=await resp.json().catch(()=>({}));throw new Error(e.error||('HTTP '+resp.status))}
    const reader=resp.body.getReader(),dec=new TextDecoder();let buf='',reply='',anl=null,err=null,unsure=false,cands=[];
    while(true){
      const {done,value}=await reader.read();if(done)break;
      buf+=dec.decode(value,{stream:true});
      let i;while((i=buf.indexOf('\n'))>=0){
        const line=buf.slice(0,i).trim();buf=buf.slice(i+1);
        if(!line)continue;
        let ev;try{ev=JSON.parse(line)}catch(e){continue}
        if(ev.step){stepTxt=ev.step;draw(stepTxt);$(boxSel).scrollTop=1e9}
        if(ev.done){if(ev.error)err=ev.error;else{reply=ev.reply||'';anl=ev.analysis||null;unsure=!!ev.unsure;cands=ev.candidates||[]}}
      }
    }
    clearInterval(tick);tip.remove();
    if(err)throw new Error(err);
    const a=anl||{};
    const ans=(a['回答']||reply||'').trim()||'(AI 未返回回答)';
    if(unsure){ // 贾维斯没把握 → 人工介入窗
      const anlHtml=renderAnalysisHTML(a);
      const fr=await openIntervene({question:text,aiDraft:ans,candidates:cands,contact:BCUR||'新朋友',mode:'ask',anlHTML:anlHtml});
      if(fr!=null){
        const marked=anlHtml+'<div class="mut" style="margin-top:4px">🔧 本人确认的回答</div>';
        bcurSess().push({who:'ai',text:fr,anl:marked});bAppendDom({who:'ai',text:fr,anl:marked});bsave();
      }else bAppendDom({who:'sys',text:'(已取消：贾维斯对这个问题没把握，等你亲自补充)'});
    }else{
      bcurSess().push({who:'ai',text:ans,anl:renderAnalysisHTML(a)});
      bAppendDom({who:'ai',text:ans,anl:renderAnalysisHTML(a)});bsave();
      if(!ORA.open&&PAGE()!=='byst'){navDot('byst',true);toast('🫧 贾维斯已回答：'+ans.slice(0,24)+'…')}
    }
  }catch(e){clearInterval(tick);tip.innerHTML='⚠ '+esc(e.message);setTimeout(()=>tip.remove(),6000)}
  BSENDING=false;btn.disabled=false;inp.focus();
}
function PAGE(){const a=document.querySelector('#nav a.on');return a?a.dataset.p:'home'}
/* 贾维斯抽屉: 全局悬浮入口, 与贾维斯页共用同一会话 */
function openOracle(q){
  ORA.open=true;
  $('#oraDrawer').classList.add('on');$('#oraMask').classList.add('on');
  bRender();
  if(q){$('#dchat-in').value=q;sendB('fab')}
  else setTimeout(()=>{if(ORA.open&&!BSENDING)$('#dchat-in').focus()},300);
}
function closeOracle(){ORA.open=false;
  $('#oraDrawer').classList.remove('on');$('#oraMask').classList.remove('on')}
$('#oraClose').onclick=closeOracle;
$('#oraMask').onclick=closeOracle;
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&ORA.open)closeOracle()});
/* 全局贾维斯提问 chips(认识自己 05/06 · 认识他人 · 首页) */
$$('.chip[data-ora]').forEach(c=>c.onclick=()=>openOracle(c.dataset.ora));
$$('.chip[data-go]').forEach(c=>c.onclick=()=>go(c.dataset.go));
$('#bsendbtn').onclick=()=>sendB('page');
$('#bchat-in').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendB('page')}});
$('#dsendbtn').onclick=()=>sendB('fab');
$('#dchat-in').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendB('fab')}});
$('#bClear').onclick=()=>{BSESS[bkey()]=[];bsave();bRender();
  toast('已清空贾维斯会话，后续不再携带之前的上下文')};
$('#bEqGo').onclick=()=>{go('twin');setMode('eq')};   // 高情商练习入口: 集成自数字分身页的完整练习 UI
async function loadByst(){bRender()}
LOADERS.byst=loadByst;

/* ───── 问答/沙盘合一: 自动路由, 无需切换 tab ───── */
const SB_PAT=/沙盘|推演|拿不定|纠结|要不要|值不值|值得吗|划算吗|该不该|该怎么选|会怎么做|怎么选|选哪个|换不换|帮我拿主意|帮我决策|帮我参谋|预测|预判|哪个更(好|值|合适)/;
function isSandboxQ(t){return SB_PAT.test(t||'')}
function isFollowUp(t){   // 上一轮是沙盘时的追问: 短句 + 追问口吻
  return (t||'').length<60&&(/^(那|如果|要是|假如|再|继续|为什么|凭啥|还有|换|按你|第[二三四五]种)/.test(t)||/呢[?？。!！]?$|风险|建议|概率|会怎样|结果会/.test(t))}
function sbCtx(){   // 从会话记录重建沙盘上下文(刷新页面后追问依然可用)
  const sb=bcurSess().filter(m=>m.sb);
  return {orig:(sb[0]&&sb[0].sbIssue)||'',
          hist:sb.map(m=>({q:m.sbIssue||'',a:((m.sbEss||'')+' '+(m.sbAdv||'')).trim()})).filter(x=>x.q)}}
function renderSbHTML(r,follow){
  const paths=(r.paths||[]).map(p=>`<div style="border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-top:8px">
    <b style="font-size:13px">方案：${mdlite(p.plan||'—')}</b>
    <div style="font-size:12.5px;color:#4a5568;line-height:1.75;margin-top:4px">
    ${p.short?`<div><span class="tag b">短期</span> ${mdlite(p.short)}</div>`:''}
    ${p.long?`<div style="margin-top:3px"><span class="tag p">长期</span> ${mdlite(p.long)}</div>`:''}
    ${p.risk?`<div style="margin-top:3px"><span class="tag o">风险</span> ${mdlite(p.risk)}</div>`:''}</div></div>`).join('');
  const ev=(r.evidence||[]).length?`<details style="margin-top:10px"><summary style="cursor:pointer;font-size:12px;color:#5b6572;user-select:none">🧾 判断依据（来自你的真实记录，点击展开）</summary>
    <div style="font-size:12px;color:#5b6572;line-height:1.8;margin-top:6px">${r.evidence.map(x=>'· '+mdlite(x)).join('<br>')}</div></details>`:'';
  return `${follow?`<div style="font-size:12px;color:#8a93a3;margin-bottom:6px">🔁 追问：${esc(follow)}</div>`:''}
    ${r.essence?`<div style="font-size:14px;font-weight:700;line-height:1.7">🎯 ${mdlite(r.essence)}</div>`:''}
    ${r.default?`<div style="margin-top:8px;font-size:12.5px;color:#4a5568;line-height:1.8"><span class="tag g">你的人设默认走向</span><br>${mdlite(r.default)}</div>`:''}
    ${paths?`<div style="margin-top:10px;font-size:12px;color:#8a93a3">—— 各方案推演 ——</div>${paths}`:''}
    ${r.advice?`<div style="margin-top:10px;background:var(--cg);border-radius:10px;padding:10px 12px;font-size:13px;line-height:1.8"><b>💡 强化版分身的建议</b><br>${mdlite(r.advice)}</div>`:''}
    ${ev}`;
}

/* ───── 认识自己(六模块) ───── */
const ME_BOXES=['meTraits','meSpeak','mePros','meLife','meActive','meSocial','meBlind'];
async function loadSelf(){
  api('/api/agent/style').then(renderStyle).catch(e=>{$('#styleBox').textContent='加载失败: '+e.message});
  try{const tl=await api('/api/agent/ai/timeline');renderTL(tl)}catch(e){$('#tlBox').textContent='加载失败: '+e.message}
  try{const me=await api('/api/agent/ai/me');renderMe(me)}catch(e){ME_BOXES.forEach(id=>$('#'+id).textContent='加载失败: '+e.message)}
  loadSkills();
  // 记忆搜索(原「个人记忆」页并入): 联系人下拉只填一次
  if($('#mct').options.length<=1){
    try{await loadTwin();
      CONTACTS.forEach(c=>{const o=document.createElement('option');o.value=o.textContent=c['姓名'];$('#mct').appendChild(o)});
    }catch(e){}
  }
  $('#mgo').onclick=doSearch;
  $('#mq').addEventListener('keydown',e=>{if(e.key==='Enter')doSearch()});
}
/* ── 03.5 技能与这几年做的事 ── */
function splitEv(t){   // 「技能名（日程：xxx）」→ 干净主名 + 依据(收进悬浮/折叠)
  const m=String(t||'').match(/^(.*?)[（(]\s*((?:日程|依据|聊天|话题|记录)[^）)]*)[）)]\s*$/);
  return m?{name:m[1].trim()||t,ev:m[2].trim()}:{name:String(t||'').trim(),ev:''};
}
function renderSkills(s){
  const cats=(s&&s['技能'])||[];
  if(!cats.length){$('#skBox').textContent='尚未提炼，点击上方「🛠 重新提炼技能与经历」（约 1-2 分钟）。';$('#expBox').textContent='尚未提炼。';$('#skOne').textContent='—';return}
  $('#skBox').innerHTML=cats.map(c=>{
    const items=(c['技能']||[]).map(splitEv);
    const evs=items.filter(x=>x.ev);
    return `<div style="margin-bottom:13px"><b style="font-size:12.5px">${esc(c['类别']||'其他')}</b><span class="mut" style="font-size:11px;margin-left:6px">${items.length} 项</span>
    <div style="margin-top:5px">${items.map(x=>`<span class="chip" style="cursor:${x.ev?'help':'default'};margin:3px 5px 0 0"${x.ev?` title="${esc(x.ev)}"`:''}>${esc(x.name)}</span>`).join('')}</div>
    ${evs.length?`<details style="margin-top:5px"><summary style="cursor:pointer;font-size:11px;color:#8a93a3;user-select:none;width:fit-content">依据明细（${evs.length}）</summary>
      <div style="font-size:11.5px;color:#8a93a3;line-height:1.9;margin-top:4px;padding-left:2px">${evs.map(x=>`· <b style="color:#5b6572;font-weight:600">${esc(x.name)}</b>：${esc(x.ev)}`).join('<br>')}</div></details>`:''}</div>`;
  }).join('');
  $('#skOne').innerHTML=s['一句话']?`<div style="font-size:13px;line-height:1.8;color:#1c2430">${esc(s['一句话'])}</div>`:'—';
  const yrs=(s['这几年']||[]).slice().sort((a,b)=>String(a['年份']||'').localeCompare(String(b['年份']||'')));
  $('#expBox').innerHTML=yrs.map(y=>`<div style="margin-bottom:12px">
    <div class="tlyear"><span class="tyy">${esc(y['年份']||'')}</span>${y['主题']?`<span class="tag g">${esc(y['主题'])}</span>`:''}</div>
    ${(y['事情']||[]).map(t=>{const p=splitEv(t);return `<div style="font-size:12.5px;color:#4a5568;line-height:1.75;padding-left:14px;position:relative;margin-top:4px"${p.ev?` title="${esc(p.ev)}"`:''}><span style="position:absolute;left:2px;color:#9aa3b0">·</span>${esc(p.name)}${p.ev?' <span style="color:#c4cbd4;font-size:10.5px">ⓘ</span>':''}</div>`}).join('')}</div>`).join('')
    +'<div class="mut" style="margin-top:6px">带 ⓘ 的条目悬浮可看日程依据；数据来自指尖时光日程（本人手动记录）+ 真实聊天，AI 只整理不编造。</div>';
}
async function loadSkills(){
  try{const s=await api('/api/agent/skills');renderSkills(s)}
  catch(e){$('#skBox').textContent='加载失败: '+e.message;$('#expBox').textContent='加载失败: '+e.message}
}
$('#genSk').onclick=async()=>{startWait($('#skBox'),'AI 正在从日程大事与聊天记录中提炼你的技能与经历…（约 1-2 分钟）');
  try{const r=await post('/api/agent/skills/build',{});stopWait();renderSkills(r.result);
    if(PAGE()!=='self'){navDot('self',true);toast('🛠 技能与经历已提炼完毕，点击左侧「认识自己」查看')}}
  catch(e){stopWait();$('#skBox').textContent='生成失败: '+e.message;if(PAGE()!=='self'){navDot('self',true);toast('⚠ 技能提炼失败: '+e.message)}}};
function renderStyle(s){
  const ld=s['长度分布']||{};
  const kc=(s['口头禅_高频完整短句_top30']||[]).slice(0,10)
    .map(x=>`<span class="chip" style="cursor:default">${esc(typeof x==='string'?x:(x['句']||''))}${(x&&x['次数']!=null)?`<span class="mut"> ×${x['次数']}</span>`:''}</span>`).join('');
  $('#styleBox').innerHTML=`
    <div class="stat3"><div class="st"><b>${s['平均长度_字']}</b><span>平均字数</span></div>
    <div class="st"><b>${s['带笑_比例%']}%</b><span>带笑比例</span></div>
    <div class="st"><b>${s['带微信表情_比例%']}%</b><span>带表情比例</span></div></div>
    <div style="margin:6px 0 2px" class="mut">回复长度分布</div>
    ${Object.entries(ld).map(([k,v])=>`<div class="pyb"><span class="y">${esc(k)}</span><div class="bar"><i style="width:${Math.min(100,v)}%"></i></div><span class="n">${v}%</span></div>`).join('')}
    <div style="margin:8px 0 2px" class="mut">高频口头禅</div>
    ${kc||'<span class="mut">暂无</span>'}
    ${(s['活跃时段_按小时']&&Object.keys(s['活跃时段_按小时']).length)?`<div style="margin:8px 0 2px" class="mut">最常活跃时段</div>
    <div>${Object.entries(s['活跃时段_按小时']).sort((a,b)=>b[1]-a[1]).slice(0,6).map(([h])=>`<span class="chip" style="cursor:default">${esc(h)}</span>`).join('')}</div>`:''}`;
  // 03 · 分对象说话差异(程序统计)
  const d=s['分对象说话差异_top15']||{};
  const ents=Object.entries(d).slice(0,10);
  $('#styleDiff').innerHTML=ents.length?`<div class="mut" style="margin:4px 0 6px">对不同的人，你的表达差异（程序统计）</div>`+
    ents.map(([n,v])=>`<div class="srow"><span class="k" style="width:auto;font-weight:600;color:#1c2430">${esc(n)}</span>
      <span class="mut" style="flex:1">平均 ${esc(v['平均长度'])} 字 · 常说：${esc((v['对该联系人高频短句_top8']||[]).slice(0,5).join('、'))}</span></div>`).join(''):'';
}
function renderMe(m){
  if(!m||!m['一句话总结']){
    ME_BOXES.forEach(id=>$('#'+id).textContent='尚未生成，点击上方「重新生成画像」（约 1-2 分钟）。');
    $('#shTags').innerHTML='';return}
  $('#shSummary').textContent=m['一句话总结'];
  $('#shTags').innerHTML=(m['性格特点']||[]).slice(0,5).map(t=>`<span class="tag" style="background:rgba(255,255,255,.16);color:#eafff5">${esc(t)}</span>`).join(' ');
  const lst=v=>Array.isArray(v)?v:(v?[String(v)]:[]);
  const ul=items=>items.length?`<div>${items.map(x=>`<div style="font-size:12.5px;color:#4a5568;line-height:1.7">· ${esc(x)}</div>`).join('')}</div>`:'<span class="mut">空</span>';
  $('#meTraits').innerHTML=ul(lst(m['性格特点']));
  // 说话方式: AI 输出为对象{整体风格/句式特点/口头禅/标点与表情}, 分项展示(修复 [object Object])
  const sp=m['说话方式'];
  if(sp&&typeof sp==='object'&&!Array.isArray(sp)){
    $('#meSpeak').innerHTML=['整体风格','句式特点','口头禅','标点与表情'].map(k=>sp[k]
      ?`<div class="srow"><span class="k">${k}</span><span style="flex:1">${esc(sp[k])}</span></div>`:'').join('')||'<span class="mut">空</span>';
  }else $('#meSpeak').innerHTML=ul(lst(sp));
  $('#mePros').innerHTML=ul(lst(m['优点']));
  $('#meLife').innerHTML=ul(lst(m['兴趣与生活']));
  // 活跃规律(此前遗漏未渲染)
  $('#meActive').innerHTML=m['活跃规律']
    ?`<div style="font-size:12.5px;color:#4a5568;line-height:1.8">${esc(m['活跃规律'])}</div>`:'<span class="mut">空</span>';
  $('#meSocial').innerHTML=m['社交风格']
    ?`<div style="font-size:12.5px;color:#4a5568;line-height:1.8">${esc(m['社交风格'])}</div>`:'<span class="mut">空</span>';
  $('#meBlind').innerHTML=ul(lst(m['注意点']));
}
function renderTL(t){
  const r=(t&&t.result)||t||{};
  const raw=r['年份']||[];
  // 后端结构: 年份=[{年,主题,事件:[{月份,标题,描述,依据,置信}]}] (数组, 非对象)
  const yrs=Array.isArray(raw)?raw:Object.values(raw);
  if(!yrs.length){$('#tlBox').innerHTML='尚未生成时间线，点击上方「重新生成时间线」（约 2-3 分钟）。';return}
  let h=`<div style="font-size:13px;line-height:1.7;margin-bottom:12px;color:#4a5568">${esc(r['总述']||'')}</div><div class="tl">`;
  yrs.slice().sort((a,b)=>String(a['年']||'').localeCompare(String(b['年']||''))).forEach(yv=>{
    const y=String(yv['年']||'').slice(0,4);
    h+=`<div class="tlyear"><span class="tyy">${esc(y)}</span>${yv['主题']?`<span class="tag g">${esc(yv['主题'])}</span>`:''}</div>`;
    (Array.isArray(yv['事件'])?yv['事件']:[]).forEach(ev=>{
      h+=`<div class="ev2"><div class="tm">${esc(y)}年${ev['月份']?'· '+String(ev['月份']).replace(/^0/,'')+'月':''}</div><b>${esc(ev['标题']||'')}</b><p>${esc(ev['描述']||'')}</p>
      ${ev['依据']?`<div class="tlev">💬 原话：${esc(ev['依据'])}${ev['置信']==='中'?' <span class="mut">（置信：中）</span>':''}</div>`:''}</div>`;});
  });
  const jz=r['校验']||{};
  h+=`</div><div class="mut" style="margin-top:8px">事件均经过原文回查校验${jz['剔除事件']?`（剔除 ${jz['剔除事件']} 个无法证实的事件）`:''}</div>`;
  $('#tlBox').innerHTML=h;
}
$('#genMe').onclick=async()=>{startWait($('#meTraits'),'AI 正在读取你的消息样本…（约 1-2 分钟）');
  try{const r=await post('/api/agent/ai/me',{});stopWait();renderMe(r.result);
    if(PAGE()!=='self'){navDot('self',true);toast('🪞 个人画像已生成完毕，点击左侧「认识自己」查看')}}
  catch(e){stopWait();$('#meTraits').textContent='生成失败: '+e.message;if(PAGE()!=='self'){navDot('self',true);toast('⚠ 个人画像生成失败: '+e.message)}}};
$('#genTl').onclick=async()=>{startWait($('#tlBox'),'AI 正在逐年梳理你的人生事件…（约 2-3 分钟）');
  try{const r=await post('/api/agent/ai/timeline',{});stopWait();renderTL(r.result);
    if(PAGE()!=='self'){navDot('self',true);toast('🗓 人生时间线已生成完毕，点击左侧「认识自己」查看')}}
  catch(e){stopWait();$('#tlBox').textContent='生成失败: '+e.message;if(PAGE()!=='self'){navDot('self',true);toast('⚠ 时间线生成失败: '+e.message)}}};

/* ───── 认识他人 ───── */
let NETYEAR='',NETPOS=[],PPL_CACHE={};
async function loadOthers(sub){
  $$('.otabs .tb').forEach(t=>t.onclick=()=>showOthTab(t.dataset.t));
  showOthTab(sub||'net');
  const chips=['','2022','2023','2024','2025','2026'];
  $('#yearChips').innerHTML=chips.map(y=>`<span class="chip ${y===NETYEAR?'on':''}" data-y="${y}">${y||'全部年份'}</span>`).join('');
  $$('#yearChips .chip').forEach(c=>c.onclick=()=>{NETYEAR=c.dataset.y;
    $$('#yearChips .chip').forEach(x=>x.classList.toggle('on',x.dataset.y===NETYEAR));drawNet()});
  if(sub!=='circ')drawNet();
}
async function showOthTab(t){
  $$('.otabs .tb').forEach(x=>x.classList.toggle('on',x.dataset.t===t));
  $('#tab-net').style.display=t==='net'?'':'none';
  $('#tab-circ').style.display=t==='circ'?'':'none';
  $('#tab-ppl').style.display=t==='ppl'?'':'none';
  $('#tab-gf').style.display=t==='gf'?'':'none';
  if(t==='net')drawNet();
  if(t==='circ'&&!$('#tab-circ').dataset.done){$('#tab-circ').dataset.done=1;renderCirc()}
  if(t==='ppl')loadTwin();
  if(t==='gf')loadGroupFriends();
}

/* ── 群友提炼: 扫描群聊找活跃非好友成员, 提炼为联系人 ── */
async function loadGroupFriends(){
  const box=$('#tab-gf');
  box.innerHTML='<div class="card"><div class="mut">扫描群聊文件中…（约几秒）</div></div>';
  try{
    const r=await api('/api/agent/group/discover');
    const promoted=r.promoted||[], cands=r.candidates||[];
    const jn=n=>esc(n).replace(/'/g,"\\'");
    box.innerHTML=`<div class="card"><h3>👥 已提炼的群友 <span class="sub">${promoted.length} 位 · 与普通联系人同等对待（画像 / 检索 / 原始聊天）</span></h3>
      ${promoted.map(p=>`<div class="rrow"><span><b>${esc(p['姓名'])}</b> <span class="tag p">群友</span> <span class="mut">${p['总消息']} 条 · 主群: ${esc((p['主群']||'').slice(0,14))}</span></span>
        <button class="btn gray sm" onclick="gfDemote('${jn(p['姓名'])}')">撤销</button></div>`).join('')||'<div class="mut">还没有提炼过</div>'}
      <button class="btn gray sm" style="margin-top:8px" onclick="loadGroupFriends()">🔄 重新扫描</button></div>
    <div class="card"><h3>🧲 发现的活跃群友 <span class="sub">群里聊得多但未加为私聊好友（门槛：群内消息≥60条）· 点击提炼</span></h3>
      ${cands.map(c=>`<div class="rrow"><span style="min-width:0"><b>${esc(c['姓名'])}</b> <span class="mut">${c['总消息']} 条（文本 ${c['文本消息']}）· 主群: ${esc(c['主群'].slice(0,14))} · 参与 ${c['参与群数']} 个群 · 最近发言 ${c['末次'].slice(0,10)}</span></span>
        <button class="btn sm" onclick="gfPromote(this,'${jn(c['姓名'])}')">提炼为联系人</button></div>`).join('')||'<div class="mut">没有符合条件的群友</div>'}
      ${cands.length?`<button class="btn sm" style="margin-top:8px" onclick="gfPromoteTop(this)">⚡ 批量提炼前 10 位</button>`:''}</div>`;
  }catch(e){box.innerHTML='<div class="err">'+esc(e.message)+'</div>'}
}
async function gfPromote(btn,name){
  if(btn){btn.disabled=true;btn.textContent='提炼中…'}
  try{
    await post('/api/agent/group/promote',{name});
    delete PPL_CACHE[name];
    toast('👥 「'+name+'」已提炼为联系人');
    loadGroupFriends();
  }catch(e){toast('⚠ 提炼失败: '+e.message);if(btn){btn.disabled=false;btn.textContent='提炼为联系人'}}
}
async function gfDemote(name){
  try{
    await post('/api/agent/group/demote',{name});
    delete PPL_CACHE[name];
    toast('已撤销「'+name+'」的群友联系人身份');
    loadGroupFriends();
  }catch(e){toast('⚠ 操作失败: '+e.message)}
}
async function gfPromoteTop(btn){
  if(btn){btn.disabled=true;btn.textContent='提炼中…'}
  try{
    const r=await api('/api/agent/group/discover');
    const top=(r.candidates||[]).slice(0,10);
    let ok=0;
    for(const c of top){try{await post('/api/agent/group/promote',{name:c['姓名']});ok++}catch(e){}}
    toast('👥 已批量提炼 '+ok+' 位群友');
    loadGroupFriends();
  }catch(e){toast('⚠ 批量提炼失败: '+e.message);if(btn){btn.disabled=false;btn.textContent='⚡ 批量提炼前 10 位'}}
}
/* ── 关系图: ECharts 力导向布局(缩放/平移/悬停高亮/标签防重叠均为库内置, 不再自研渲染) ── */
let NETCHART=null; // ECharts 关系图实例
let NET_SEARCH='', NET_CONTACTS=null; // 搜索关键字 / 全量联系人缓存(搜不在图里的人时补节点)
window.addEventListener('resize',()=>{if(NETCHART)NETCHART.resize()});
async function drawNet(){
  // 先读工具栏状态再清空容器(innerHTML 会连带清掉复选框)
  const strong0=$('#netStrong')?$('#netStrong').checked:true;
  const radial0=$('#netRadial')?$('#netRadial').checked:false;
  $('#netbox').innerHTML='<div class="mut" style="padding:30px">计算关系图…</div>';
  try{
    const g=await api('/api/agent/network/graph'+(NETYEAR?`?year=${NETYEAR}`:''));
    $('#netbox').innerHTML=`<div class="nettools">
        <input id="netSearch" list="netContactList" value="${esc(NET_SEARCH)}" placeholder="搜人后回车, 找不到会自动加入图中" style="padding:4px 8px;border:1px solid var(--line,#d7dee8);border-radius:8px;font-size:12px;width:180px">
        <datalist id="netContactList"></datalist>
        <label style="cursor:pointer;display:flex;gap:5px;align-items:center"><input type="checkbox" id="netStrong" ${strong0?'checked':''}> 只看强关系</label>
        <label style="cursor:pointer;display:flex;gap:5px;align-items:center" title="互动越多的人离你越近, 四个圈层各占一个方向; 取消勾选则回到自动力导向布局"><input type="checkbox" id="netRadial" ${radial0?'checked':''}> 按亲疏排列</label>
        <button class="btn gray sm" id="netReset" style="padding:4px 10px;font-size:12px">重置布局</button>
        <span class="mut">滚轮缩放 · 拖动平移 · 悬停高亮关系 · 点节点看详情</span></div>
      <div id="netchart" style="width:100%;height:640px"></div>`;
    const max=Math.max(...g.nodes.map(n=>n.value),1);
    const cats=['家人','同事/工作','朋友/其他','其他'];
    const CMAP={'家人':'#22a06b','同事/工作':'#3b82f6','朋友/其他':'#8b5cf6','其他':'#e08a00'};
    const nodes=g.nodes.filter(n=>!strong0||n.value>=max*.02);
    // 搜索: 图里没有的人(消息量少被过滤/没进 top140)从全量档案补成节点, 金框高亮
    let searchHit=null;
    if(NET_SEARCH){
      searchHit=nodes.find(n=>n.name.includes(NET_SEARCH))||g.nodes.find(n=>n.name.includes(NET_SEARCH));
      if(searchHit&&!nodes.includes(searchHit))nodes.push(searchHit);
      if(!searchHit){
        if(!NET_CONTACTS)NET_CONTACTS=await api('/api/agent/contacts');
        const c=(NET_CONTACTS.contacts||[]).find(x=>(x['姓名']||'').includes(NET_SEARCH)&&x['类别']!=='群聊');
        if(c){const b=c['圈层猜测']||'';searchHit={name:c['姓名'],value:c['总消息']||0,
                circle:['家人','同事/工作','朋友/其他'].indexOf(b)>=0?b:'其他'};
              g.nodes.push(searchHit);nodes.push(searchHit)}
      }
    }
    const names=new Set(nodes.map(n=>n.name));
    // 万凯与每个人的连线(绿色, 粗细=消息量) + 联系人之间的共同群边
    const wxLinks=nodes.map(n=>({source:'万凯',target:n.name,n:n.value,
      lineStyle:{color:'#0e9f6e',width:Math.min(4.5,.5+3*Math.sqrt(n.value/max)),opacity:.10+.30*Math.sqrt(n.value/max)}}));
    const links=wxLinks.concat(g.edges.filter(e=>names.has(e.a)&&names.has(e.b)&&(e.n>=3||!strong0))
      .map(e=>({source:e.a,target:e.b,n:e.n,
        lineStyle:{width:Math.min(4,.4+e.n/10),opacity:.2+Math.min(.55,e.n/25)}})));
    // 确定性基准位: 消息量越大半径越小(强=近); 四个圈层按人数比例各占一个扇区。
    // 无论力导向还是径向模式都把它当初始位置 —— 搜索/筛选切换后节点位置保持稳定(力导向只微调)
    const pos={};
    {
      const R0=95,R1=335;
      let ang=-Math.PI/2; // 固定起始角(顶部), 不用随机: 每次重绘朝向一致
      for(const cat of cats){
        const arr=nodes.filter(n=>(cats.indexOf(n.circle)<0?'其他':n.circle)===cat).sort((a,b)=>b.value-a.value);
        if(!arr.length)continue;
        const span=Math.PI*2*arr.length/nodes.length;
        arr.forEach((n,i)=>{
          const a=ang+span*(i+.5)/arr.length;
          const r=R0+(R1-R0)*(1-Math.sqrt(n.value/max));
          pos[n.name]=[Math.cos(a)*r,Math.sin(a)*r];
        });
        ang+=span;
      }
    }
    if(NETCHART){NETCHART.dispose();NETCHART=null}
    NETCHART=echarts.init($('#netchart'));
    if(!nodes.length){$('#netchart').innerHTML='<div class="mut" style="padding:30px">该年份暂无数据</div>';return}
    NETCHART.setOption({
      color:['#22a06b','#3b82f6','#8b5cf6','#e08a00'],
      tooltip:{confine:true,formatter:p=>p.dataType==='edge'
        ?(p.data.source==='万凯'
          ?'万凯 ↔ '+esc(p.data.target)+'<br>消息 '+p.data.n+' 条'
          :esc(p.data.source)+' ↔ '+esc(p.data.target)+'<br>共同群 '+p.data.n+' 个')
        :'<b>'+esc(p.name)+'</b><br>消息 '+p.value+' 条'},
      series:[{
        type:'graph',layout:radial0?'none':'force',roam:true,scaleLimit:{min:.5,max:4},
        categories:cats.map(c=>({name:c})),
        force:{repulsion:220,edgeLength:[35,95],gravity:.14,layoutAnimation:false},
        emphasis:{focus:'adjacency'},
        label:{show:true,fontSize:10.5,color:'#334155',formatter:p=>p.name.length>7?p.name.slice(0,7)+'…':p.name},
        labelLayout:{hideOverlap:true},
        lineStyle:{color:'#94a3b8',curveness:.15},
        data:[{name:'万凯',value:nodes.reduce((a,b)=>a+b.value,0),symbolSize:46,category:0,x:0,y:0,
            itemStyle:{color:'#0e9f6e',borderColor:'#fff',borderWidth:2.5},
            label:{color:'#fff',fontWeight:700,fontSize:13}}]
          .concat(nodes.map(n=>({name:n.name,value:n.value,
            symbolSize:n===searchHit?Math.max(26,7+24*Math.sqrt(n.value/max)):7+24*Math.sqrt(n.value/max),
            x:pos[n.name]?pos[n.name][0]:undefined,y:pos[n.name]?pos[n.name][1]:undefined,
            label:n===searchHit?{show:true,fontWeight:700,fontSize:12.5,color:'#b45309'}:undefined,
            itemStyle:n===searchHit?{color:CMAP[n.circle]||'#e08a00',borderColor:'#f59e0b',borderWidth:3,shadowBlur:14,shadowColor:'#f59e0b'}:{color:CMAP[n.circle]||'#e08a00',borderColor:'#fff',borderWidth:1.5},
            category:Math.max(0,cats.indexOf(n.circle))}))),
        links:links
      }]
    });
    NETCHART.on('click',p=>{if(p.dataType==='node')showEgo(p.name)});
    // 搜索命中: 高亮 + 让标签强制显示(绕过 hideOverlap); 后台拉全量联系人给 datalist 提示
    if(searchHit)NETCHART.dispatchAction({type:'highlight',seriesIndex:0,name:searchHit.name});
    if(!NET_CONTACTS)api('/api/agent/contacts').then(r=>{NET_CONTACTS=r;const dl=$('#netContactList');
      if(dl)dl.innerHTML=r.contacts.filter(c=>c['类别']!=='群聊').map(c=>`<option value="${esc(c['姓名'])}">`).join('')}).catch(()=>{});
    const _s=$('#netSearch');
    _s.addEventListener('keydown',e=>{if(e.key==='Enter'){NET_SEARCH=_s.value.trim();drawNet()}});
    _s.addEventListener('input',()=>{if(!_s.value.trim()&&NET_SEARCH){NET_SEARCH='';drawNet()}});
    $('#netStrong').onchange=drawNet;
    $('#netRadial').onchange=drawNet;
    $('#netReset').onclick=drawNet;
  }catch(e){$('#netbox').innerHTML='<div class="err">'+e.message+'</div>'}
}
// 关闭关系详情面板, 图表恢复占满整行
window.closeEgo=()=>{const b=$('#egobox');if(b)b.style.display='none';
  const w=document.querySelector('.netwrap');if(w)w.style.gridTemplateColumns='minmax(0,1fr)';
  if(NETCHART)setTimeout(()=>NETCHART.resize(),60)};
async function showEgo(name){
  const box=$('#egobox');box.innerHTML='<div class="mut">读取 '+esc(name)+' 的关系网…</div>';
  // 点节点才弹出详情面板; 弹出时恢复两列布局
  box.style.display='block';
  box.closest('.netwrap').style.gridTemplateColumns='minmax(0,1.7fr) minmax(0,1fr)';
  if(NETCHART)setTimeout(()=>NETCHART.resize(),60);
  try{
    const e=await api('/api/agent/network/ego?name='+encodeURIComponent(name));
    const info=e.info||{};const maxY=Math.max(...Object.values(e.per_year).map(v=>v.n),1);
    box.innerHTML=`
    <div style="display:flex;align-items:center;gap:8px"><b style="font-size:16px">${esc(name)}</b>
      <span class="tag ${CT[e.circle]||''}">${e.circle}</span>
      <span title="复制名称" style="cursor:pointer;font-size:13px" onclick="copyName('${esc(name).replace(/'/g,"\\'")}')">📋</span>
      <span title="关闭详情(图表放大)" style="cursor:pointer;margin-left:auto;font-size:15px;color:#64748b" onclick="closeEgo()">✕</span></div>
    <div class="stat3"><div class="st"><b>${info['总消息']}</b><span>总消息</span></div>
      <div class="st"><b>${info['我的占比%']}%</b><span>我占${info['我的发言']}/${info['对方发言']}</span></div>
      <div class="st"><b>${(info['首次']||'').slice(2,10)}</b><span>首次 → ${(info['末次']||'').slice(2,10)}</span></div></div>
    <div class="mut">与万凯的逐年消息量</div>
    ${Object.entries(e.per_year).map(([y,v])=>`<div class="pyb"><span class="y">${y}</span><div class="bar"><i style="width:${(v.n/maxY*100).toFixed(0)}%"></i></div><span class="n">${v.n}条(我${v.mine})</span></div>`).join('')}
    ${e.late_sessions.length?`<div class="mut" style="margin-top:10px">🌙 深夜长聊（间隔≤30分钟算连续）</div>
      ${e.late_sessions.map(s=>`<div class="rrow"><span>${s.start.slice(0,10)} ${s.start.slice(11)} → ${s.end.slice(11)}</span><span class="mut">${s.n}条</span></div>`).join('')}`:''}
    <div class="mut" style="margin-top:10px">👥 ta 参与的群（前6）</div>
    <div>${e.groups.slice(0,6).map(g=>`<span class="chip" style="cursor:default">${esc(g.group)}<span class="mut"> ${g.members}人</span></span>`).join('')||'<span class="mut">未发现</span>'}</div>
    <div class="mut" style="margin-top:10px">🔗 与 ta 同群的人（前12）</div>
    <div>${e.shared_with.slice(0,12).map(s=>`<span class="tag" style="background:#f1f4f7;color:#4a5568;margin:2px">${esc(s.name)}·${s.n}群</span>`).join('')||'<span class="mut">未发现</span>'}</div>
    <div class="mut" style="margin-top:8px">⚠ 同群聊仅代表存在共同群，不等于两人真实认识</div>
    <button class="btn sm" style="margin-top:10px" onclick="showRecent('${esc(name).replace(/'/g,"\\'")}')">💬 查看原始聊天</button>
    <button class="btn sm gray" style="margin-top:10px" onclick="openOracle('我和${esc(name).replace(/'/g,'')}的关系是怎样的？')">🫧 问贾维斯：我和 ta 的关系</button>`;
    // 联动"人物画像"下拉框: 点关系图选人时, 画像区同步显示该人的历史画像
    const sel=$('#pplSel');
    if(sel&&[...sel.options].some(o=>o.value===name)){sel.value=name;loadPplFor(name)}
  }catch(err){box.innerHTML='<div class="err">'+err.message+'</div>'}
}
async function renderCirc(){
  const [c,ls]=await Promise.all([api('/api/agent/network/circles'),api('/api/agent/life_stats')]);
  const cir=c.circles||{};
  const circleCard=(k,v,cls)=>`<div class="card" style="margin-bottom:0">
    <h3 style="color:var(--c${cls})">● ${k}</h3>
    <div class="stat3"><div class="st"><b>${v['人数']}</b><span>人数</span></div>
    <div class="st"><b>${(v['消息']/10000).toFixed(1)}w</b><span>累计消息</span></div>
    <div class="st"><b>${v['近120天活跃']}</b><span>近120天活跃</span></div></div></div>`;
  $('#tab-circ').innerHTML=`
  <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr));margin-bottom:14px">
    ${Object.entries(cir).map(([k,v])=>circleCard(k,v,CT[k]||'o')).join('')}
  </div>
  <div class="card"><h3>🌉 桥梁人物<span class="sub">同群对象跨越多个圈层 —— 你社交网络里的连接者</span></h3>
    ${(ls.bridges||[]).map(b=>`<div class="rrow"><b>${esc(b.name)}</b><span>${b.circles.map(x=>`<span class="tag ${CT[x]||''}">${x}</span>`).join(' ')} <span class="mut">跨${b.co_n}人次</span></span></div>`).join('')||'<div class="mut">暂无</div>'}
  </div>
  <div class="card"><h3>📉 关系疏远预警<span class="sub">近一年消息量 < 峰值年35% 且峰值≥100条</span></h3>
    <table><tr><th>联系人</th><th>峰值年</th><th>峰值</th><th>今年</th><th>变化</th></tr>
    ${(ls.fading||[]).map(f=>`<tr><td>${esc(f.name)}</td><td>${f.peak_year}</td><td>${f.base}</td><td>${f.now}</td>
      <td style="color:#c0392b">-${(100-f.now/f.base*100).toFixed(0)}%</td></tr>`).join('')||'<tr><td colspan="5" class="mut">没有明显疏远的关系</td></tr>'}</table>
  </div>
  <div class="card"><h3>🌙 深夜长聊 TOP<span class="sub">哪天和谁聊到几点（间隔≤30分钟算连续会话）</span></h3>
    <table><tr><th>日期</th><th>和谁</th><th>开始</th><th>结束</th><th>条数</th><th>我占</th></tr>
    ${(ls.late_sessions||[]).map(s=>`<tr><td>${s.start.slice(0,10)}</td><td>${esc(s.ct)}</td><td>${s.start.slice(11)}</td><td>${s.end.slice(11)}</td><td>${s.n}</td><td>${(s.mine/s.n*100).toFixed(0)}%</td></tr>`).join('')}</table>
  </div>
  <div class="card"><h3>💬 每个人的聊天量与回复占比<span class="sub">私聊 · 我说几条 / 对方说几条</span></h3>
    <table><tr><th>#</th><th>联系人</th><th>圈层</th><th>总消息</th><th>我说</th><th>对方说</th><th style="width:130px">我的占比</th></tr>
    ${(ls.reply_share||[]).map((r,i)=>`<tr><td>${i+1}</td><td>${esc(r.name)}</td><td><span class="tag ${CT[r.circle]||''}">${r.circle}</span></td>
      <td>${r.total}</td><td>${r.mine}</td><td>${r.other}</td>
      <td><div class="bar"><i style="width:${r.pct}%;background:${r.pct>=50?'var(--brand)':'#94a3b8'}"></i></div><span class="mut">${r.pct}%</span></td></tr>`).join('')}</table>
  </div>`;
}
async function loadPplFor(n){
  if(!n)return;
  if(PPL_CACHE[n]){renderPpl(n,PPL_CACHE[n]);return}
  $('#pplBox').innerHTML='<div class="mut">正在查看历史画像…</div>';
  try{const r=await api('/api/agent/ai/contact?name='+encodeURIComponent(n));
    if(r&&r.result&&Object.keys(r.result).length){PPL_CACHE[n]=r.result;renderPpl(n,r.result,r.generated_at)}
    else $('#pplBox').innerHTML='<div class="mut">该联系人尚未生成画像，点击「生成 / 刷新画像」。生成的画像会一直保存，切换回来时仍显示。</div>'}
  catch(e){$('#pplBox').innerHTML='<div class="mut">尚未生成画像，点击「生成 / 刷新画像」。</div>'}
}
$('#genPpl').onclick=async()=>{
  const n=$('#pplSel').value;if(!n)return;
  const box=$('#pplBox');
  box.innerHTML='<div class="anl" style="max-width:none"><b>⏳ 生成「'+esc(n)+'」的画像</b>'
    +'<div class="mut" id="pplWait" style="margin-top:4px">准备中…</div>'
    +'<div id="pplSteps" style="margin-top:6px"></div></div>';
  const t0=Date.now();
  const wt=setInterval(()=>{const w=document.getElementById('pplWait');
    if(!w){clearInterval(wt);return}
    w.textContent='已等待 '+((Date.now()-t0)/1000|0)+' 秒（预计 1-2 分钟）'},1000);
  const addStep=s=>{const p=document.getElementById('pplSteps');if(!p)return;
    const d=document.createElement('div');d.className='mut';
    d.style.cssText='font-size:12px;margin-top:3px';d.textContent='▸ '+s;p.appendChild(d)};
  try{
    const resp=await fetch('/api/agent/ai/contact',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({contact:n,stream:true})});
    if(!resp.ok){let j=null;try{j=await resp.json()}catch(e){}throw new Error((j&&j.error)||('HTTP '+resp.status))}
    const rd=resp.body.getReader(),dec=new TextDecoder();let buf='',result=null;
    while(true){
      const {value,done}=await rd.read();if(done)break;
      buf+=dec.decode(value,{stream:true});
      let i;while((i=buf.indexOf('\n'))>=0){
        const line=buf.slice(0,i).trim();buf=buf.slice(i+1);
        if(!line)continue;
        let ev;try{ev=JSON.parse(line)}catch(e){continue}
        if(ev.step)addStep(ev.step);
        if(ev.done){if(ev.error)throw new Error(ev.error);result=ev.result}
      }
    }
    clearInterval(wt);PPL_CACHE[n]=result;renderPpl(n,result);
    if(PAGE()!=='others'){navDot('others',true);toast('👥 「'+dn(n)+'」的画像已生成完毕')}
  }catch(e){clearInterval(wt);box.innerHTML='<div class="err">'+e.message+'</div>';if(PAGE()!=='others'){navDot('others',true);toast('⚠ 画像生成失败: '+e.message)}}
};
$('#pplSel').onchange=()=>loadPplFor($('#pplSel').value);
function filterPpl(q){   // 人物画像搜人: 输入名字过滤下拉(首次记录全量名单)
  const sel=$('#pplSel');
  if(!sel.dataset.all)sel.dataset.all=[...sel.options].map(o=>o.value).join('\n');
  if(!sel.dataset.all)return;
  const cur=sel.value;
  const names=sel.dataset.all.split('\n').filter(n=>!q||n.toLowerCase().includes(q.toLowerCase()));
  sel.innerHTML='';
  names.forEach(n=>{const o=document.createElement('option');o.value=o.textContent=n;sel.appendChild(o)});
  if(names.includes(cur))sel.value=cur;
}
$('#pplQ')&&$('#pplQ').addEventListener('input',e=>filterPpl(e.target.value.trim()));
function renderPpl(n,r,genAt){
  if(!r){$('#pplBox').innerHTML='<div class="mut">暂无</div>';return}
  const IC={'关系':'🤝','性格特点':'🧠','说话方式':'💬','相处方式':'🍵','共同话题':'🔥','关键事件':'📌',
    '聊天氛围':'🌡️','身份推测':'🪪','与我的关系':'❤️','事业':'💼','雷点':'⚡','负面记录':'⚠️',
    '备注':'🗒️','活跃时段':'⏰','联系方式':'📇','兴趣':'🎯','习惯':'🔁'};
  const clampable=inner=>`<div class="clampable closed">${inner}</div><span class="more">展开 ▾</span>`;
  const tx=v=>`<div class="tx">${esc(v)}</div>`;
  const lis=v=>v.map(x=>`<div class="li">${esc(typeof x==='string'?x:JSON.stringify(x))}</div>`).join('');
  const valHtml=v=>{ // string | 数组 | 嵌套对象(如 性格特点:{外在表现,内在动机}) 统一转可折叠内容
    if(typeof v==='string')return clampable(tx(v));
    if(Array.isArray(v))return clampable(lis(v));
    if(v&&typeof v==='object')return Object.entries(v).map(([k2,v2])=>
      `<div class="ppl-sec"><b>${esc(k2)}</b>${Array.isArray(v2)?clampable(lis(v2)):clampable(tx(typeof v2==='string'?v2:JSON.stringify(v2)))}</div>`).join('');
    return `<div class="mut">${esc(String(v))}</div>`;
  };
  const keys=Object.keys(r).filter(k=>k!=='总结'&&r[k]!==null&&r[k]!==''&&!(Array.isArray(r[k])&&!r[k].length));
  $('#pplBox').innerHTML=(genAt?`<div class="mut" style="margin-bottom:8px">🗓 生成于 ${esc(String(genAt).replace('T',' '))} · 每个维度默认收起，点「展开」看全文</div>`:'')
    +(r['总结']?`<div class="ppl-hero"><b>📌 一句话画像</b><p>${esc(r['总结'])}</p></div>`:'')
    +(keys.length?`<div class="ppl-grid">${keys.map(k=>
      `<div class="ppl-card"><h4>${IC[k]||'▫️'} ${esc(k)}</h4>${valHtml(r[k])}</div>`).join('')}</div>`:'<div class="mut">无结构化内容</div>');
  // 内容不足 3 行的卡片隐藏「展开」按钮
  document.querySelectorAll('#pplBox .more').forEach(m=>{
    const c=m.parentElement.querySelector('.clampable');
    if(c&&c.scrollHeight<=c.clientHeight+4)m.style.display='none'});
}
$('#pplBox').addEventListener('click',e=>{
  const m=e.target.closest('.more');if(!m)return;
  const c=m.parentElement.querySelector('.clampable');if(!c)return;
  c.classList.toggle('closed');
  m.textContent=c.classList.contains('closed')?'展开 ▾':'收起 ▴';
});
/* 关系洞察 Agent 已并入「贾维斯」: ego 面板的提问直接打开贾维斯抽屉 */
AFTERS.others=sub=>showOthTab(sub||'net');

/* 个人记忆页已并入「认识自己」; 以下仅保留记忆搜索逻辑(容器在认识自己页内) */
async function doSearch(){
  const q=$('#mq').value.trim();if(!q)return;
  $('#mctx').innerHTML='';
  $('#mres').innerHTML='<span class="mut">搜索中…</span>';
  const p=new URLSearchParams({q,limit:50,fuzzy:$('#mfuzzy').checked?'1':'0'});
  if($('#mct').value)p.set('contact',$('#mct').value);
  if($('#mfrom').value)p.set('from',$('#mfrom').value);
  if($('#mto').value)p.set('to',$('#mto').value);
  if($('#mme').checked)p.set('me','1');
  try{
    const d=await api('/api/agent/memory/search?'+p);
    const hits=d.hits||[];
    $('#mres').innerHTML=`${hits.length} 条结果${d.fuzzy?'（含近似检索）':''}${$('#mct').value?' · 限「'+esc($('#mct').value)+'」':''}`;
    const terms=q.split(/\s+/).filter(Boolean);
    const hl=s=>{let o=esc(s);terms.forEach(t=>{o=o.replace(new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'gi'),m=>`<b style="color:#0b7f58">${m}</b>`)});return o};
    $('#mres').innerHTML+=hits.map(h2=>`<div class="lc" style="cursor:pointer" data-rel="${esc(h2.rel)}" data-line="${h2.line}">
      <div class="d">${esc(h2.t.slice(0,16))}</div>
      <div style="flex:1;min-width:0"><div class="b">${esc(h2.ct)} · ${h2.s==='我'?'<b style="color:var(--brand2)">我</b>':esc(h2.s)}${h2.fuzzy?' <span class="tag b">近似</span>':''}</div>
      <div class="pv">${hl(h2.c.slice(0,120))}</div></div></div>`).join('')||'<div class="mut">没有命中</div>';
    $$('#mres .lc[data-rel]').forEach(el=>el.onclick=()=>showCtx(el.dataset.rel,el.dataset.line));
  }catch(e){$('#mres').innerHTML='<div class="err">'+e.message+'</div>'}
}
async function showCtx(rel,line){
  $('#mctx').innerHTML='<div class="ctx mut">读取上下文…</div>';
  try{const d=await api('/api/agent/memory/context?rel='+encodeURIComponent(rel)+'&line='+line);
    $('#mctx').innerHTML=`<div class="ctx"><div class="mut" style="margin-bottom:6px">${esc(rel)} 第 ${line} 行附近</div>
      ${(d.messages||[]).map(m=>`<div class="m ${m._hit?'hit':''}"><b>${esc(m.speaker==='我'?'我':m.speaker)}</b> <span class="mut">${esc(m.time||'')}</span><br>${esc(m.content||'')}</div>`).join('')}</div>`;
    $('#mctx').scrollIntoView({behavior:'smooth'});
  }catch(e){$('#mctx').innerHTML='<div class="err">'+e.message+'</div>'}
}

/* ───── 数据档案 ───── */
/* ───── 数据档案下钻: 某天/某月谁在聊 ───── */
function showDetail(d,isMonth){
  const mask=document.createElement('div');
  mask.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:999;display:flex;align-items:center;justify-content:center';
  const box=document.createElement('div');
  box.style.cssText='background:#f5f6f7;border-radius:14px;width:min(620px,92vw);max-height:78vh;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 8px 40px rgba(0,0,0,.25)';
  box.innerHTML=`<div style="padding:12px 16px;background:#ededed;border-bottom:1px solid #e0e0e0;display:flex;justify-content:space-between;align-items:center">
    <b style="font-size:14px">📊 ${isMonth?d.slice(0,7)+' 当月谁在聊':d+' 当天谁在聊'}</b>
    <span style="cursor:pointer;color:#888;font-size:18px;line-height:1" onclick="this.closest('div[style*=fixed]').remove()">✕</span></div>
    <div class="rcbody" style="overflow-y:auto;padding:12px 16px"><div class="mut">统计中…</div></div>`;
  mask.appendChild(box);
  mask.onclick=e=>{if(e.target===mask)mask.remove()};
  document.body.appendChild(mask);
  const body=box.querySelector('.rcbody');
  api('/api/agent/day/detail?date='+encodeURIComponent(d)+(isMonth?'&month=1':'')).then(r=>{
    if(!r.items||!r.items.length){body.innerHTML='<div class="mut">该时段没有聊天记录</div>';return}
    const head=`<div class="mut" style="text-align:center;margin-bottom:8px">共 ${r.total} 条消息 · ${r.people} 个联系人/群 · 按消息量排序 · 点击行看原始聊天</div>`;
    body.innerHTML=head+r.items.map(it=>{
      const cc=CC[it.circle]||'#94a3b8';
      return `<div class="drow" style="display:flex;gap:10px;align-items:center;padding:8px 6px;border-bottom:1px solid #e8eaee;cursor:pointer" onclick="showRecent('${esc(it.name).replace(/'/g,"\\'")}')">
        <div class="av" style="background:${it.is_group?'#64748b':cc};border-radius:8px">${it.is_group?'👥':esc((it.name||'?')[0])}</div>
        <div style="min-width:0;flex:1">
          <div style="font-size:13px"><b>${esc(it.name)}</b>
            <span class="tag" style="margin-left:6px">${it.is_group?'群聊':'私聊'}</span>
            ${!it.is_group&&it.circle?`<span class="tag ${CT[it.circle]||''}" style="margin-left:4px">${it.circle}</span>`:''}
          </div>
          <div class="mut" style="font-size:11.5px;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${it.last_t?it.last_t+' · ':''}${wxface(esc((it.last_c||'').slice(0,60)))||'(图片/表情)'}</div>
        </div>
        <div style="text-align:right;flex-shrink:0"><b style="font-size:14px">${it.n}</b><span class="mut" style="font-size:11px"> 条</span>
          <div class="mut" style="font-size:10.5px">我发 ${it.mine}</div></div>
      </div>`}).join('');
  }).catch(e=>{body.innerHTML='<div class="err">'+esc(e.message)+'</div>'});
}

async function loadData(){
  const [ov,daily,st]=await Promise.all([api('/api/agent/overview'),api('/api/agent/daily'),api('/api/agent/style')]);
  const mo=ov['月度总趋势']||{},hrs=ov['每小时消息数_全体']||{},wk=ov['每星期消息数_全体']||{};
  const top=ov['亲密度排行']||[],days=ov['最活跃的15天']||[];
  const moE=Object.entries(mo),moMax=Math.max(...moE.map(x=>x[1]),1);
  const hrE=Object.entries(hrs),hrMax=Math.max(...hrE.map(x=>x[1]),1);
  const wkE=['周一','周二','周三','周四','周五','周六','周日'].map(d=>[d,wk[d]||0]),wkMax=Math.max(...wkE.map(x=>x[1]),1);
  const dd=daily['每日消息数']||{};
  const dkeys=Object.keys(dd).sort();
  const dmax=Math.max(...Object.values(dd),1);
  let hm='';const start=new Date(dkeys[0]||'2022-01-01'),end=new Date(dkeys[dkeys.length-1]||'2026-11-01');
  for(let d=new Date(start);d<=end;d.setDate(d.getDate()+1)){
    const k=d.toISOString().slice(0,10),v=dd[k]||0;
    const lv=v===0?0:v/dmax;const bg=lv===0?'#e9edf1':lv<.15?'#d6f0e3':lv<.4?'#8fd8b4':lv<.7?'#3fbd85':'#0e9f6e';
    hm+=`<i style="background:${bg};cursor:pointer" onclick="showDetail('${k}')" title="${k}: ${v}条 · 点击看谁在聊"></i>`;
  }
  const total=Object.values(dd).reduce((a,b)=>a+b,0);
  $('#dataBody').innerHTML=`
  <div class="grid kpis">
    <div class="kpi"><div class="v">${(total/10000).toFixed(1)}w</div><div class="t">总消息数</div></div>
    <div class="kpi"><div class="v">${dkeys.length}</div><div class="t">覆盖天数</div></div>
    <div class="kpi"><div class="v">${(st['文本消息总数']/10000).toFixed(1)}w</div><div class="t">文本消息</div></div>
    <div class="kpi"><div class="v">${dkeys[0]||''} ~ ${(dkeys[dkeys.length-1]||'').slice(5)}</div><div class="t">时间范围</div></div>
  </div>
  <div class="card"><h3>📈 月度消息趋势<span class="sub">点击柱子看当月谁在聊</span></h3>
    <div style="display:flex;align-items:flex-end;gap:2px;height:120px;overflow-x:auto">
    ${moE.map(([k,v])=>`<div title="${k}: ${v}条 · 点击下钻" onclick="showDetail('${k}',true)" style="flex:1;min-width:7px;height:${(v/moMax*110).toFixed(0)}px;background:linear-gradient(180deg,#2fd08a,#0e9f6e);border-radius:2px 2px 0 0;cursor:pointer"></div>`).join('')}</div>
    <div style="display:flex;gap:2px" class="mut">${moE.map(([k])=>`<span style="flex:1;min-width:7px;overflow:visible;white-space:nowrap;font-size:9px">${k.slice(2,7)}</span>`).join('')}</div>
  </div>
  <div class="card"><h3>📊 月份对比<span class="sub">选两个月, 看和谁聊多人次变多/变少 · 点击人名看原始聊天</span></h3>
    <div style="display:flex;gap:10px;align-items:center;margin-bottom:6px">
      <select id="cmpA" style="min-width:120px"></select>
      <span class="mut">→</span>
      <select id="cmpB" style="min-width:120px"></select>
      <button class="btn sm" id="cmpGo">对比</button>
    </div>
    <div id="cmpOut"><div class="mut">选好两个月后点"对比"</div></div>
  </div>
  <div class="grid" style="grid-template-columns:1fr 1fr">
    <div class="card"><h3>🕐 时段分布<span class="sub">几点聊得最多</span></h3>
      ${hrE.map(([k,v])=>`<div class="pyb"><span class="y" style="width:34px">${k}</span><div class="bar"><i style="width:${(v/hrMax*100).toFixed(0)}%"></i></div><span class="n">${v}</span></div>`).join('')}</div>
    <div class="card"><h3>📅 星期分布</h3>
      ${wkE.map(([k,v])=>`<div class="pyb"><span class="y" style="width:34px">${k}</span><div class="bar"><i style="width:${(v/wkMax*100).toFixed(0)}%"></i></div><span class="n">${v}</span></div>`).join('')}</div>
  </div>
  <div class="card"><h3>🔥 每日聊天热力图<span class="sub">四年每一天 · 点击色块看当天谁在聊</span></h3><div class="hmap">${hm}</div></div>
  <div class="grid" style="grid-template-columns:1fr 1fr">
    <div class="card"><h3>💕 亲密度排行 TOP10<span class="sub">按聊天天数/回复速度计算</span></h3>
      <table><tr><th>#</th><th>姓名</th><th>圈层</th><th>总消息</th><th>聊天天</th><th>回复秒</th><th>亲密度</th></tr>
      ${top.slice(0,10).map((t,i)=>`<tr><td>${i+1}</td><td>${esc(t['姓名'])}</td><td><span class="tag ${CT[t['圈层']]||''}">${t['圈层']}</span></td>
        <td>${t['总消息']}</td><td>${t['聊天天数']}</td><td>${t['中位回复秒']}</td><td><b>${t['亲密度']}</b></td></tr>`).join('')}</table></div>
    <div class="card"><h3>⚡ 最活跃的 15 天<span class="sub">点击行下钻</span></h3>
      <table><tr><th>日期</th><th>消息数</th><th></th></tr>
      ${days.map(([k,v])=>`<tr style="cursor:pointer" onclick="showDetail('${k}')"><td>${k}</td><td>${v}</td><td><div class="bar"><i style="width:${(v/dmax*100).toFixed(0)}%"></i></div></td></tr>`).join('')}</table></div>
  </div>`;
  // ── 月份对比: 填充月份下拉(默认最近两个月) ──
  const months=[...new Set(dkeys.map(k=>k.slice(0,7)))].sort().reverse();
  const mSel=months.map(m=>`<option value="${m}">${m}</option>`).join('');
  $('#cmpA').innerHTML=mSel;$('#cmpB').innerHTML=mSel;
  $('#cmpA').value=months[1]||months[0]||'';$('#cmpB').value=months[0]||'';
  $('#cmpGo').onclick=doCmp;
}

/* ───── 月份对比 ───── */
async function doCmp(){
  const a=$('#cmpA').value,b=$('#cmpB').value;
  if(!a||!b||a===b){toast('请选择两个不同的月份');return}
  const out=$('#cmpOut');out.innerHTML='<div class="mut">对比中…</div>';
  try{
    const r=await api('/api/agent/month/compare?a='+encodeURIComponent(a)+'&b='+encodeURIComponent(b));
    const row=it=>`<div style="display:flex;align-items:center;gap:8px;padding:6px 4px;border-bottom:1px solid var(--line);cursor:pointer" onclick="showRecent('${esc(it.name).replace(/'/g,"\\'")}')">
        <div style="min-width:0;flex:1"><b style="font-size:12.5px">${esc(it.name)}</b>${it.is_group?'<span class="tag" style="margin-left:5px">群聊</span>':''}
          <div class="mut" style="font-size:11px">${it.a} 条 → ${it.b} 条</div></div>
        <b style="color:${it.d>0?'#0e9f6e':'#c0392b'};font-size:13px;flex-shrink:0">${it.d>0?'+':''}${it.d}</b></div>`;
    const col=(t,ic,arr)=>`<div><div style="margin:6px 0 2px;font-size:12.5px;font-weight:600">${ic} ${t} <span class="mut">(${arr.length})</span></div>${arr.map(row).join('')||'<div class="mut" style="padding:6px 0">无</div>'}</div>`;
    const dt=r.total_b-r.total_a;
    out.innerHTML=`<div class="mut" style="text-align:center;margin-bottom:4px">${r.a}: 共 ${r.total_a} 条 → ${r.b}: 共 ${r.total_b} 条（${dt>=0?'+':''}${dt}）</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
        ${col('聊得变多了','📈',r.inc)}
        ${col('聊得变少了','📉',r.dec)}
      </div>
      ${(r.new.length||r.gone.length)?`<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:8px">
        ${col('本月新出现','🆕',r.new)}
        ${col('本月没聊了','💤',r.gone)}</div>`:''}`;
  }catch(e){out.innerHTML='<div class="err">'+esc(e.message)+'</div>'}
}

/* ───── 系统设置 ───── */
async function loadSys(){
  const c=await api('/api/agent/config');
  $('#cfgBox').innerHTML=`
    <div style="display:flex;flex-direction:column;gap:10px">
      <label class="mut">API 地址（OpenAI 兼容）<input id="cfgUrl" value="${esc(c.base_url)}" style="width:100%;margin-top:3px"></label>
      <label class="mut">模型名<input id="cfgModel" value="${esc(c.model)}" style="width:100%;margin-top:3px"></label>
      <label class="mut">API Key${c.has_key?'（已保存，留空则不修改）':''}<input id="cfgKey" type="password" value="" style="width:100%;margin-top:3px"></label>
      <div><button class="btn" id="cfgSave">保存配置</button><span class="mut" style="margin-left:10px" id="cfgMsg"></span></div>
    </div>`;
  $('#cfgSave').onclick=async()=>{
    try{await post('/api/agent/config',{base_url:$('#cfgUrl').value.trim(),model:$('#cfgModel').value.trim(),
      api_key:$('#cfgKey').value.trim()||undefined});
      $('#cfgMsg').textContent='✓ 已保存';setTimeout(()=>$('#cfgMsg').textContent='',2000);}
    catch(e){$('#cfgMsg').textContent='✗ '+e.message}
  };
  // 聊天记录同步
  try{
    const p=await api('/api/agent/pipeline/status');
    const envOk=p.ready;
    $('#pipeBox').innerHTML=`
      <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:8px">
        <span>累计消息: <b style="color:var(--g)">${(p.total_msgs||0).toLocaleString()}</b></span>
        <span>跟踪会话: <b>${p.tracked}</b></span>
        <span>上次导出: <b>${p.last_export||'从未(首次将全量比对)'}</b></span>
        <span>状态: <b style="color:${p.running?'#d97706':'#22a06b'}">${p.running?p.phase:'就绪'}</b></span>
      </div>
      ${envOk?'':'<div class="err">环境未就绪: '+['密钥key.txt','微信数据目录','导出工具'].filter((x,i)=>[p.env.key,p.env.wechat_data,p.env.tool][i]===false).join(' / ')+'</div>'}
      <div class="mut" style="font-size:12px">· 只追加新消息, 绝不动已有历史数据<br>· 建议在微信 PC 端登录状态下同步<br>· 同步后分身/画像/关系网自动更新(约需 1-3 分钟)</div>`;
    $('#pipeRun').disabled=p.running||!envOk;
  }catch(e){$('#pipeBox').innerHTML='<span style="color:#c0392b">'+esc(e.message)+'</span>'}
  // 人工纠正记忆(介入闭环落库情况): 每次本人拍板都会存进来, 并自动注入分身记忆
  try{
    const fb=await api('/api/agent/interventions?limit=6');
    $('#fbCnt').textContent=fb.count?`共 ${fb.count} 条 · 越纠正越像你`:'';
    $('#fbBox').innerHTML=(fb.items||[]).length?fb.items.map(i=>`
      <div style="margin-bottom:9px"><b style="font-size:12.5px">${esc((i['时间']||'').slice(0,16).replace('T',' '))} · ${esc(i['联系人']||'—')}</b>
        <span class="tag" style="margin-left:4px">${esc(i['决定']||'')}</span>
        <span class="fbdel" data-ts="${esc(i['时间']||'')}" style="float:right;cursor:pointer;font-size:11px;color:#c0392b;opacity:.7">🗑 删除</span>
        <div class="mut" style="font-size:12px;margin-top:2px">问: ${esc(i['问题'])}</div>
        <div style="font-size:12.5px;margin-top:2px">→ ${esc(i['最终回答'])}</div></div>`).join('')
      :'还没有纠正记录。当分身拿不准时你会收到确认弹窗，你的决定会保存在这里，并自动注入分身记忆。';
    document.querySelectorAll('#fbBox .fbdel').forEach(el=>el.onclick=async()=>{
      if(!confirm('删除这条纠正记忆？'))return;
      try{await post('/api/agent/feedback/delete',{时间:el.dataset.ts});toast('已删除');loadSys()}catch(e){toast('⚠ 删除失败: '+e.message)}});
  }catch(e){$('#fbBox').textContent='加载失败: '+e.message}
}
$('#pipeRun').onclick=async()=>{
  const btn=$('#pipeRun'),log=$('#pipeLog');
  btn.disabled=true;log.style.display='';log.innerHTML='';
  const add=t=>{const d=document.createElement('div');d.textContent=t;log.appendChild(d);log.scrollTop=1e9};
  add('⏳ 启动同步…');
  try{
    const resp=await fetch('/api/agent/pipeline/run',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const rd=resp.body.getReader(),dec=new TextDecoder();let buf='';
    while(true){
      const {done,value}=await rd.read();if(done)break;
      buf+=dec.decode(value,{stream:true});
      let i;while((i=buf.indexOf('\n'))>=0){
        const line=buf.slice(0,i).trim();buf=buf.slice(i+1);
        if(!line)continue;
        let ev;try{ev=JSON.parse(line)}catch(e){continue}
        if(ev.step)add(ev.step);
        if(ev.done){
          if(ev.error)throw new Error(ev.error);
          const s1=ev.result.step1||{};
          add(`✅ 全部完成! 新增 ${s1['新增消息']||0} 条消息, 知识库已更新(关系网/画像/分身立即生效)`);
          if(PAGE()!=='sys'){navDot('sys',true);toast(`🔄 聊天记录同步完成：新增 ${s1['新增消息']||0} 条消息，知识库已更新`)}
        }
      }
    }
  }catch(e){add('⚠ 失败: '+e.message);if(PAGE()!=='sys'){navDot('sys',true);toast('⚠ 同步失败: '+e.message)}}
  btn.disabled=false;loadSys();
};

/* ───── 启动 ───── */
setMode('dialog');
$('#topdt').textContent=(d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`)(new Date());
loadHome().catch(e=>showErr('pg-home',e));

  // ---- 内联 onclick/ondblclick 属性走全局作用域: 把组件内函数挂到 window ----
  window.closeEgo = closeEgo;
  window.copyName = copyName;
  window.end = end;
  window.gfDemote = gfDemote;
  window.gfPromote = gfPromote;
  window.gfPromoteTop = gfPromoteTop;
  window.go = go;
  window.loadGroupFriends = loadGroupFriends;
  window.loseOracle = loseOracle;
  window.oCmp = oCmp;
  window.oSearch = oSearch;
  window.openOracle = openOracle;
  window.rawNet = rawNet;
  window.showDetail = showDetail;
  window.showRecent = showRecent;
  window.simApprove = simApprove;
  window.simDel = simDel;
  window.sync = sync;
})
</script>

<style scoped>
.agent-page{--brand:#0e9f6e;--brand2:#0b7f58;--bg:#f3f5f7;--card:#fff;--tx:#1c2430;--mut:#8a93a3;--line:#e7eaf0;
--cg:#e8f7ef;--cb:#e8f1fd;--co:#fdf3e8;--cp:#f3eefd;--cg2:#22a06b;--cb2:#3b82f6;--co2:#e08a00;--cp2:#8b5cf6}
*{margin:0;padding:0;box-sizing:border-box;font-family:"Microsoft YaHei",system-ui,sans-serif}
.agent-page{background:var(--bg);color:var(--tx);height:100vh;display:flex;overflow:hidden}
/* ───── 侧栏 ───── */
aside{width:228px;flex-shrink:0;background:linear-gradient(180deg,#0d4032 0%,#0a3227 55%,#082a20 100%);
color:#fff;display:flex;flex-direction:column;padding:18px 14px 12px}
.logo{display:flex;gap:11px;align-items:center;margin:2px 6px 20px}
.logo .av{width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,#2fd08a,#0e9f6e);
display:flex;align-items:center;justify-content:center;font-weight:700;font-size:16px}
.logo b{font-size:15.5px;display:block}
.logo span{font-size:11px;color:#9fd4bd}
nav{display:flex;flex-direction:column;gap:4px}
nav a{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:10px;color:#cfe8dd;position:relative;
font-size:13.5px;cursor:pointer;text-decoration:none}
nav a small{display:block;font-size:10.5px;color:#7fb3a0;margin-top:1px}
nav a .ic{width:20px;text-align:center;font-size:15px}
nav a.on{background:rgba(255,255,255,.14);color:#fff}
nav a:hover{background:rgba(255,255,255,.08)}
nav a .ndot{position:absolute;right:10px;top:50%;margin-top:-4px;width:8px;height:8px;border-radius:50%;background:#ff4d4f;box-shadow:0 0 0 2px rgba(255,77,79,.22);animation:simpulse 1.2s infinite}
aside .foot{margin-top:auto;font-size:10.5px;color:#6fa290;padding:0 8px;line-height:1.7}
aside .foot b{color:#9fd4bd}
/* ───── 主体 ───── */
.wrap{flex:1;display:flex;flex-direction:column;min-width:0}
#topbar{height:54px;background:#fff;border-bottom:1px solid var(--line);display:flex;align-items:center;
gap:14px;padding:0 20px;flex-shrink:0}
#topbar .q{flex:1;max-width:520px;display:flex}
#topbar input{flex:1;border:1px solid var(--line);border-radius:20px;padding:8px 16px;font-size:13px;background:#f7f8fa}
#topbar .dt{margin-left:auto;font-size:12.5px;color:var(--mut)}
main{flex:1;overflow:hidden;position:relative}
.page{position:absolute;inset:0;overflow-y:auto;padding:20px 24px 40px;display:none}
.page.on{display:block}
.page.chatpg.on{display:flex;padding:0}
h2.pt{font-size:17px;margin:2px 0 14px}
/* ───── 通用卡片 ───── */
.card{background:var(--card);border-radius:14px;padding:16px 18px;margin-bottom:14px;box-shadow:0 1px 4px rgba(16,42,67,.06)}
.card h3{font-size:14px;margin-bottom:10px;display:flex;align-items:center;gap:8px}
.card h3 .sub{font-size:11px;color:var(--mut);font-weight:400;margin-left:auto}
.grid{display:grid;gap:12px}
.tag{display:inline-block;padding:2px 9px;border-radius:10px;font-size:11px;background:#eef2f6;color:#5b6572;white-space:nowrap}
.tag.g{background:var(--cg);color:var(--cg2)} .tag.b{background:var(--cb);color:var(--cb2)}
.tag.o{background:var(--co);color:var(--co2)} .tag.p{background:var(--cp);color:var(--cp2)}
.mut{color:var(--mut);font-size:12px}
.btn{border:none;background:var(--brand);color:#fff;border-radius:9px;padding:8px 16px;font-size:13px;cursor:pointer}
.btn:hover{background:var(--brand2)} .btn.gray{background:#eef1f4;color:#444}
.btn:disabled{opacity:.5;cursor:default}
.btn.sm{padding:5px 12px;font-size:12px;border-radius:8px}
input,select,textarea{border:1px solid var(--line);border-radius:9px;padding:8px 12px;font-size:13px;outline:none;background:#fff}
input:focus,textarea:focus{border-color:var(--brand)}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:500;font-size:11.5px;white-space:nowrap}
.bar{height:7px;background:#eef1f4;border-radius:4px;overflow:hidden;margin-top:4px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--brand),#3ddc84);border-radius:4px}
.err{background:#fdecec;color:#c0392b;border-radius:9px;padding:10px 14px;font-size:13px;margin:10px 0}
.okn{background:var(--cg);color:var(--brand2);border-radius:9px;padding:10px 14px;font-size:13px;margin:10px 0}
.chip{display:inline-block;padding:4px 12px;border-radius:14px;background:#f1f4f7;font-size:12px;color:#4a5563;cursor:pointer;margin:3px 4px 0 0}
.chip:hover{background:var(--cg);color:var(--brand2)}
.chip.on{background:var(--brand);color:#fff}
/* ───── 人物画像: 摘要前置 + 分维度卡片网格 + 长文折叠 ───── */
.ppl-hero{background:linear-gradient(135deg,#f0faf5,#eef6ff);border:1px solid #d9ede2;border-radius:12px;padding:13px 16px;margin-bottom:12px}
.ppl-hero p{font-size:13.5px;line-height:1.85;margin-top:6px}
.ppl-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px;align-items:start}
.ppl-card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.ppl-card h4{font-size:13px;display:flex;align-items:center;gap:6px;margin-bottom:7px;color:#1c2430}
.ppl-sec{margin-top:8px}
.ppl-sec>b{font-size:12px;color:#5b6572;display:block;margin-bottom:2px}
.ppl-card .li{font-size:12.5px;color:#4a5568;line-height:1.7;padding-left:12px;position:relative}
.ppl-card .li::before{content:'·';position:absolute;left:2px;color:#9aa3b0}
.ppl-card .tx{font-size:12.5px;color:#4a5568;line-height:1.7;white-space:pre-wrap}
.clampable{overflow:hidden;position:relative}
.clampable.closed{max-height:5.3em}
.clampable.closed::after{content:'';position:absolute;left:0;right:0;bottom:0;height:2em;background:linear-gradient(transparent,#fff)}
.more{font-size:11.5px;color:var(--brand2);cursor:pointer;user-select:none;margin-top:4px;display:inline-block}
.more:hover{color:var(--brand)}
/* ───── 首页 ───── */
#pg-home .hero{border-radius:16px;padding:26px 30px;color:#fff;margin-bottom:16px;position:relative;overflow:hidden;
background:linear-gradient(120deg,#0d4032 0%,#0e6b4c 55%,#119a68 100%)}
#pg-home .hero h1{font-size:22px;font-weight:700}
#pg-home .hero p{margin-top:6px;font-size:13px;color:#c9ecdd}
#pg-home .hero .rt{position:absolute;right:26px;top:50%;transform:translateY(-50%);text-align:right;font-size:12px;color:#bfe6d4;line-height:1.9;opacity:.85}
#pg-home .cols{display:grid;grid-template-columns:minmax(0,2.1fr) minmax(0,1fr);gap:14px}
.slice4{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:14px}
.sl{border-radius:14px;padding:14px 16px;cursor:default;box-shadow:0 1px 4px rgba(16,42,67,.05)}
.sl .tt{font-size:11.5px;display:flex;align-items:center;gap:6px;color:#57606d}
.sl .big{font-size:17px;font-weight:700;margin-top:8px}
.sl .sub2{font-size:11.5px;color:#57606d;margin-top:6px;line-height:1.55;max-height:52px;overflow:hidden}
.sl.g{background:var(--cg)} .sl.b{background:var(--cb)} .sl.o{background:var(--co)} .sl.p{background:var(--cp)}
.liferow{display:flex;align-items:center;gap:12px;padding:11px 4px;border-bottom:1px solid var(--line);cursor:pointer}
.liferow:last-child{border-bottom:none}
.liferow:hover{background:#fafbfc}
.liferow .ic{width:34px;height:34px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0}
.liferow b{font-size:13.5px}
.liferow .desc{font-size:11.5px;color:var(--mut);margin-top:2px}
.liferow .names{margin-left:auto;font-size:11.5px;color:#6a7382;text-align:right;max-width:46%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lc{display:flex;gap:12px;padding:10px 2px;border-bottom:1px solid var(--line);align-items:flex-start}
.lc:last-child{border-bottom:none}
.lc .d{width:86px;flex-shrink:0;font-size:12px;color:var(--mut);line-height:1.5}
.lc .b{font-size:13px;margin-bottom:3px}
.lc .pv{font-size:12px;color:#5b6572;line-height:1.55}
/* 右栏 */
.rrow{display:flex;justify-content:space-between;align-items:center;padding:8px 2px;border-bottom:1px solid var(--line);font-size:12.5px}
.rrow:last-child{border-bottom:none}
.rrow b{font-size:12.5px}
/* ───── 聊天 ───── */
.side{width:225px;background:#fff;border-right:1px solid var(--line);display:flex;flex-direction:column;flex-shrink:0}
.side .hd{padding:11px 14px;font-size:12px;color:var(--mut);border-bottom:1px solid var(--line)}
.side .list{flex:1;overflow-y:auto;padding:6px}
.side .it{padding:8px 10px;border-radius:9px;font-size:12.5px;cursor:pointer;display:flex;justify-content:space-between;gap:6px;align-items:center}
.side .it:hover{background:#f5f6f7}
.side .it.on{background:var(--cg);color:var(--brand2);font-weight:600}
.side .it .n{font-size:10.5px;color:var(--mut)}
.chatwrap{flex:1;display:flex;flex-direction:column;background:#eceff1;min-width:0}
.modebar{background:#fff;border-bottom:1px solid var(--line);padding:8px 16px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.modebar .mb{padding:6px 13px;border-radius:9px;font-size:12.5px;cursor:pointer;background:#f1f4f7;color:#5b6572;border:none}
.modebar .mb.on{background:var(--brand);color:#fff}
.modebar .hint{font-size:11px;color:var(--mut)}
/* 身份横幅: 始终显示屏幕前正在输入的人是谁, 截图分享时一目了然 */
#roleBanner{padding:7px 16px;font-size:12.5px;background:#fdf3e8;color:#8a5a00;border-bottom:1px solid #f0e0c8;display:none}
#roleBanner.rb-b{background:var(--cg);color:var(--brand2);border-color:#cfe8dd}
#roleBanner b{font-weight:700}
#msgs{flex:1;overflow-y:auto;padding:18px 26px;display:flex;flex-direction:column;gap:12px}
.row{display:flex;gap:10px;align-items:flex-start;max-width:92%}
.row.me{flex-direction:row-reverse;align-self:flex-end}
.av{width:34px;height:34px;border-radius:8px;flex-shrink:0;display:flex;align-items:center;justify-content:center;color:#fff;font-size:13px;font-weight:600;background:#5b8def}
.row.me .av{background:var(--brand)}
.bub{background:#fff;border-radius:4px 12px 12px 12px;padding:9px 13px;font-size:13.5px;line-height:1.6;white-space:pre-wrap;word-break:break-word;box-shadow:0 1px 2px rgba(0,0,0,.06)}
.row.me .bub{background:#95ec69;border-radius:12px 4px 12px 12px}
/* 高情商模式: 三方气泡 */
.row .bub.eqgold{background:linear-gradient(135deg,#fff7e6,#ffe9c2);border:1px solid #f5d9a8}
.row .bub.eqgirl{background:#fff;border:1px dashed #c9ced8}
.row.eqrow .av{background:linear-gradient(135deg,#f7b733,#e08a00)!important;font-size:12px}
.eqdiag{background:#fdf8ef;border-left:3px solid #e0a53a;border-radius:8px;padding:10px 13px;font-size:12.5px;margin-top:8px;max-width:560px;line-height:1.7;color:#5a4a2f}
.eqdiag b{color:#b07a10}
.eqdiag .iss{background:#fff;border-radius:7px;padding:6px 10px;margin:5px 0}
.anl{background:#f6fafd;border-left:3px solid #3b82f6;border-radius:8px;padding:10px 13px;font-size:12.5px;margin-top:8px;max-width:560px;line-height:1.7}
.anl summary{cursor:pointer;font-weight:700;color:#2563eb;user-select:none}
.anl summary::marker{color:#3b82f6}
.anl b{color:#2563eb}
.anl .ev{background:#fff;border-radius:7px;padding:7px 10px;margin:6px 0;font-size:12px;color:#4a5568}
.typing{color:#98a2b3;font-size:12px;padding:2px 6px}
@keyframes simpulse{0%,100%{opacity:.4}50%{opacity:1}}
.av.ai{background:linear-gradient(135deg,#22d3ee,#8b5cf6)!important;font-size:12px}
.row .who{font-size:11px;color:#98a2b3;margin-bottom:3px;padding:0 2px}
.row.me .who{text-align:right}
.wc{font-size:1.2em;font-style:normal}
.inrow{display:flex;gap:10px;padding:12px 18px;background:#fff;border-top:1px solid var(--line);box-shadow:0 -2px 8px rgba(0,0,0,.03)}
.inrow textarea{flex:1;resize:none;height:44px;border-radius:10px}
/* ───── 关系网络 ───── */
.otabs{display:flex;gap:8px;margin-bottom:14px}
.otabs .tb{padding:7px 16px;border-radius:10px;background:#fff;font-size:13px;cursor:pointer;border:1px solid var(--line);color:#5b6572}
.otabs .tb.on{background:var(--brand);color:#fff;border-color:var(--brand)}
.nettools{display:flex;gap:14px;align-items:center;padding:2px 4px 8px;font-size:12px}
.netwrap{display:grid;grid-template-columns:minmax(0,1.7fr) minmax(0,1fr);gap:14px}
#netbox{background:#fff;border-radius:14px;padding:10px;box-shadow:0 1px 4px rgba(16,42,67,.06)}
.years{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;padding:2px 8px}
#egobox{background:#fff;border-radius:14px;padding:16px;box-shadow:0 1px 4px rgba(16,42,67,.06);overflow-y:auto;max-height:660px}
.stat3{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}
.stat3 .st{background:#f7f9fa;border-radius:9px;padding:8px;text-align:center}
.stat3 .st b{font-size:15px;color:var(--brand2);display:block}
.stat3 .st span{font-size:10.5px;color:var(--mut)}
.pyb{display:flex;align-items:center;gap:8px;margin:4px 0;font-size:11.5px}
.pyb .y{width:34px;color:var(--mut)}
.pyb .bar{flex:1;margin-top:0}
.pyb .n{width:70px;text-align:right;color:#5b6572}
.qabox .qa{display:flex;gap:8px;margin-top:8px}
.qabox textarea{flex:1;resize:none;height:40px}
.ev{background:#fff;border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:6px 0;font-size:12px;color:#4a5568;line-height:1.6}
/* 数据档案 */
.kpis{grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin-bottom:14px}
.kpi{background:var(--card);border-radius:14px;padding:14px 16px;box-shadow:0 1px 4px rgba(16,42,67,.06)}
.kpi .v{font-size:21px;font-weight:700;color:var(--brand2)}
.kpi .t{font-size:11.5px;color:var(--mut);margin-top:3px}
.hmap{display:grid;grid-auto-flow:column;grid-template-rows:repeat(7,11px);gap:2.5px;overflow-x:auto;padding:6px 0}
.hmap i{width:11px;height:11px;border-radius:2.5px;background:#e9edf1}
.tl{border-left:3px solid var(--cg2);margin-left:8px;padding-left:16px}
.tl .ev2{margin-bottom:14px;position:relative}
.tl .ev2:before{content:'';position:absolute;left:-22.5px;top:5px;width:9px;height:9px;border-radius:50%;background:var(--brand)}
.tl .ev2 .tm{font-size:11.5px;color:var(--mut)}
.tl .ev2 b{font-size:13.5px}
.tl .ev2 p{font-size:12.5px;color:#5b6572;margin-top:3px;line-height:1.6}
.ctx{background:#f7f9fa;border-radius:10px;padding:10px 14px;margin:8px 0;font-size:12.5px;max-height:340px;overflow-y:auto}
.ctx .m{padding:5px 0;border-bottom:1px dashed var(--line)}
.ctx .m:last-child{border:none}
.ctx .m.hit{background:var(--cg);border-radius:6px}
/* 数字人生(模拟推演) */
.simhero{background:linear-gradient(135deg,#0b1226,#101d3a 55%,#0b2b3a);color:#dfe9ff;border-radius:16px;padding:22px 24px;margin-bottom:14px;display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap;box-shadow:0 6px 24px rgba(20,40,90,.25)}
.simhero h1{font-size:20px;color:#9be7ff;margin-bottom:6px;letter-spacing:1px}
.simhero p{font-size:13px;color:#8fa3c8;max-width:600px;line-height:1.7}
.simstats{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.sst{background:rgba(255,255,255,.06);border:1px solid rgba(140,190,255,.18);border-radius:12px;padding:10px 16px;min-width:104px}
.sst .v{font-size:17px;font-weight:700;color:#7fe3ff;font-family:Consolas,monospace}
.sst .t{font-size:11px;color:#8fa3c8;margin-top:3px}
.simwarn{background:#141a2e;border-left:3px solid #ffb020;color:#c9d4f0;font-size:12px;border-radius:10px;padding:10px 14px;margin-bottom:14px;line-height:1.7}
.simops{background:#0e1526;border:1px solid #1d2b4a;color:#c9d4f0}
.simops h3{color:#9be7ff}
.simbtn{background:linear-gradient(135deg,#0ea5b7,#22d3ee);color:#03202a;font-weight:600}
.simbtn:hover{filter:brightness(1.1)}
.oprow{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.simmerge{margin-left:auto;font-size:12px;color:#8fa3c8;cursor:pointer}
#simTl{display:flex;flex-direction:column;gap:10px}
.sime{background:#0e1526;border:1px solid #1d2b4a;border-radius:12px;padding:12px 14px;color:#c9d4f0}
.sime .dt2{font-family:Consolas,monospace;color:#7fe3ff;font-weight:600}
.sime .who{color:#ffd28a;font-weight:600}
.sime .bs{font-size:11px;color:#6f7f9e;margin-top:6px;line-height:1.6}
.sime .m{font-size:13px;margin-top:6px;line-height:1.6}
.sime .m b{color:#9be7ff;font-weight:600}
.sime .warn{color:#ffb020;font-size:11px;margin-top:5px}
.sime.quiet{color:#6f7f9e;font-size:12px}
.sime .ap{color:#34d399;font-size:11px;border:1px solid #2a5c4a;border-radius:8px;padding:1px 8px;margin-left:8px}
/* 首页图标化 */
.slice4 .sl{display:flex;gap:12px;align-items:flex-start}
.bigic{width:46px;height:46px;border-radius:13px;display:flex;align-items:center;justify-content:center;font-size:23px;background:rgba(255,255,255,.62);flex-shrink:0;box-shadow:inset 0 0 0 1px rgba(0,0,0,.05)}
.slbd{flex:1;min-width:0}
.lc .av{width:38px;height:38px;border-radius:10px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;color:#fff}
/* ───── 认识自己(重构: 六模块) ───── */
.selfhero{border-radius:16px;padding:26px 30px 20px;color:#fff;margin-bottom:18px;position:relative;overflow:hidden;
background:linear-gradient(125deg,#0d4032 0%,#0e6b4c 58%,#119a68 100%)}
.selfhero .sheb{font-size:10.5px;letter-spacing:1.5px;color:#9fd4bd;margin-bottom:10px}
.selfhero h1{font-size:24px;font-weight:700}
.selfhero p{margin-top:8px;font-size:14px;color:#d8f3e6;line-height:1.7;max-width:720px}
.selfhero .shops{margin-top:14px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.selfhero .shops .btn{background:rgba(255,255,255,.16)}
.selfhero .shops .btn:hover{background:rgba(255,255,255,.28)}
.selfmod{margin:4px 0 20px}
.smhd{display:flex;align-items:baseline;gap:10px;font-size:15.5px;font-weight:700;margin:0 2px 10px}
.smhd span{font-size:11.5px;color:var(--mut);font-weight:400}
.srow{display:flex;gap:8px;margin:6px 0;font-size:12.5px;line-height:1.7}
.srow .k{flex-shrink:0;width:76px;color:var(--mut)}
.tlyear{margin:8px 0 10px;display:flex;align-items:center;gap:8px}
.tlyear .tyy{font-size:16px;font-weight:700;color:var(--brand2)}
.tlev{background:var(--cg);border-radius:8px;padding:6px 10px;margin-top:5px;font-size:12px;color:#2f5d4c;line-height:1.6}
/* ───── 贾维斯: 抽屉(由提问 chips 唤起, 不设全局悬浮按钮) ───── */
#oraMask{position:fixed;inset:0;background:rgba(15,23,32,.35);z-index:1590;opacity:0;pointer-events:none;transition:opacity .25s}
#oraMask.on{opacity:1;pointer-events:auto}
#oraDrawer{position:fixed;top:0;right:-440px;width:410px;max-width:94vw;height:100vh;background:#f7f9f8;z-index:1600;
display:flex;flex-direction:column;box-shadow:-8px 0 32px rgba(0,0,0,.18);transition:right .28s}
#oraDrawer.on{right:0}
.oraHd{padding:14px 18px;background:linear-gradient(120deg,#0d4032,#0e6b4c 70%,#119a68);color:#fff;display:flex;justify-content:space-between;align-items:center;flex-shrink:0}
.oraHd b{font-size:15px;display:block}
.oraHd .sub2{font-size:11px;color:#9fd4bd}
#dmsgs{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:12px}
#dmsgs .row{max-width:100%}
/* 贾维斯独立页消息区: 与数字分身聊天页同布局, 撑满可用高度, 输入框固定在底部 */
#bmsgs{flex:1;overflow-y:auto;padding:18px 26px;display:flex;flex-direction:column;gap:12px}
#bmsgs .row{max-width:92%}
</style>
