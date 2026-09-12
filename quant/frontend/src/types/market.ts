 export interface KlineData {
  time: string;
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount?: number;
}

export interface WatchlistSecurityInfo {
  code: string;
  name: string;
  market: number;
  t0: boolean;
  price: number;
  change_pct: number;
  change: number;
  volume: number;
  amount: number;
  tracked_signal_count?: number;
  tracked_return_pct?: number | null;
}

export type ETFInfo = WatchlistSecurityInfo;

export interface RealtimeQuote {
  code: string;
  name: string;
  price: number;
  open: number;
  high: number;
  low: number;
  pre_close: number;
  volume: number;
  amount: number;
  change_pct: number;
  change: number;
  bid1: number;
  ask1: number;
  bid1_vol: number;
  ask1_vol: number;
}

export interface IndexQuote {
  code: string;
  name: string;
  price?: number | null;
  change_pct?: number | null;
  change?: number | null;
  market?: number;
}

export interface SignalInfo {
  direction: string;
  price: number;
  time: string;
  reason: string;
  size?: number;
  amount?: number;
  commission?: number;
  timestamp?: number;
}

export interface KlineResponse {
  success: boolean;
  data?: KlineData[];
  indicators?: {
    ma: Record<string, number[]>;
    macd: { DIF: number[]; DEA: number[]; MACD: number[] };
    boll: { MID: number[]; UPPER: number[]; LOWER: number[] };
  };
  signals?: SignalInfo[];
  has_more?: boolean;
  next_before_ts?: string | null;
  source?: string;
  message?: string;
}

export interface StrategyInfo {
  name: string;
  description: string;
  enabled?: boolean;
  requires_login?: boolean;
  vk_only?: boolean;
  locked?: boolean;
  lock_message?: string;
}

export type BenchKind = "em_index" | "em_board" | "em_global" | "tdx_board";

export interface BenchmarkPoint {
  time: string;
  timestamp: number;
  price: number | null;
  pct: number | null;
}

export interface BenchmarkTrends {
  kind: BenchKind;
  code: string;
  source: string;
  trade_date: string;
  pre_close: number | null;
  pre_close_approx?: boolean;
  fetched_at: string;
  stale: boolean;
  points: BenchmarkPoint[];
}

export interface BenchmarkCandidate {
  kind: BenchKind;
  code: string;
  label: string;
  source?: string;
}

export interface SignalDiagnosisEvaluation {
  direction: string;
  point_key: string;
  point_name: string;
  status: "matched" | "not_matched" | "out_of_range";
  reason: string;
}

export interface SignalDiagnosisResult {
  bar_time: string;
  strategy_name: string;
  source: "backtest" | "scan";
  evaluations: SignalDiagnosisEvaluation[];
}
