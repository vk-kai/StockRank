import type { AccountInfo } from "../types";

interface Props {
  account: AccountInfo | null;
  onReset: () => void;
}

export default function AccountPanel({ account, onReset }: Props) {
  if (!account) {
    return (
      <div className="account-panel">
        <h3>账户信息</h3>
        <div className="loading">加载中...</div>
      </div>
    );
  }

  return (
    <div className="account-panel">
      <h3>账户信息</h3>
      <div className="account-grid">
        <div className="account-item">
          <span className="label">总资产</span>
          <span className="value">{account.total_assets.toFixed(2)}</span>
        </div>
        <div className="account-item">
          <span className="label">可用余额</span>
          <span className="value">{account.available_balance.toFixed(2)}</span>
        </div>
        <div className="account-item">
          <span className="label">持仓市值</span>
          <span className="value">{account.total_market_value.toFixed(2)}</span>
        </div>
        <div className="account-item">
          <span className="label">总盈亏</span>
          <span
            className="value"
            style={{
              color:
                account.total_profit > 0
                  ? "#ef5350"
                  : account.total_profit < 0
                  ? "#26a69a"
                  : "#d1d4dc",
            }}
          >
            {account.total_profit > 0 ? "+" : ""}
            {account.total_profit.toFixed(2)}
            ({account.total_profit_pct > 0 ? "+" : ""}
            {account.total_profit_pct}%)
          </span>
        </div>
        <div className="account-item">
          <span className="label">累计手续费</span>
          <span className="value">{account.total_fee.toFixed(2)}</span>
        </div>
      </div>
      <button className="reset-btn" onClick={onReset}>
        重置账户
      </button>
    </div>
  );
}
