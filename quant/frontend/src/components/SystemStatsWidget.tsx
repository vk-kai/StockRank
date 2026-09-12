import { useCallback, useEffect, useState } from "react";
import { fetchSystemStats, fetchNodeStatus, type SystemStats, type NodeLoad, type NodeStatus } from "../api/system";

const POLL_INTERVAL_MS = 3000;
const NODE_POLL_INTERVAL_MS = 12000;

function formatG(bytes: number | null | undefined): string {
  if (bytes == null) return "--";
  return `${(bytes / 1024 ** 3).toFixed(1)}G`;
}

function formatGpuMb(mb: number | null | undefined): string {
  if (mb == null) return "--";
  return `${(mb / 1024).toFixed(1)}G`;
}

function loadColor(pct: number | null | undefined): string {
  if (pct == null) return "var(--text-muted)";
  if (pct >= 85) return "var(--accent-red)";
  if (pct >= 60) return "#f0a020";
  return "var(--accent-green)";
}

export default function SystemStatsWidget() {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [nodeStatus, setNodeStatus] = useState<NodeStatus | null>(null);

  const refresh = useCallback(async () => {
    const res = await fetchSystemStats();
    if (res.success && res.data) {
      setStats(res.data);
    }
  }, []);

  const refreshNode = useCallback(async () => {
    const res = await fetchNodeStatus();
    if (res.success && res.data) {
      setNodeStatus(res.data);
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    refreshNode();
    const timer = window.setInterval(refreshNode, NODE_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refreshNode]);

  const cpuPct = stats?.cpu_percent ?? null;
  const memPct = stats?.memory_percent ?? null;
  const cores = stats?.cpu_count ?? "--";
  const memUsed = formatG(stats?.memory_used_bytes);
  const memTotal = formatG(stats?.memory_total_bytes);
  const gpuDevices = stats?.gpu ?? [];
  const firstGpu = gpuDevices[0];
  const gpuMemPct =
    firstGpu && firstGpu.memory_total_mb > 0
      ? (firstGpu.memory_used_mb / firstGpu.memory_total_mb) * 100
      : null;

  const tooltip = firstGpu
    ? `${gpuDevices
        .map(
          (g) =>
            `${g.name} · 利用率 ${g.utilization_pct != null ? `${g.utilization_pct}%` : "--"} · 显存 ${formatGpuMb(
              g.memory_used_mb,
            )}/${formatGpuMb(g.memory_total_mb)}`,
        )
        .join("\n")}`
    : "未检测到 NVIDIA GPU（仅支持通过 nvidia-smi 读取的 N 卡）";

  // Pi 节点信息
  const piEnabled = nodeStatus?.enabled ?? false;
  const piOnline = piEnabled && nodeStatus?.state === "online";
  const piLoad = (nodeStatus?.load ?? {}) as Partial<NodeLoad>;
  const piCpuPct = piLoad.cpu_percent ?? null;
  const piMemPct = piLoad.memory_percent ?? null;
  const piCores = piLoad.cpu_count ?? "--";
  const piMemUsed = formatG(piLoad.memory_used_bytes);
  const piMemTotal = formatG(piLoad.memory_total_bytes);
  const piLatency = nodeStatus?.latency_ms != null ? `${Math.round(nodeStatus.latency_ms)}ms` : "--";
  const piActiveTasks = nodeStatus?.active_tasks ?? 0;
  const piWorkers = nodeStatus?.workers ?? 0;

  return (
    <div className="sys-stats-bar" title={tooltip}>
      <span className="sys-seg">
        <span className="sys-k">CPU</span>
        <span className="sys-v" style={{ color: loadColor(cpuPct) }}>
          {cpuPct != null ? `${cpuPct}%` : "--"}
        </span>
        <span className="sys-sub">{cores}核</span>
      </span>

      <span className="sys-sep" />

      <span className="sys-seg">
        <span className="sys-k">内存</span>
        <span className="sys-v" style={{ color: loadColor(memPct) }}>
          {memPct != null ? `${memPct}%` : "--"}
        </span>
        <span className="sys-sub">{`${memUsed}/${memTotal}`}</span>
      </span>

      <span className="sys-sep" />

      <span className="sys-seg">
        <span className="sys-k">GPU</span>
        {firstGpu ? (
          <>
            <span className="sys-v" style={{ color: loadColor(firstGpu.utilization_pct) }}>
              {firstGpu.utilization_pct != null ? `${firstGpu.utilization_pct.toFixed(0)}%` : "--"}
            </span>
            <span className="sys-sub" style={{ color: loadColor(gpuMemPct) }}>
              {`${formatGpuMb(firstGpu.memory_used_mb)}/${formatGpuMb(firstGpu.memory_total_mb)}`}
            </span>
          </>
        ) : (
          <span className="sys-v sys-muted">未使用GPU</span>
        )}
      </span>

      {piEnabled && (
        <>
          <span className="sys-sep" />
          <span className="sys-seg sys-pi-seg" title={
            piOnline
              ? `Pi 节点 · ${piWorkers} workers · 活跃 ${piActiveTasks} · ${piCores}核 · 内存 ${piMemUsed}/${piMemTotal} · 延迟 ${piLatency}${
                  nodeStatus?.version_match === false ? " · ⚠ 版本不一致" : ""
                }`
              : piEnabled
                ? `Pi 节点离线 · ${nodeStatus?.last_error || "连接失败"}${
                    nodeStatus?.last_seen ? ` · 最后在线 ${nodeStatus.last_seen}` : ""
                  }`
                : ""
          }>
            <span className="sys-k sys-pi-label">
              <span className={`sys-pi-dot ${piOnline ? "online" : "offline"}`}>●</span>
              Pi
            </span>
            {piOnline ? (
              <>
                <span className="sys-v" style={{ color: loadColor(piCpuPct) }}>
                  {piCpuPct != null ? `${piCpuPct}%` : "--"}
                </span>
                <span className="sys-sub">{piCores}核</span>
                <span className="sys-v" style={{ color: loadColor(piMemPct), marginLeft: 4 }}>
                  {piMemPct != null ? `${piMemPct}%` : "--"}
                </span>
                <span className="sys-sub">{piLatency}</span>
                <span className="sys-v" style={{ marginLeft: 4, color: piActiveTasks > 0 ? "var(--accent-green)" : "var(--text-muted)" }}>
                  {piActiveTasks}/{piWorkers}
                </span>
              </>
            ) : (
              <span className="sys-v sys-muted">{nodeStatus?.state === "cooldown" ? "保底中" : "离线"}</span>
            )}
          </span>
        </>
      )}
    </div>
  );
}
