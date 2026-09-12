export interface Position {
  code: string;
  name: string;
  quantity: number;
  available_quantity?: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  profit: number;
  profit_pct: number;
}

export interface TradeRecord {
  id: string;
  code: string;
  name: string;
  direction: string;
  price: number;
  quantity: number;
  amount: number;
  fee: number;
  time: string;
}

export interface AccountInfo {
  balance: number;
  frozen: number;
  available_balance: number;
  total_market_value: number;
  total_assets: number;
  total_profit: number;
  total_profit_pct: number;
  total_fee: number;
  positions: Record<string, Position>;
  recent_trades: TradeRecord[];
}
