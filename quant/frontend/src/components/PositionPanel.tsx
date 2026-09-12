import type { Position } from "../types";

interface Props {
  positions: Position[];
  onSelectCode: (code: string) => void;
}

export default function PositionPanel({ positions, onSelectCode }: Props) {
  if (positions.length === 0) {
    return (
      <div className="position-panel">
        <h3>持仓</h3>
        <div className="empty">暂无持仓</div>
      </div>
    );
  }

  return (
    <div className="position-panel">
      <h3>持仓</h3>
      <div className="position-list">
        {positions.map((pos) => (
          <div
            key={pos.code}
            className="position-item"
            onClick={() => onSelectCode(pos.code)}
          >
            <div className="pos-header">
              <span className="pos-name">{pos.name}</span>
              <span className="pos-code">{pos.code}</span>
            </div>
            <div className="pos-details">
              <div className="pos-detail">
                <span className="label">数量</span>
                <span>{pos.quantity}</span>
              </div>
              <div className="pos-detail">
                <span className="label">可卖</span>
                <span>{pos.available_quantity ?? pos.quantity}</span>
              </div>
              <div className="pos-detail">
                <span className="label">成本</span>
                <span>{pos.avg_cost.toFixed(3)}</span>
              </div>
              <div className="pos-detail">
                <span className="label">现价</span>
                <span>{pos.current_price.toFixed(3)}</span>
              </div>
              <div className="pos-detail">
                <span className="label">市值</span>
                <span>{pos.market_value.toFixed(2)}</span>
              </div>
              <div className="pos-detail">
                <span className="label">盈亏</span>
                <span
                  style={{
                    color:
                      pos.profit > 0 ? "#ef5350" : pos.profit < 0 ? "#26a69a" : "#d1d4dc",
                  }}
                >
                  {pos.profit > 0 ? "+" : ""}
                  {pos.profit.toFixed(2)}({pos.profit_pct > 0 ? "+" : ""}
                  {pos.profit_pct}%)
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
