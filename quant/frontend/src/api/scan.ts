import type { ScanScopeCandidatePage, ScanSignal, ScanStatus, SettledSignal, TrackedSignal, TrackedSignalSettlement } from "../types";
import { requestJson } from "./base";

export async function fetchScanStatus(): Promise<{ success: boolean; data: ScanStatus }> {
  return requestJson("/api/market/scan/status");
}

export async function saveScanSettings(params: {
  enabled?: boolean;
  strategy_name?: string;
  interval_minutes?: number;
  scan_scope_type?: string;
  scan_scope_codes?: string[];
  scan_focus_codes?: string[];
  scan_period?: string;
  auto_download_enabled?: boolean;
  auto_download_hour?: number;
  kline_force_refresh?: boolean;
}): Promise<{ success: boolean; data: ScanStatus }> {
  const qs = new URLSearchParams();
  if (params.enabled !== undefined) qs.set("enabled", String(params.enabled));
  if (params.strategy_name) qs.set("strategy_name", params.strategy_name);
  if (params.interval_minutes !== undefined) qs.set("interval_minutes", String(params.interval_minutes));
  if (params.scan_scope_type) qs.set("scan_scope_type", params.scan_scope_type);
  if (params.scan_period) qs.set("scan_period", params.scan_period);
  if (params.scan_scope_codes && params.scan_scope_codes.length > 0) {
    qs.set("scan_scope_codes", params.scan_scope_codes.join(","));
  } else if (params.scan_scope_type === "selected") {
    qs.set("scan_scope_codes", "");
  }
  if (params.scan_focus_codes) {
    qs.set("scan_focus_codes", params.scan_focus_codes.join(","));
  }
  if (params.auto_download_enabled !== undefined) qs.set("auto_download_enabled", String(params.auto_download_enabled));
  if (params.auto_download_hour !== undefined) qs.set("auto_download_hour", String(params.auto_download_hour));
  if (params.kline_force_refresh !== undefined) qs.set("kline_force_refresh", String(params.kline_force_refresh));
  return requestJson(`/api/market/scan/settings?${qs.toString()}`, { method: "POST" });
}

export async function runScanNow(): Promise<{
  success: boolean;
  data: { alerts: ScanSignal[]; status: ScanStatus };
}> {
  return requestJson("/api/market/scan/run", { method: "POST" });
}

export async function fetchScanCandidates(params: {
  page?: number;
  page_size?: number;
  keyword?: string;
}): Promise<{ success: boolean; data: ScanScopeCandidatePage }> {
  const qs = new URLSearchParams();
  if (params.page !== undefined) qs.set("page", String(params.page));
  if (params.page_size !== undefined) qs.set("page_size", String(params.page_size));
  if (params.keyword) qs.set("keyword", params.keyword);
  return requestJson(`/api/market/scan/candidates?${qs.toString()}`);
}

export async function markScanSignalsRead(ids: number[]): Promise<{ success: boolean; message?: string; status?: number }> {
  return requestJson(`/api/market/scan/read?ids=${ids.join(",")}`, { method: "POST" });
}

export async function deleteScanRun(
  runId: number
): Promise<{ success: boolean; message?: string; status?: number; data?: { run_id: number; signal_count: number; deleted: boolean } }> {
  return requestJson(`/api/market/scan/runs/${runId}`, { method: "DELETE" });
}

export async function pushScanRunToMarketMap(
  runId: number
): Promise<{
  success: boolean;
  message?: string;
  status?: number;
  data?: { run_id: number; pushed_count: number; market_map_url: string };
}> {
  return requestJson(`/api/market/scan/runs/${runId}/push-to-market-map`, { method: "POST" });
}

export async function trackSignal(signalId: number): Promise<{
  success: boolean;
  data?: { tracked_id: number; code: string; name: string; added_to_watchlist: boolean };
  message?: string;
  status?: number;
}> {
  return requestJson(`/api/market/scan/track?signal_id=${signalId}`, { method: "POST" });
}

export async function untrackSignal(
  trackedId: number,
  removeFromWatchlist: boolean = false
): Promise<{
  success: boolean;
  data?: {
    code: string;
    name: string;
    removed_from_watchlist: boolean;
    settlement: TrackedSignalSettlement;
  };
  message?: string;
  status?: number;
}> {
  const qs = new URLSearchParams({ tracked_id: String(trackedId) });
  if (removeFromWatchlist) qs.set("remove_from_watchlist", "true");
  return requestJson(`/api/market/scan/untrack?${qs.toString()}`, { method: "POST" });
}

export async function fetchTrackedSignals(code?: string): Promise<{
  success: boolean;
  data: TrackedSignal[];
}> {
  const qs = code ? `?code=${code}` : "";
  return requestJson(`/api/market/tracked-signals${qs}`);
}

export async function fetchSettledSignals(code?: string): Promise<{
  success: boolean;
  data: SettledSignal[];
}> {
  const qs = code ? `?code=${code}` : "";
  return requestJson(`/api/market/settled-signals${qs}`);
}
