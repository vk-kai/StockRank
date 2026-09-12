import HistoryDownloadPanel from "./HistoryDownloadPanel";
import type { HistoryDownloadStatus } from "../types";

interface Props {
  status: HistoryDownloadStatus | null;
  onStart: (params: { periods: string[]; force_refresh?: boolean; codes?: string[]; time_span?: string }) => Promise<void>;
  onClose: () => void;
  autoDownloadEnabled?: boolean;
  autoDownloadHour?: number;
  klineForceRefresh?: boolean;
  onAutoDownloadChange?: (enabled: boolean, hour: number) => void;
  onKlineForceRefreshChange?: (enabled: boolean) => void;
}

export default function DataDownloadModal({
  status,
  onStart,
  onClose,
  autoDownloadEnabled,
  autoDownloadHour,
  klineForceRefresh,
  onAutoDownloadChange,
  onKlineForceRefreshChange,
}: Props) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="scan-settings-modal data-download-modal" onClick={(e) => e.stopPropagation()}>
        <div className="panel-card-header" style={{ marginBottom: 14 }}>
          <h3>数据下载</h3>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="panel-card-meta">
              {status?.running
                ? "筛选并下载中"
                : "支持按规则批量下载，也支持指定代码直接下载"}
            </span>
            <button className="modal-close-btn" onClick={onClose}>
              关闭
            </button>
          </div>
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          <div className="scan-setting-hint">
            <div>规则下载范围：A股 + ETF + 指数，其中A股初始化时会剔除 ST 和总市值低于 100 亿的股票。</div>
            <div>执行顺序：先初始化基础池，再下载日线和30分钟 K 线，最后按日线收盘是否站上 144 均线生成最终规则池。</div>
          </div>

          <HistoryDownloadPanel
            status={status}
            onStart={onStart}
            autoDownloadEnabled={autoDownloadEnabled}
            autoDownloadHour={autoDownloadHour}
            klineForceRefresh={klineForceRefresh}
            onAutoDownloadChange={onAutoDownloadChange}
            onKlineForceRefreshChange={onKlineForceRefreshChange}
          />
        </div>
      </div>
    </div>
  );
}
