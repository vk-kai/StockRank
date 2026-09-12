import { requestJson } from "./base";

export interface SystemGpuDevice {
  name: string;
  memory_total_mb: number;
  memory_used_mb: number;
  utilization_pct: number | null;
}

export interface SystemStats {
  cpu_percent: number | null;
  cpu_count: number;
  memory_total_bytes: number | null;
  memory_used_bytes: number | null;
  memory_percent: number | null;
  gpu: SystemGpuDevice[];
  psutil_available: boolean;
}

export async function fetchSystemStats(): Promise<{
  success: boolean;
  data?: SystemStats;
  message?: string;
}> {
  return requestJson("/api/system/stats");
}

export interface NodeLoad {
  cpu_percent: number | null;
  cpu_count: number;
  memory_percent: number | null;
  memory_total_bytes: number;
  memory_used_bytes: number;
}

export interface NodeStatus {
  enabled: boolean;
  online: boolean;
  state: "online" | "offline" | "cooldown" | "disabled";
  latency_ms: number | null;
  last_seen: string;
  last_error: string;
  url: string;
  workers: number | null;
  active_tasks: number;
  node_backtrader: string;
  version_match: boolean;
  load: NodeLoad | Record<string, never>;
  cooldown_remaining_seconds: number;
}

export async function fetchNodeStatus(): Promise<{
  success: boolean;
  data?: NodeStatus;
  message?: string;
}> {
  return requestJson("/api/system/node-status");
}

export async function toggleNode(enabled: boolean): Promise<{
  success: boolean;
  data?: { enabled: boolean };
  message?: string;
}> {
  return requestJson("/api/system/node-toggle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
}
