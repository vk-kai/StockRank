export interface HistoryDownloadPeriodOption {
  value: string;
  label: string;
  store: string;
  realtime: string;
}

export interface RuntimeInfo {
  cpu_count: number;
  cpu_workers_scan: number;
  cpu_workers_backtest: number;
  io_workers_screening: number;
  io_workers_market: number;
  io_workers_download: number;
  cpu_worker_limit_env: number;
  io_worker_limit_env: number;
}

export interface HistoryDownloadStatus {
  running: boolean;
  periods: string[];
  period_options: HistoryDownloadPeriodOption[];
  stage?: string;
  target_mode?: string;
  requested_code_count?: number;
  raw_total_count?: number;
  raw_stock_count?: number;
  raw_etf_count?: number;
  raw_index_count?: number;
  a_share_fetched_count?: number;
  removed_st_count?: number;
  removed_market_cap_count?: number;
  removed_delisted_count?: number;
  eligible_stock_count?: number;
  removed_ma_count?: number;
  final_stock_count?: number;
  final_etf_count?: number;
  final_index_count?: number;
  qualified_count?: number;
  current_period?: string;
  current_code?: string;
  current_name?: string;
  current_index?: number;
  total_count?: number;
  ready_count?: number;
  progress_pct?: number;
  current_message?: string;
  selection_index?: number;
  selection_total_count?: number;
  last_started_at?: string;
  last_finished_at?: string;
  error?: string;
  time_span?: string;
  estimated_remaining_seconds?: number;
  current_download_date?: string;
  trigger_source?: string;
  kline_counts?: Record<string, number>;
  kline_period_days?: Record<string, number>;
  kline_downloaded_count?: number;
  scan_eligible_count?: number;
  kline_latest_date?: number | string;
  runtime_info?: RuntimeInfo;
  auto_download_enabled?: boolean;
  auto_download_hour?: number;
  auto_download_check_interval_seconds?: number;
  auto_download_last_checked_at?: string;
  auto_download_next_check_at?: string;
  auto_download_next_check_seconds?: number;
  auto_download_today?: string;
  auto_download_today_started?: boolean;
  auto_download_today_done?: boolean;
  auto_download_status?: string;
}

export interface HistoryDownloadTimeSpanOption {
  value: string;
  label: string;
  days: number;
}

export const HISTORY_DOWNLOAD_TIME_SPANS: HistoryDownloadTimeSpanOption[] = [
  { value: "1m", label: "1个月", days: 30 },
  { value: "3m", label: "3个月", days: 90 },
  { value: "6m", label: "6个月", days: 180 },
  { value: "1y", label: "1年", days: 365 },
  { value: "2y", label: "2年", days: 730 },
  { value: "3y", label: "3年", days: 1095 },
];
