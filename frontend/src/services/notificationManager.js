// 全局桌面通知管理器（单例）
// 通过 WebSocket 接收服务器实时推送，触发桌面通知。
// 事件类型：news(新闻) / anomaly(资金异动) / price_alert(价格异动) / data_update(数据刷新)
//
// 鉴权：监听 auth-login-success / auth-logout / auth-required 事件，
//       仅在已登录时连接 WebSocket。
// 开关/声音：读 localStorage（newsNotificationEnabled / newsSoundMode），
//           首页与新闻页的开关 UI 写入同一 key，全局生效。
import { io } from 'socket.io-client'
import { getAuthSession } from './apiService'

const ICON = 'https://pic.0vk.top/%E8%82%A1%E7%A5%A8.png'
const SOUND_PATHS = { important: '/assets/sounds/important.mp3', normal: '/assets/sounds/normal.mp3' }

const state = {
  started: false,
  authed: false,
  socket: null,
  reconnectTimer: null,
}

function isEnabled() {
  return localStorage.getItem('newsNotificationEnabled') !== 'false'
}
function getSoundMode() {
  const s = localStorage.getItem('newsSoundMode')
  return ['none', 'important', 'all'].includes(s) ? s : 'all'
}
function getNewsLevel() {
  const level = localStorage.getItem('newsNotificationLevel')
  return level === 'important' ? 'important' : 'all' // 默认全部
}
function canNotify() {
  return typeof Notification !== 'undefined' && Notification.permission === 'granted'
}

function playSound(type) {
  try {
    const a = new Audio(SOUND_PATHS[type] || SOUND_PATHS.normal)
    a.volume = 0.5
    a.play().catch(() => {})
  } catch (e) { /* 忽略 */ }
}

function isNewsImportant(news) {
  return news.importance === '3' || (news.ai_analysis && news.ai_analysis.level === '重大')
}

// ==================== 桌面通知 ====================

function sendNewsNotification(news) {
  try {
    const important = isNewsImportant(news)
    let body = news.content || ''
    if (body.length > 100) body = body.slice(0, 100) + '...'
    const n = new Notification(news.title, {
      body,
      icon: ICON,
      tag: news.id,
      requireInteraction: important
    })
    n.onclick = () => { window.focus(); if (news.url) window.open(news.url, '_blank'); n.close() }
    const mode = getSoundMode()
    if (mode === 'all') playSound(important ? 'important' : 'normal')
    else if (mode === 'important' && important) playSound('important')
  } catch (e) { /* 忽略 */ }
}

function sendAnomalyNotification(a) {
  try {
    const topLabel = (a.labels && a.labels.length) ? a.labels[0] : ''
    const nf = a.net_flow != null ? Number(a.net_flow) : 0
    const subs = a.subs || []
    const isRevUp = subs.some(s => String(s) === 'reversal_up')
    const isRevDown = subs.some(s => String(s) === 'reversal_down')
    // 颜色：反转按方向（V底=流出减缓/转流入=红/看涨，V顶=流入减缓/转流出=绿/看跌）；否则按净流入正负
    const arrow = isRevUp ? '🔴' : isRevDown ? '🟢' : (nf >= 0 ? '🔴' : '🟢')
    const nfStr = `净流入${nf >= 0 ? '+' : ''}${nf.toFixed(2)}亿`
    const chg = a.change_pct != null ? ` ${a.change_pct >= 0 ? '+' : ''}${Number(a.change_pct).toFixed(2)}%` : ''
    const lead = a.lead_stock ? ` 龙头${a.lead_stock}` : ''
    // 有反转明细时优先展示"之前→现在/减缓%"，更直观
    const labels = (a.labels || []).filter(Boolean)
    const body = a.reversal_detail
      ? `${a.reversal_detail}｜${chg}${lead}`
      : `${labels.length ? labels.join('、') : '资金异动'}｜${chg}${lead}`
    const n = new Notification(`${arrow} ${a.sector}${topLabel} ${nfStr}`, {
      body,
      icon: ICON,
      tag: `${a.date}-${a.time}-${a.sector}`,
      requireInteraction: true
    })
    n.onclick = () => { window.focus(); n.close() }
    const mode = getSoundMode()
    if (mode === 'all' || mode === 'important') playSound('important')
  } catch (e) { /* 忽略 */ }
}

