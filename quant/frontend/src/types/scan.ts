export interface ScanSignal {
  id?: number;
  run_id?: number | null;
  code: string;
  name: string;
  direction: string;
  price: number;
  signal_time: string;
  reason: string;
  strategy_name: string;
  period: string;
  detected_at: string;
  run_slot?: string;
  is_read?: boolean;
}

export interface ScanRunIndustryInfo {
  industry: string;
  stock_count: number;
}

export interface ScanRunInfo {
  id: number;
  display_no?: number;
  started_at: string;
  finished_at?: string | null;
  strategy_name: string;
  trigger_type?: string;
  candidate_count: number;
  scanned_count: number;
  signal_count: number;
  status: string;
  message?: string;
  buy_industries?: ScanRunIndustryInfo[];
}

export interface ScanStatus {
  enabled: boolean;
  strategy_name: string;
  interval_minutes: number;
  updated_at: string;
  scan_scope_type?: string;
  scan_scope_codes?: string[];
  scan_focus_codes?: string[];
  scan_period?: string;
  scan_period_label?: string;
  running: boolean;
  last_run_slot?: string;
  current_code?: string;
  current_name?: string;
  current_index?: number;
  total_count?: number;
  progress_pct?: number;
  current_message?: string;
  estimated_remaining_seconds?: number;
  latest_run?: ScanRunInfo | null;
  recent_runs?: ScanRunInfo[];
  recent_signals: ScanSignal[];
  unread_count?: number;
  scan_ready?: boolean;
  scan_ready_message?: string;
  scan_universe_count?: number;
  local_ready_count?: number;
  required_periods?: string[];
  auto_download_enabled?: boolean;
  auto_download_hour?: number;
  kline_force_refresh?: boolean;
  default_strategy?: string;
  strategy_owner_username?: string | null;
  is_trading_day?: boolean;
  next_scan_at?: string | null;
}

export interface ScanScopeCandidate {
  code: string;
  name: string;
  market: number;
}

export interface ScanScopeCandidatePage {
  items: ScanScopeCandidate[];
  total: number;
  page: number;
  page_size: number;
}

export interface TrackedSignalSettlement {
  tracked_id: number;
  signal_id: number;
  direction: string;
  signal_price: number;
  signal_time: string;
  exit_price: number;
  exit_time: string;
  return_pct: number;
  strategy_name: string;
  period: string;
  reason: string;
  tracked_at: string;
}

export interface SettledSignal {
  id: number;
  tracked_signal_id: number;
  signal_id: number;
  code: string;
  name: string;
  direction: string;
  signal_price: number;
  signal_time: string;
  exit_price: number;
  exit_time: string;
  return_pct: number;
  strategy_name: string;
  period: string;
  reason: string;
  tracked_at: string;
  settled_at: string;
  removed_from_watchlist: boolean;
}

export interface TrackedSignal {
  id: number;
  signal_id: number;
  code: string;
  name: string;
  direction: string;
  signal_price: number;
  signal_time: string;
  strategy_name: string;
  period: string;
  reason: string;
  tracked_at: string;
}
