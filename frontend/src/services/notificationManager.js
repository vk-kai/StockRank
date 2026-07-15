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
    const labels = (a.labels && a.labels.length) ? a.labels.join('、') : '资金异动'
    const nf = a.net_flow != null ? `净流入${a.net_flow >= 0 ? '+' : ''}${Number(a.net_flow).toFixed(2)}亿` : ''
    const chg = a.change_pct != null ? ` ${a.change_pct >= 0 ? '+' : ''}${Number(a.change_pct).toFixed(2)}%` : ''
    const lead = a.lead_stock ? ` 龙头${a.lead_stock}` : ''
    const n = new Notification(`🚨 资金异动 · ${a.sector}`, {
      body: `${labels}｜${nf}${chg}${lead}`,
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
    const label = a.label || a.type || '价格异动'
    const bullish = /大涨|拉升|高开|涨停|回升|反弹|撬板/.test(label)
    const bearish = /大跌|打压|低开|跌停|回落|炸板/.test(label)
    const icon = bullish ? '🔴' : bearish ? '🟢' : (a.pct || 0) >= 0 ? '🔴' : '🟢'
    const n = new Notification(`${icon} 价格异动 · ${a.name || a.code}`, {
      body: `${label}｜${pct}${price}`,
      icon: ICON,
      tag: a.timestamp,
      requireInteraction: true
    })
    n.onclick = () => { window.focus(); n.close() }
    const mode = getSoundMode()
    if (mode === 'all' || mode === 'important') playSound('important')
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

  // 以下事件需要检查通知开关和权限
  if (!isEnabled() || !canNotify()) return

  switch (msg.type) {
    case 'news':
      if (msg.data) sendNewsNotification(msg.data)
      break
    case 'anomaly':
      if (msg.data) sendAnomalyNotification(msg.data)
      break
    case 'price_alert':
      if (msg.data) sendPriceAlertNotification(msg.data)
      break
  }
}

// ==================== WebSocket 连接管理 ====================

function connectSocket() {
  if (state.socket && state.socket.connected) return

  // 自动检测WebSocket地址（同源或显式指定）
  const wsUrl = window.location.protocol === 'https:'
    ? `https://${window.location.host}`
    : `http://${window.location.hostname}:5000`

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
