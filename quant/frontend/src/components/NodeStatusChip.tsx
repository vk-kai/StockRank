import { useCallback, useEffect, useState } from "react";
import { fetchNodeStatus, toggleNode, type NodeLoad, type NodeStatus } from "../api/system";

// 节点状态变化慢（健康检测 15s 一轮），12s 轮询足够，几乎无带宽开销
const POLL_INTERVAL_MS = 12000;

function formatG(bytes: number | null | undefined): string {
  if (bytes == null) return "--";
  return `${(bytes / 1024 ** 3).toFixed(1)}G`;
}

export default function NodeStatusChip() {
  const [s, setS] = useState<NodeStatus | null>(null);
  const [toggling, setToggling] = useState(false);

  const refresh = useCallback(async () => {
    const r = await fetchNodeStatus();
    if (r.success && r.data) setS(r.data);
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const handleToggle = useCallback(async () => {
    if (toggling) return;
    const nextEnabled = !s?.enabled;
    setToggling(true);
    try {
      const r = await toggleNode(nextEnabled);
      if (r.success) {
        await refresh();
      }
    } finally {
      setToggling(false);
    }
  }, [s?.enabled, toggling, refresh]);

  const enabled = s?.enabled ?? false;
  const state: NodeStatus["state"] = enabled ? s?.state ?? "offline" : "disabled";
  const load = (s?.load ?? {}) as Partial<NodeLoad>;
  const latency = s?.latency_ms != null ? `${Math.round(s.latency_ms)}ms` : "--";

  const label = !enabled
    ? "Pi节点:关"
    : state === "online"
      ? `Pi节点:开 ${load.cpu_percent != null ? `${load.cpu_percent}%` : "--"}·${
          load.memory_percent != null ? `${load.memory_percent}%` : "--"
        } ${latency}`
      : state === "cooldown"
        ? `Pi节点:开(保底${(s?.cooldown_remaining_seconds ?? 0).toFixed(0)}s)`
        : "Pi节点:开(离线)";

  const dot = !enabled
    ? "○"
    : state === "online"
      ? "●"
      : state === "cooldown"
        ? "◐"
        : "●";

  const title = !enabled
    ? "Pi 节点卸载已关闭，点击开启"
    : state === "online"
      ? `Pi 节点在线 · ${s?.workers ?? "?"} workers · ${load.cpu_count ?? "?"}核 · 内存 ${formatG(
          load.memory_used_bytes,
        )}/${formatG(load.memory_total_bytes)} · 延迟 ${latency}${
          s?.version_match === false ? " · ⚠ backtrader 版本不一致，结果可能漂移" : ""
        } · 点击关闭`
      : `节点不可用，已回落本机执行 · ${s?.last_error || "连接失败"}${
          s?.last_seen ? ` · 最后在线 ${s.last_seen}` : ""
        } · 点击关闭`;

  return (
    <span
      className={`node-status ${state} clickable`}
      title={title}
      onClick={handleToggle}
      style={{ cursor: toggling ? "wait" : "pointer", opacity: toggling ? 0.6 : 1 }}
    >
      <span className="node-dot">{dot}</span>
      {toggling ? "切换中..." : label}
    </span>
  );
}
