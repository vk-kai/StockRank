import type {
  BenchmarkCandidate,
  BenchmarkTrends,
  ETFInfo,
  IndexQuote,
  KlineResponse,
  RealtimeQuote,
  SignalDiagnosisResult,
  StrategyInfo,
  WatchlistSecurityInfo,
} from "../types";
import { requestJson } from "./base";

export async function fetchWatchlist(): Promise<{ success: boolean; data: WatchlistSecurityInfo[] }> {
  return requestJson("/api/market/watchlist");
}

export async function fetchETFList(): Promise<{ success: boolean; data: ETFInfo[] }> {
  return fetchWatchlist();
}

export async function addWatchlistSecurity(
  code: string,
  name?: string,
  market?: number
): Promise<{ success: boolean; message?: string; status?: number; data?: WatchlistSecurityInfo }> {
  const qs = new URLSearchParams({ code });
  if (name) qs.set("name", name);
  if (market !== undefined) qs.set("market", String(market));
  return requestJson(`/api/market/watchlist/add?${qs.toString()}`, { method: "POST" });
}

export async function addETF(
  code: string,
  name?: string,
  market?: number
): Promise<{ success: boolean; message?: string; status?: number; data?: ETFInfo }> {
  return addWatchlistSecurity(code, name, market);
}

export async function removeWatchlistSecurity(
  code: string
): Promise<{ success: boolean; message?: string; status?: number }> {
  return requestJson(`/api/market/watchlist/remove?code=${code}`, { method: "POST" });
}

export async function removeETF(
  code: string
): Promise<{ success: boolean; message?: string; status?: number }> {
  return removeWatchlistSecurity(code);
}

export async function searchSecurity(
  keyword: string,
  limit: number = 20
): Promise<{
  success: boolean;
  data: Array<{
    code: string;
    name: string;
    market?: number;
    price?: number;
    change_pct?: number;
    premium_rate?: number;
  }>;
}> {
  return requestJson(
    `/api/market/security/search?keyword=${encodeURIComponent(keyword)}&limit=${limit}`
  );
}

export async function searchETF(
  keyword: string,
  limit: number = 20
): Promise<{
  success: boolean;
  data: Array<{
    code: string;
    name: string;
    market?: number;
    price?: number;
    change_pct?: number;
    premium_rate?: number;
  }>;
}> {
  return searchSecurity(keyword, limit);
}

export async function fetchSecurityDetail(
  code: string,
  options?: { name?: string; includeMargin?: boolean }
): Promise<{ success: boolean; data?: Record<string, any>; message?: string }> {
  const qs = new URLSearchParams({ code });
  if (options?.name) qs.set("name", options.name);
  if (options?.includeMargin) qs.set("include_margin", "true");
  return requestJson(`/api/market/security/detail?${qs.toString()}`);
}

export async function fetchETFDetail(
  code: string,
  options?: { name?: string; includeMargin?: boolean }
): Promise<{ success: boolean; data?: Record<string, any>; message?: string }> {
  return fetchSecurityDetail(code, options);
}

export async function fetchKline(
  code: string,
  name: string,
  period: string,
  count: number = 300,
  beforeTs?: string
): Promise<KlineResponse> {
  const qs = new URLSearchParams({ code, period, count: String(count) });
  if (name) qs.set("name", name);
  if (beforeTs) qs.set("before_ts", beforeTs);
  return requestJson(`/api/market/kline?${qs.toString()}`);
}

export async function fetchRealtime(
  code: string
): Promise<{ success: boolean; data?: RealtimeQuote; message?: string }> {
  return requestJson(`/api/market/realtime?code=${code}`);
}

export async function fetchMajorIndexQuotes(): Promise<{ success: boolean; data: IndexQuote[] }> {
  return requestJson("/api/market/index/quotes");
}

export async function fetchScanStrategies(): Promise<{ success: boolean; data: StrategyInfo[] }> {
  return requestJson("/api/market/scan-strategies");
}

export async function fetchBenchmarkTrends(
  kind: string,
  code: string,
  label?: string
): Promise<{ success: boolean; data?: BenchmarkTrends; message?: string }> {
  const qs = new URLSearchParams({ kind, code });
  if (label) qs.set("label", label);
  return requestJson(`/api/market/benchmark/trends?${qs.toString()}`);
}

export async function searchBenchmarks(
  keyword: string
): Promise<{ success: boolean; data: BenchmarkCandidate[] }> {
  return requestJson(
    `/api/market/benchmark/search?keyword=${encodeURIComponent(keyword)}`
  );
}

export async function fetchSignalDiagnosis(params: {
  source: "backtest" | "scan";
  code: string;
  name?: string;
  period: string;
  strategy_name: string;
  target_timestamp: number;
  range_start?: string;
  range_end?: string;
}): Promise<{ success: boolean; data?: SignalDiagnosisResult; message?: string }> {
  const qs = new URLSearchParams({
    source: params.source,
    code: params.code,
    period: params.period,
    strategy_name: params.strategy_name,
    target_timestamp: String(params.target_timestamp),
  });
  if (params.name) qs.set("name", params.name);
  if (params.range_start) qs.set("range_start", params.range_start);
  if (params.range_end) qs.set("range_end", params.range_end);
  return requestJson(`/api/market/signal-diagnosis?${qs.toString()}`);
}
