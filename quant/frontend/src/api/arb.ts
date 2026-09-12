import type { ArbPair, ArbStatus } from "../types";
import { requestJson } from "./base";

export async function fetchArbStatus(): Promise<{ success: boolean; data?: ArbStatus; message?: string }> {
  return requestJson("/api/market/arb/status");
}

export async function addArbPair(params: {
  stock_code: string;
  stock_name?: string;
  bench_kind: string;
  bench_code: string;
  bench_label?: string;
  preopen_enabled?: boolean;
}): Promise<{ success: boolean; data?: ArbPair; existed?: boolean; message?: string }> {
  const qs = new URLSearchParams({
    action: "add",
    stock_code: params.stock_code,
    bench_kind: params.bench_kind,
    bench_code: params.bench_code,
  });
  if (params.stock_name) qs.set("stock_name", params.stock_name);
  if (params.bench_label) qs.set("bench_label", params.bench_label);
  if (params.preopen_enabled !== undefined) qs.set("preopen_enabled", String(params.preopen_enabled));
  return requestJson(`/api/market/arb/pairs?${qs.toString()}`, { method: "POST" });
}

export async function removeArbPair(pairId: number): Promise<{ success: boolean; message?: string }> {
  return requestJson(`/api/market/arb/pairs?action=remove&pair_id=${pairId}`, { method: "POST" });
}

export async function toggleArbPair(pairId: number, enabled: boolean): Promise<{ success: boolean; message?: string }> {
  return requestJson(
    `/api/market/arb/pairs?action=toggle&pair_id=${pairId}&enabled=${enabled ? "true" : "false"}`,
    { method: "POST" }
  );
}

export async function updateArbSettings(enabled: boolean): Promise<{ success: boolean; message?: string }> {
  return requestJson(`/api/market/arb/settings?enabled=${enabled ? "true" : "false"}`, { method: "POST" });
}

export async function markArbAlertsRead(ids: string): Promise<{ success: boolean; message?: string }> {
  return requestJson(`/api/market/arb/read?ids=${encodeURIComponent(ids)}`, { method: "POST" });
}
