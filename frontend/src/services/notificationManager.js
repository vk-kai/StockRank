// 全局桌面通知管理器（单例）
// 目的：新闻 / 资金异动的桌面通知与当前所在页面解耦——只要网站开着且已登录，
// 不管在哪个路由，新到达的新闻/异动都会通知。在 main.js 启动时调用一次，
// 常驻整个会话；轮询独立于任何 Vue 组件，路由切换不影响。
//
// 鉴权：监听 Root.vue 派发的 auth-login-success / auth-logout / auth-required 事件，
//       仅在已登录时轮询；刷新后若 cookie 仍有效则通过 getAuthSession 自启。
// 开关/声音：读 localStorage（newsNotificationEnabled / newsSoundMode），
//           首页与新闻页的开关 UI 写入同一 key，全局生效。
import { getNews, getAnomalyAlerts, getStockPriceAlerts, getAuthSession } from './apiService'

const ICON = 'https://pic.0vk.top/%E8%82%A1%E7%A5%A8.png'
const NEWS_INTERVAL = 10000    // 新闻轮询 10s
const ANOMALY_INTERVAL = 15000 // 资金异动轮询 15s
const PRICE_ALERT_INTERVAL = 10000 // 价格异动轮询 10s
const SOUND_PATHS = { important: '/assets/sounds/important.mp3', normal: '/assets/sounds/normal.mp3' }

const state = {
  started: false,
  authed: false,
  newsTimer: null,
  anomalyTimer: null,
  priceAlertTimer: null,
  lastNewsId: null,
  lastAnomalyTs: '',
  lastPriceAlertTs: '',
  // 首次轮询只建立基线（记录当前最新 id/timestamp）不弹窗，避免一登录就把存量当新消息刷屏
  newsBaselined: false,
  anomalyBaselined: false,
  priceAlertBaselined: false
}

function isEnabled() {
  // 默认开启；用户在首页/新闻页切换通知开关会写入此 key
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
    // 利好(涨/回升)用🔴，利空(跌/回落)用🟢，与推送消息一致
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

async function pollNews() {
  if (!state.authed) return
  try {
    const res = await getNews(1, 5)
    if (!res || !res.success) return
    const list = Array.isArray(res.data) ? res.data : []
    if (!list.length) return
    const newest = list[0]
    if (!state.newsBaselined) { state.lastNewsId = newest.id; state.newsBaselined = true; return }
    // 收集比上次水位更新的条目（按 id 倒序走到命中 lastNewsId 为止）
    const fresh = []
    for (const n of list) {
      if (n.id === state.lastNewsId) break
      fresh.unshift(n)
    }
    // 始终推进水位——即便用户关了通知，重开时也不会把积压一次性弹出
    state.lastNewsId = newest.id
    if (fresh.length && isEnabled() && canNotify()) fresh.slice(0, 5).forEach(sendNewsNotification)
  } catch (e) { /* 401 等鉴权异常由 auth-required 事件统一处理，这里静默 */ }
}

async function pollAnomaly() {
  if (!state.authed) return
  try {
    const res = await getAnomalyAlerts()
    if (!res || !res.success || !Array.isArray(res.data) || !res.data.length) return
    const newest = res.data[0].timestamp || ''
    if (!state.anomalyBaselined) { state.lastAnomalyTs = newest; state.anomalyBaselined = true; return }
    if (!newest || newest <= state.lastAnomalyTs) return
    const fresh = res.data.filter(a => (a.timestamp || '') > state.lastAnomalyTs)
    state.lastAnomalyTs = newest
    if (fresh.length && isEnabled() && canNotify()) fresh.slice(0, 5).forEach(sendAnomalyNotification)
  } catch (e) { /* 静默 */ }
}

async function pollPriceAlert() {
  if (!state.authed) return
  try {
    const today = new Date().toISOString().slice(0, 10)
    const res = await getStockPriceAlerts(today)
    if (!res || !res.success || !Array.isArray(res.data) || !res.data.length) return
    const newest = res.data[0].timestamp || ''
    if (!state.priceAlertBaselined) { state.lastPriceAlertTs = newest; state.priceAlertBaselined = true; return }
    if (!newest || newest <= state.lastPriceAlertTs) return
    const fresh = res.data.filter(a => (a.timestamp || '') > state.lastPriceAlertTs)
    state.lastPriceAlertTs = newest
    if (fresh.length && isEnabled() && canNotify()) fresh.slice(0, 5).forEach(sendPriceAlertNotification)
  } catch (e) { /* 静默 */ }
}

function startTimers() {
  if (state.newsTimer || state.anomalyTimer || state.priceAlertTimer) return
  // 立即跑一次建立基线（不弹窗），随后定时轮询
  pollNews()
  pollAnomaly()
  pollPriceAlert()
  state.newsTimer = setInterval(pollNews, NEWS_INTERVAL)
  state.anomalyTimer = setInterval(pollAnomaly, ANOMALY_INTERVAL)
  state.priceAlertTimer = setInterval(pollPriceAlert, PRICE_ALERT_INTERVAL)
}

function stopTimers() {
  if (state.newsTimer) { clearInterval(state.newsTimer); state.newsTimer = null }
  if (state.anomalyTimer) { clearInterval(state.anomalyTimer); state.anomalyTimer = null }
  if (state.priceAlertTimer) { clearInterval(state.priceAlertTimer); state.priceAlertTimer = null }
  // 登出/失鉴权时重置基线，下次登录重新建立，既不漏报也不误报
  state.newsBaselined = false
  state.anomalyBaselined = false
  state.priceAlertBaselined = false
}

function onLogin() {
  state.authed = true
  startTimers()
}
function onLogout() {
  state.authed = false
  stopTimers()
}

export function startNotificationManager() {
  if (state.started) return
  state.started = true
  window.addEventListener('auth-login-success', onLogin)
  window.addEventListener('auth-logout', onLogout)
  window.addEventListener('auth-required', onLogout)
  // 初始鉴权探测：刷新页面后若 cookie 仍为登录态，直接启动轮询
  getAuthSession()
    .then(s => { if (s && s.authenticated) onLogin() })
    .catch(() => {})
}
