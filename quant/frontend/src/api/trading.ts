import type { AccountInfo, Position, TradeRecord } from "../types";
import { requestJson } from "./base";

export async function fetchAccount(): Promise<{ success: boolean; data: AccountInfo }> {
  return requestJson("/api/trading/account");
}

export async function placeOrder(
  code: string,
  direction: "buy" | "sell",
  price: number,
  quantity: number
): Promise<{ success: boolean; message: string; trade?: any }> {
  return requestJson(
    `/api/trading/order?code=${code}&direction=${direction}&price=${price}&quantity=${quantity}`,
    { method: "POST" }
  );
}

export async function resetAccount(): Promise<{ success: boolean; data: AccountInfo }> {
  return requestJson("/api/trading/reset", { method: "POST" });
}

export async function fetchPositions(): Promise<{ success: boolean; data: Position[] }> {
  return requestJson("/api/trading/positions");
}

export async function fetchTradeHistory(
  limit: number = 50
): Promise<{ success: boolean; data: TradeRecord[] }> {
  return requestJson(`/api/trading/history?limit=${limit}`);
}
