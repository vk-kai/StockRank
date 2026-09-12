/**
 * 缠论「走势结构的两重表里关系」状态计算
 *
 * 缠中说禅笔定理：任何当下，在某级别K线里，走势必然落在一段确定方向的笔中，
 * 且只有两种位置——①分型构造中 ②分型确认后延伸为笔的过程中。
 * 于是每个级别可用 (X,Y) 两元组精确编码：
 *   X = 笔方向（+1 向上 / -1 向下）
 *   Y = 位置（0 分型构造中 / 1 延伸为笔中）
 * 四态：(1,1)涨中延伸、(-1,1)跌中延伸、(1,0)顶分型、(-1,0)底分型。
 *
 * 多级别连读即"病情记录矩阵"：小级别先变、大级别后变 → 未病/欲病/已病。
 * 本模块把这套状态算出来，并用直观说法替换"已病"等术语，供前端展示。
 */
import type { KlineData } from "../types";
import { buildChanAutoDrawResult, type ChanAutoDrawResult } from "./chan";

// 级别 period → 中文名
export const LEVEL_LABELS: Record<string, string> = {
  "1": "1分钟",
  "5": "5分钟",
  "15": "15分钟",
  "30": "30分钟",
  "60": "60分钟",
  "120": "120分钟",
  daily: "日线",
  weekly: "周线",
  monthly: "月线",
};

// 两组可选级别（小→大）
export const BIAOLI_GROUPS = {
  short: { label: "短线（5分钟 / 30分钟 / 日线）", periods: ["5", "30", "daily"] },
  long: { label: "长线（30分钟 / 日线 / 周线）", periods: ["30", "daily", "weekly"] },
} as const;

export type BiaoliGroupKey = keyof typeof BIAOLI_GROUPS;

export interface LevelBiaoliState {
  period: string;
  level: string; // 中文名
  X: 1 | -1; // +1 向上笔 / -1 向下笔
  Y: 0 | 1; // 0 分型构造中 / 1 延伸为笔中
  code: string; // "(1,1)" 等原始编码
  penLabel: string; // 直观："上涨·延伸中"
  hint: string; // 一句话解释
  klineCount: number;
}

export interface BiaoliResult {
  groupKey: BiaoliGroupKey;
  groupLabel: string;
  levels: LevelBiaoliState[]; // 小→大
  stage: string; // 阶段标签（直观说法）
  stageDesc: string; // 阶段说明（对应 未病/欲病/已病 的直观解释）
  verdict: string; // 综合判断一句话
  zenConcept: string; // 对应的缠论原始概念（未病/欲病/已病/…），便于对照
}

// 末尾 3 根K线是否构成与当前笔反向的分型（顶/底分型代理）
function hasOppositeTailFractal(klines: KlineData[], currentDir: "up" | "down"): boolean {
  if (klines.length < 3) return false;
  const a = klines[klines.length - 3];
  const b = klines[klines.length - 2];
  const c = klines[klines.length - 1];
  if (currentDir === "up") {
    // 当前向上延伸 → 尾部出现顶分型视为"见顶分型构造中"
    return b.high > a.high && b.high > c.high;
  }
  // 当前向下延伸 → 尾部出现底分型视为"见底分型构造中"
  return b.low < a.low && b.low < c.low;
}

// 从 chan.ts 结果 + 原始K线推出单级别 (X,Y)
function deriveXY(res: ChanAutoDrawResult, klines: KlineData[]): { X: 1 | -1; Y: 0 | 1 } {
  const pens = res.pens || [];
  if (pens.length === 0) {
    // 笔不足：用首末收盘价粗判方向，视为延伸
    if (klines.length < 2) return { X: 1, Y: 1 };
    const X: 1 | -1 = klines[klines.length - 1].close >= klines[0].close ? 1 : -1;
    return { X, Y: 1 };
  }
  // chan.ts 在末尾补一条 pen-active-* 的"延伸中"未确认笔
  const activePen = res.lines.find(
    (l) => l.kind === "pen" && !l.confirmed && l.id.startsWith("pen-active")
  );
  if (activePen) {
    const X: 1 | -1 = activePen.direction === "up" ? 1 : -1;
    const Y: 0 | 1 = hasOppositeTailFractal(klines, activePen.direction) ? 0 : 1;
    return { X, Y };
  }
  // 无延伸笔：上一笔刚确认完，正停在端点分型 → 分型构造中
  const last = pens[pens.length - 1];
  return { X: (last.direction === "up" ? 1 : -1) as 1 | -1, Y: 0 };
}

function penLabelOf(X: 1 | -1, Y: 0 | 1): { penLabel: string; hint: string } {
  if (X === 1 && Y === 1) return { penLabel: "上涨 · 延伸中", hint: "向上笔还在推进，涨势延续" };
  if (X === 1 && Y === 0) return { penLabel: "上涨 · 顶分型", hint: "涨势出现停顿，可能见顶" };
  if (X === -1 && Y === 1) return { penLabel: "下跌 · 延伸中", hint: "向下笔还在推进，跌势延续" };
  return { penLabel: "下跌 · 底分型", hint: "跌势出现停顿，可能见底" };
}