function sendPriceAlertNotification(a) {
  try {
    const pct = a.pct != null ? (a.pct >= 0 ? '+' : '') + Number(a.pct).toFixed(2) + '%' : ''
    const price = a.price != null ? ` 现价${a.price}` : ''
    const label = a.label || a.type || '异动'
    const bullish = /大涨|拉升|高开|涨停|回升|反弹|撬板/.test(label)
    const bearish = /大跌|打压|低开|跌停|回落|炸板/.test(label)
    const icon = bullish ? '🔴' : bearish ? '🟢' : (a.pct || 0) >= 0 ? '🔴' : '🟢'
    // 标题直接关键信息，不加"价格异动"前缀
    const n = new Notification(`${icon} ${a.name || a.code}${label} ${pct}`, {
      body: `现价${a.price || '--'}｜${label}`,
      icon: ICON,
      tag: a.timestamp,
      requireInteraction: true
    })
    n.onclick = () => { window.focus(); n.close() }
    const mode = getSoundMode()
    if (mode === 'all' || mode === 'important') playSound('important')
  } catch (e) { /* 忽略 */ }
}

function sendArbAlertNotification(a) {
  try {
    // TrendZen 套利背离:买点/偏多=红(看涨机会),卖点/偏空=绿,与价格异动的红涨绿跌一致
    const bullish = String(a.direction || '').includes('buy')
    const icon = bullish ? '🔴' : '🟢'
    const pct = a.stock_pct != null ? (a.stock_pct >= 0 ? '+' : '') + Number(a.stock_pct).toFixed(2) + '%' : ''
    const bench = a.bench_pct != null
      ? ` 基准${a.bench_label || ''} ${a.bench_pct >= 0 ? '+' : ''}${Number(a.bench_pct).toFixed(2)}%`
      : ''
    const n = new Notification(`${icon} ${a.name || a.code}套利背离 ${a.label || ''} ${pct}`, {
      body: `${a.reason || ''}${bench ? '\n' + bench : ''}`,
      icon: ICON,
      tag: a.tz_id ? `tz-arb-${a.tz_id}` : a.timestamp,
      requireInteraction: true
    })
    n.onclick = () => { window.focus(); n.close() }
    const mode = getSoundMode()
    if (mode === 'all' || mode === 'important') playSound('important')
  } catch (e) { /* 忽略 */ }
}

// 个股异动（Stock Pulse）轮次记录：一条轮次弹一条通知，正文取最显著的板块聚集
function sendPulseNotification(record) {
  try {
    if (!record) return
    const closing = !!record.closing
    const stocks = record.stocks || []
    // ---- 正文：板块聚集明细 + 涨跌停名单（有名字才一目了然） ----
    const lines = []
    for (const sec of (record.sectors || []).slice(0, 2)) {
      const h = (sec.hits || [])[0]
      if (!h) continue
      const secLabel = sec.level === 'l2' && sec.l1 && sec.l1 !== sec.sector
        ? `${sec.l1}·${sec.sector}` : sec.sector
      const mid = sec.median_pct != null ? `${sec.median_pct >= 0 ? '+' : ''}${sec.median_pct}%` : ''
      lines.push(`${secLabel} ${h.count}/${sec.total} 只${h.label}（中位 ${mid}）`)
    }
    const ups = stocks.filter(s => (s.pct || 0) > 0)
    const downs = stocks.filter(s => (s.pct || 0) <= 0)
    if (ups.length) lines.push(`涨停：${ups.slice(0, 5).map(x => x.name).join('、')}${ups.length > 5 ? ` 等${ups.length}只` : ''}`)
    if (downs.length) lines.push(`跌停：${downs.slice(0, 5).map(x => x.name).join('、')}${downs.length > 5 ? ` 等${downs.length}只` : ''}`)
    if (closing && record.summary) {
      const s = record.summary
      lines.push(`全天：涨${s.advance} 跌${s.decline}，涨停${s.limit_up} 跌停${s.limit_down}`)
    }
    // ---- 无实质内容不推送（纯温度轮/空记录） ----
    if (!lines.length) return
    // ---- 标题：最显著信号在前、时间在后 ----
    const sec0 = (record.sectors || [])[0]
    const h0 = sec0 && (sec0.hits || [])[0]
    const signals = []
    if (h0) {
      const secLabel = sec0.level === 'l2' && sec0.l1 && sec0.l1 !== sec0.sector ? `${sec0.l1}·${sec0.sector}` : sec0.sector
      signals.push(`${secLabel}${h0.count}只${h0.label}`)
    }
    if (ups.length) signals.push(`涨停${ups.length}只`)
    if (downs.length) signals.push(`跌停${downs.length}只`)
    const head = signals.slice(0, 2).join('·') || (closing ? '全天复盘' : '异动')
    const title = closing ? `📊 ${head}｜收盘` : `📈 ${head}｜${record.time || ''}`
    const n = new Notification(title, {
      body: lines.join('\n'),
      icon: ICON,
      tag: `pulse-${record.date}-${record.time}`,
      requireInteraction: !closing
    })
    n.onclick = () => { window.focus(); n.close() }
    const mode = getSoundMode()
    if (mode === 'all' || mode === 'important') playSound('important')
  } catch (e) { /* 忽略 */ }
}

