import type { TradeRecord } from "../types";

interface Props {
  trades: TradeRecord[];
  maxRows?: number;
  title?: string;
}

export default function TradeHistoryPanel({
  trades,
  maxRows,
  title = "历史订单",
}: Props) {
  const rows = maxRows ? trades.slice(-maxRows).reverse() : [...trades].reverse();

  return (
    <div className="panel-card trade-history-panel">
      <div className="panel-card-header">
        <h3>{title}</h3>
        <span className="panel-card-meta">{trades.length} 笔</span>
      </div>

      {rows.length === 0 ? (
        <div className="empty">暂无交易记录</div>
      ) : (
        <div className="trade-table-wrap">
          <table className="trade-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>代码</th>
                <th>方向</th>
                <th>价格</th>
                <th>数量</th>
                <th>金额</th>
                <th>手续费</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id}>
                  <td>{t.time || "--"}</td>
                  <td>{t.code}</td>
                  <td
                    style={{
                      color: t.direction === "buy" ? "#ef5350" : "#26a69a",
                    }}
                  >
                    {t.direction === "buy" ? "买入" : "卖出"}
                  </td>
                  <td>{t.price?.toFixed(3)}</td>
                  <td>{t.quantity}</td>
                  <td>{t.amount?.toFixed(2)}</td>
                  <td>{t.fee?.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