// 单级别计算
export function computeLevelState(period: string, klines: KlineData[]): LevelBiaoliState {
  const level = LEVEL_LABELS[period] || period;
  const res = buildChanAutoDrawResult(klines);
  const { X, Y } = deriveXY(res, klines);
  const { penLabel, hint } = penLabelOf(X, Y);
  return {
    period,
    level,
    X,
    Y,
    code: `(${X === 1 ? "1" : "-1"},${Y})`,
    penLabel,
    hint,
    klineCount: klines.length,
  };
}

// 多级别综合判定 → 阶段标签（直观说法）+ 对应缠论概念
export function classifyBiaoliLevels(
  levels: LevelBiaoliState[],
  groupLabel: string
): Pick<BiaoliResult, "stage" | "stageDesc" | "verdict" | "zenConcept"> {
  if (levels.length < 3) {
    return {
      stage: "数据不足",
      stageDesc: "级别数据不足，无法综合判断。",
      verdict: "请确保每个级别都取到了足够K线。",
      zenConcept: "—",
    };
  }
  const [s, , l] = levels; // 小级别 / 大级别（中间级别辅助）
  const allUpExt = levels.every((v) => v.X === 1 && v.Y === 1);
  const allDownExt = levels.every((v) => v.X === -1 && v.Y === 1);

  if (allUpExt) {
    return {
      stage: "强势上涨",
      stageDesc: "三个级别同步向上延伸，方向一致、动能最强——最健康的上涨状态。",
      verdict: `${groupLabel}：多级别共振向上，涨势强劲。`,
      zenConcept: "健康（共振）",
    };
  }
  if (allDownExt) {
    return {
      stage: "弱势下跌",
      stageDesc: "三个级别同步向下延伸，方向一致、跌势最盛——最弱的下跌状态。",
      verdict: `${groupLabel}：多级别共振向下，跌势正盛。`,
      zenConcept: "病重（共振）",
    };
  }

  const largeUp = l.X === 1;
  const smallAgainst = s.X !== l.X; // 小级别已反手
  const largeTurning = l.Y === 0; // 大级别出现分型

  if (largeUp) {
    if (largeTurning && smallAgainst) {
      return {
        stage: "见顶观察",
        stageDesc: "大级别已现顶分型，小级别已先向下；按原文，(1,0) 后仍有重新延续或转弱两种演化，要继续观察小级别走势类型和中枢震荡。",
        verdict: "大级别由 (1,1) 进入 (1,0)，小级别先弱，先减风险、等市场选择。",
        zenConcept: "(1,0) 后分类观察",
      };
    }
    if (largeTurning || smallAgainst) {
      return {
        stage: "见顶预警",
        stageDesc: "大级别仍在涨，但小级别率先停顿/回落——早期预警，留意卖点、控制仓位。",
        verdict: "大级别仍涨、小级别率先走弱，见顶预警。",
        zenConcept: "未病（早期预警）",
      };
    }
    return {
      stage: "震荡偏强",
      stageDesc: "大级别向上但小级别未完全同步，处于震荡整理，方向未明。",
      verdict: "大级别向上、级别间未共振，震荡偏强。",
      zenConcept: "欲病（转折酝酿）",
    };
  }

  // 大级别向下
  if (largeTurning && smallAgainst) {
    return {
      stage: "见底观察",
      stageDesc: "大级别已现底分型，小级别已先向上；按原文，(-1,0) 后仍可能重新延续或转强，要继续观察小级别走势类型和中枢震荡。",
      verdict: "大级别由 (-1,1) 进入 (-1,0)，小级别先强，关注买点但先等确认。",
      zenConcept: "(-1,0) 后分类观察",
    };
  }
  if (largeTurning || smallAgainst) {
    return {
      stage: "见底预警",
      stageDesc: "大级别仍在跌，但小级别率先止跌/回升——早期预警，留意买点。",
      verdict: "大级别仍跌、小级别率先走强，见底预警。",
      zenConcept: "未病（早期预警）",
    };
  }
  return {
    stage: "震荡偏弱",
    stageDesc: "大级别向下但小级别未完全同步，处于震荡整理，方向未明。",
    verdict: "大级别向下、级别间未共振，震荡偏弱。",
    zenConcept: "欲病（转折酝酿）",
  };
}

// 组装完整结果（K线由调用方取好传入）
export function buildBiaoliResult(
  groupKey: BiaoliGroupKey,
  klinesByPeriod: Record<string, KlineData[]>
): BiaoliResult {
  const group = BIAOLI_GROUPS[groupKey];
  const levels = group.periods.map((p) => computeLevelState(p, klinesByPeriod[p] || []));
  const cls = classifyBiaoliLevels(levels, group.label);
  return {
    groupKey,
    groupLabel: group.label,
    levels,
    ...cls,
  };
}
