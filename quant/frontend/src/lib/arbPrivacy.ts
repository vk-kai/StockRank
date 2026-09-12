// 套利监控个股名称隐藏(小眼睛开关):截屏/投屏时打码配对卡片、告警历史、弹窗横幅里的个股名称。
// 状态存 localStorage,经自定义事件广播,让面板外的 WS 弹窗(App 层)实时跟着切换。
const HIDDEN_KEY = "tz_arb_names_hidden";
const CHANGE_EVENT = "tz-arb-names-visibility";

export function isArbNameHidden(): boolean {
  try {
    return localStorage.getItem(HIDDEN_KEY) === "1";
  } catch {
    return false;
  }
}

export function setArbNameHidden(hidden: boolean): void {
  try {
    localStorage.setItem(HIDDEN_KEY, hidden ? "1" : "0");
  } catch {}
  try {
    window.dispatchEvent(new Event(CHANGE_EVENT));
  } catch {}
}

/** 订阅开关变化;返回取消订阅函数。 */
export function onArbNameHiddenChange(listener: () => void): () => void {
  try {
    window.addEventListener(CHANGE_EVENT, listener);
    return () => window.removeEventListener(CHANGE_EVENT, listener);
  } catch {
    return () => {};
  }
}

/** 打码:名称整个抹掉,代码只留交易所前两位(60/00/30/68)方便自己辨认。 */
export function maskArbStockLabel(code?: string | null): string {
  const c = (code || "").trim();
  const head = c.length > 2 ? c.slice(0, 2) : "";
  return `***(${head}****)`;
}