function sendTestNotification(data) {
  // 手动「测试」按钮触发：走真实 WebSocket 通道到达，弹一条桌面通知用于人眼验证。
  try {
    const n = new Notification((data && data.title) || '🔔 推送测试', {
      body: (data && data.body) || 'WebSocket 推送链路正常',
      icon: ICON,
      tag: 'push-test'
    })
    n.onclick = () => { window.focus(); n.close() }
  } catch (e) { /* 忽略 */ }
}

// ==================== WebSocket 推送处理 ====================

function handlePushEvent(msg) {
  if (!msg || !msg.type) return

  // data_update 事件：触发全局自定义事件，让各页面组件自行刷新数据
  if (msg.type === 'data_update') {
    window.dispatchEvent(new CustomEvent('ws-data-update', { detail: msg.data }))
    return
  }

  // push_ping：服务监控的静默心跳，立即回 pong，不弹通知、不受通知开关影响
  if (msg.type === 'push_ping') {
    if (msg.data && msg.data.nonce && state.socket) {
      try { state.socket.emit('push_pong', { nonce: msg.data.nonce }) } catch (e) { /* 忽略 */ }
    }
    return
  }

  // 以下事件需要检查通知开关和权限
  if (!isEnabled() || !canNotify()) return

  switch (msg.type) {
    case 'news':
      // 根据桌面通知级别设置过滤新闻
      if (msg.data) {
        const newsLevel = getNewsLevel()
        if (newsLevel === 'all' || isNewsImportant(msg.data)) {
          sendNewsNotification(msg.data)
        }
      }
      break
    case 'anomaly':
      if (msg.data) sendAnomalyNotification(msg.data)
      break
    case 'price_alert':
      if (msg.data) sendPriceAlertNotification(msg.data)
      break
    case 'arb_alert':
      if (msg.data) sendArbAlertNotification(msg.data)
      break
    case 'stock_pulse':
      // 个股异动轮次：桌面通知 + 通知个股异动页面刷新
      if (msg.data) {
        sendPulseNotification(msg.data)
        window.dispatchEvent(new CustomEvent('ws-stock-pulse', { detail: msg.data }))
      }
      break
    case 'push_test':
      if (msg.data) sendTestNotification(msg.data)
      break
  }
}

// ==================== WebSocket 连接管理 ====================

function connectSocket() {
  // 如果已有连接且正常，直接返回
  if (state.socket && state.socket.connected) {
    console.log('[WS] 已有连接，跳过创建')
    return
  }

  // 如果有旧连接但已断开，先清理
  if (state.socket && !state.socket.connected) {
    console.log('[WS] 清理旧连接')
    state.socket.disconnect()
    state.socket = null
  }

  // 自动检测WebSocket地址（同源或显式指定）
  const wsUrl = window.location.protocol === 'https:'
    ? `https://${window.location.host}`
    : `http://${window.location.hostname}:5000`

  console.log('[WS] 创建新连接:', wsUrl)
  const socket = io(wsUrl, {
    transports: ['websocket', 'polling'],
    reconnection: true,
    reconnectionAttempts: Infinity,
    reconnectionDelay: 2000,
    reconnectionDelayMax: 30000,
    timeout: 10000,
    path: '/socket.io/'
  })

  socket.on('push', handlePushEvent)

  socket.on('connect', () => {
    console.log('[WS] 已连接', socket.id)
  })

  socket.on('disconnect', (reason) => {
    console.log('[WS] 断开', reason)
  })

  socket.on('connect_error', (err) => {
    console.warn('[WS] 连接失败', err.message)
  })

  state.socket = socket
}

function disconnectSocket() {
  if (state.socket) {
    state.socket.disconnect()
    state.socket = null
  }
}

function onLogin() {
  state.authed = true
  connectSocket()
}

function onLogout() {
  state.authed = false
  disconnectSocket()
}

export function startNotificationManager() {
  if (state.started) return
  state.started = true
  window.addEventListener('auth-login-success', onLogin)
  window.addEventListener('auth-logout', onLogout)
  window.addEventListener('auth-required', onLogout)
  // 初始鉴权探测：刷新页面后若 cookie 仍为登录态，直接连接
  getAuthSession()
    .then(s => { if (s && s.authenticated) onLogin() })
    .catch(() => {})
}
