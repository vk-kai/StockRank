export interface TradeRecordItem {
  direction: string;
  price: number;
  size: number;
  value: number;
  commission: number;
  date: string;
  timestamp?: number;
  signal_time?: string | null;
  signal_timestamp?: number | null;
  avg_cost?: number | null;
  pnl?: number | null;
  pnl_pct?: number | null;
  reason?: string;
}

export interface BacktestTradeExtreme {
  date?: string;
  timestamp?: number;
  signal_time?: string | null;
  signal_timestamp?: number | null;
  price?: number;
  size?: number;
  value?: number;
  commission?: number;
  avg_cost?: number | null;
  pnl?: number | null;
  pnl_pct?: number | null;
  reason?: string;
}

export interface BacktestDrawdownDetail {
  drawdown_pct: number;
  peak_date?: string;
  peak_timestamp?: number;
  peak_value?: number;
  trough_date?: string;
  trough_timestamp?: number;
  trough_value?: number;
}

export interface BatchExtremeDetail {
  code: string;
  name: string;
  period: string;
  strategy_name: string;
  bar_count: number;
  range_start: string;
  range_end: string;
  total_return: number;
  stock_change_pct?: number;
  vs_hold_return?: number;
  max_drawdown: number;
  round_trip_trades: number;
  won_trades: number;
  lost_trades: number;
  win_rate: number;
  trade_records: TradeRecordItem[];
  drawdown_detail?: BacktestDrawdownDetail | null;
  best_trade?: BacktestTradeExtreme | null;
  worst_trade?: BacktestTradeExtreme | null;
}

export interface BatchBucketItem {
  code: string;
  name: string;
  total_profit: number;
  total_return: number;
  stock_change_pct?: number;
  vs_hold_return?: number;
  max_drawdown: number;
  round_trip_trades: number;
  won_trades: number;
  lost_trades: number;
  bucket?: "profit" | "loss";
}

export interface FullBacktestSummary {
  strategy_name: string;
  period: string;
  range_start: string;
  range_end: string;
  target_count: number;
  success_count: number;
  failed_count: number;
  backtest_failed_count?: number;
  backtest_success_target_count?: number;
  traded_target_count?: number;
  total_round_trip_trades?: number;
  profitable_count: number;
  loss_count: number;
  win_rate: number;
  cumulative_return: number;
  average_return: number;
  max_drawdown: number;
  max_gain: number;
  profitable_average_return?: number;
  loss_average_return?: number;
  profitable_cumulative_return?: number;
  loss_cumulative_return?: number;
  profitable_items?: BatchBucketItem[];
  loss_items?: BatchBucketItem[];
  max_drawdown_item?: {
    code: string;
    name: string;
    total_return?: number;
    max_drawdown?: number;
  } | null;
  max_gain_item?: {
    code: string;
    name: string;
    total_return?: number;
    max_drawdown?: number;
  } | null;
}

export interface FullBacktestHistoryItem {
  id: number;
  strategy_name: string;
  period: string;
  start_date: string;
  end_date: string;
  target_count: number;
  success_count: number;
  failed_count: number;
  profitable_count: number;
  loss_count: number;
  win_rate: number;
  cumulative_return: number;
  average_return: number;
  max_drawdown: number;
  max_gain: number;
  created_at: string;
  payload?: {
    summary?: FullBacktestSummary;
    top_successes?: Array<{
      code: string;
      name: string;
      total_return: number;
      max_drawdown: number;
    }>;
    top_losses?: Array<{
      code: string;
      name: string;
      total_return: number;
      max_drawdown: number;
    }>;
    max_drawdown_item?: FullBacktestSummary["max_drawdown_item"];
    max_gain_item?: FullBacktestSummary["max_gain_item"];
    profitable_items?: BatchBucketItem[];
    loss_items?: BatchBucketItem[];
    max_drawdown_detail?: BatchExtremeDetail | null;
    max_gain_detail?: BatchExtremeDetail | null;
    failed_items?: Array<{
      code: string;
      name: string;
      message: string;
    }>;
  } | null;
}

export interface BacktestResult {
  success: boolean;
  mode?: "single" | "batch";
  start_value?: number;
  end_value?: number;
  total_return?: number;
  total_profit?: number;
  stock_change_pct?: number;
  stock_change_from_first_buy_pct?: number;
  final_close_price?: number;
  vs_hold_return?: number;
  sharpe_ratio?: number;
  max_drawdown?: number;
  total_trades?: number;
  closed_trade_count?: number;
  round_trip_trades?: number;
  won_trades?: number;
  lost_trades?: number;
  win_rate?: number;
  bar_count?: number;
  period?: string;
  strategy_name?: string;
  range_start?: string;
  range_end?: string;
  batch_run_id?: number;
  batch_summary?: FullBacktestSummary;
  drawdown_detail?: BacktestDrawdownDetail | null;
  equity_curve?: { timestamp: number; value: number }[] | null;
  benchmark_curve?: { timestamp: number; value: number }[] | null;
  best_trade?: BacktestTradeExtreme | null;
  worst_trade?: BacktestTradeExtreme | null;
  trade_records?: TradeRecordItem[];
  message?: string;
}

export interface BacktestRuntimeStatus {
  job_id: string;
  running: boolean;
  mode?: "single" | "full";
  progress_pct: number;
  current_step: string;
  message: string;
  total_targets?: number;
  completed_targets?: number;
  success_targets?: number;
  failed_targets?: number;
  current_target_index?: number;
  current_target_code?: string;
  current_target_name?: string;
  owner_username?: string;
  result?: BacktestResult | null;
  error?: string;
  updated_at?: string;
  /** 本次回测实际执行位置：pi=树莓派节点 / local=本机 / mixed=全量扫描时部分节点部分本机 */
  node_used?: "" | "pi" | "local" | "mixed";
}
