import type { HistoryDownloadStatus } from "../types";
import { requestJson } from "./base";

export async function fetchHistoryDownloadStatus(): Promise<{ success: boolean; data: HistoryDownloadStatus }> {
  return requestJson("/api/market/history-download/status");
}

export async function startHistoryDownload(params: {
  periods: string[];
  force_refresh?: boolean;
  codes?: string[];
  time_span?: string;
}): Promise<{ success: boolean; message?: string; data?: HistoryDownloadStatus }> {
  const qs = new URLSearchParams();
  if (params.periods.length > 0) {
    qs.set("periods", params.periods.join(","));
  }
  if (params.force_refresh) {
    qs.set("force_refresh", "true");
  }
  if (params.codes && params.codes.length > 0) {
    qs.set("codes", params.codes.join(","));
  }
  if (params.time_span) {
    qs.set("time_span", params.time_span);
  }
  return requestJson(`/api/market/history-download/start?${qs.toString()}`, { method: "POST" });
}
