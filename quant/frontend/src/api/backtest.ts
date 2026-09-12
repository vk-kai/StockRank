import type { BacktestRuntimeStatus, BatchExtremeDetail, FullBacktestHistoryItem, StrategyInfo } from "../types";
import { requestJson } from "./base";

export async function startBacktest(params: {
  code: string;
  name?: string;
  strategy: string;
  start_date: string;
  end_date: string;
  cash: number;
  period: string;
  mode?: "single" | "full";
}): Promise<{ success: boolean; message?: string; data?: BacktestRuntimeStatus }> {
  const qs = new URLSearchParams({
    code: params.code,
    strategy: params.strategy,
    start_date: params.start_date,
    end_date: params.end_date,
    cash: String(params.cash),
    period: params.period,
    mode: params.mode || "single",
  });
  if (params.name) qs.set("name", params.name);
  return requestJson(`/api/backtest/start?${qs.toString()}`, { method: "POST" });
}

export async function fetchBacktestStatus(): Promise<{ success: boolean; data: BacktestRuntimeStatus }> {
  return requestJson("/api/backtest/status");
}

export async function fetchStrategies(): Promise<{ success: boolean; data: StrategyInfo[] }> {
  return requestJson("/api/market/strategies");
}

export async function fetchFullBacktestHistory(params?: {
  strategy_name?: string;
  limit?: number;
}): Promise<{ success: boolean; data: FullBacktestHistoryItem[]; message?: string }> {
  const qs = new URLSearchParams();
  if (params?.strategy_name) qs.set("strategy_name", params.strategy_name);
  if (params?.limit !== undefined) qs.set("limit", String(params.limit));
  return requestJson(`/api/backtest/full/history${qs.toString() ? `?${qs.toString()}` : ""}`);
}

export async function fetchFullBacktestHistoryDetail(runId: number): Promise<{
  success: boolean;
  data?: FullBacktestHistoryItem;
  message?: string;
}> {
  return requestJson(`/api/backtest/full/history/${runId}`);
}

export async function deleteFullBacktestHistory(runId: number): Promise<{ success: boolean; message?: string }> {
  return requestJson(`/api/backtest/full/history/${runId}`, { method: "DELETE" });
}

export async function fetchFullBacktestStockDetail(runId: number, code: string): Promise<{
  success: boolean;
  data?: BatchExtremeDetail;
  message?: string;
}> {
  return requestJson(`/api/backtest/full/history/${runId}/stock/${code}`);
}

export interface BacktestSettings {
  strategy: string;
  start_date: string;
  end_date: string;
  cash: number;
  period: string;
  mode: string;
}

export async function fetchBacktestSettings(): Promise<{ success: boolean; data?: BacktestSettings; message?: string }> {
  return requestJson("/api/backtest/settings");
}
