import type { BenchKind } from "./market";

export interface ArbPair {
  id: number;
  owner_username?: string | null;
  stock_code: string;
  stock_name: string;
  bench_kind: BenchKind;
  bench_code: string;
  bench_label: string;
  enabled: boolean;
  preopen_enabled: boolean;
  created_at?: string;
  existed?: boolean;
}

export type ArbDirection = "buy" | "sell" | "preopen_buy" | "preopen_sell";

export interface ArbAlert {
  id: number;
  pair_id: number;
  stock_code: string;
  stock_name: string;
  bench_kind: BenchKind;
  bench_code: string;
  bench_label: string;
  direction: ArbDirection;
  signal_time: string;
  trade_date: string;
  stock_pct?: number | null;
  bench_pct?: number | null;
  beta?: number | null;
  corr?: number | null;
  spread_sigma?: number | null;
  reason: string;
  detected_at: string;
  is_read?: number;
}

export interface ArbPairSnapshot {
  pair_id: number;
  stock_code: string;
  stock_name: string;
  bench_kind: BenchKind;
  bench_code: string;
  bench_label: string;
  enabled: boolean;
  preopen_enabled: boolean;
  status: "warmup" | "ok" | "decoupled" | "flat" | "preopen" | "error" | "off";
  signal?: ArbDirection | null;
  reason: string;
  samples?: number;
  corr?: number | null;
  beta?: number | null;
  spread?: number | null;
  spread_sigma?: number | null;
  drift_z?: number | null;
  bench_mom_z?: number | null;
  stock_pct?: number | null;
  bench_pct?: number | null;
  kospi_pct?: number | null;
  bench_source?: string | null;
  bench_stale?: boolean;
  error?: string | null;
  pre_close_approx?: boolean;
  /** 当日对齐分钟曲线 [HH:MM, 个股%, 基准%],卡片右侧迷你分时图用 */
  curve?: Array<[string, number, number]> | null;
}

export interface ArbRuntime {
  enabled: boolean | null;
  phase: string;
  trading_day: boolean | null;
  last_tick: string | null;
  last_error: string | null;
  kospi_pct: number | null;
  interval_seconds: number;
  pairs: ArbPairSnapshot[];
}

export interface ArbStatus {
  settings: { enabled: boolean; updated_at?: string };
  runtime: ArbRuntime;
  alerts: ArbAlert[];
}
