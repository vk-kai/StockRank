import json
import os
from datetime import datetime

from backend.time_utils import now_beijing
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
from backend.config import DEFAULT_BALANCE, BASE_DIR
from backend.trading.fees import calc_a_share_fee_total

ACCOUNT_FILE = os.path.join(BASE_DIR, "account.json")


@dataclass
class Position:
    code: str
    name: str
    quantity: int
    avg_cost: float
    current_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.current_price * self.quantity

    @property
    def profit(self) -> float:
        return (self.current_price - self.avg_cost) * self.quantity

    @property
    def profit_pct(self) -> float:
        if self.avg_cost == 0:
            return 0
        return round((self.current_price - self.avg_cost) / self.avg_cost * 100, 2)


@dataclass
class TradeRecord:
    id: str
    code: str
    name: str
    direction: str
    price: float
    quantity: int
    amount: float
    fee: float
    time: str


@dataclass
class VirtualAccount:
    balance: float = DEFAULT_BALANCE
    frozen: float = 0.0
    positions: Dict[str, Position] = field(default_factory=dict)
    trades: List[TradeRecord] = field(default_factory=list)
    total_fee: float = 0.0

    @property
    def available_balance(self) -> float:
        return self.balance - self.frozen

    @property
    def total_market_value(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    @property
    def total_assets(self) -> float:
        return self.balance + self.total_market_value

    @property
    def total_profit(self) -> float:
        return self.total_assets - DEFAULT_BALANCE

    @property
    def total_profit_pct(self) -> float:
        return round(self.total_profit / DEFAULT_BALANCE * 100, 2)

    def to_dict(self) -> dict:
        return {
            "balance": round(self.balance, 2),
            "frozen": round(self.frozen, 2),
            "available_balance": round(self.available_balance, 2),
            "total_market_value": round(self.total_market_value, 2),
            "total_assets": round(self.total_assets, 2),
            "total_profit": round(self.total_profit, 2),
            "total_profit_pct": self.total_profit_pct,
            "total_fee": round(self.total_fee, 2),
            "positions": {k: {
                "code": v.code,
                "name": v.name,
                "quantity": v.quantity,
                "available_quantity": get_t1_sellable_quantity(self, v.code),
                "avg_cost": round(v.avg_cost, 3),
                "current_price": round(v.current_price, 3),
                "market_value": round(v.market_value, 2),
                "profit": round(v.profit, 2),
                "profit_pct": v.profit_pct,
            } for k, v in self.positions.items()},
            "recent_trades": [asdict(t) for t in self.trades[-20:]],
        }


def _calc_fee(amount: float, is_sell: bool = False) -> float:
    # 与回测引擎共享费用口径(见 backend/trading/fees.py):佣金最低5元 + 印花税0.05%(卖出) + 过户费0.001%
    return calc_a_share_fee_total(amount, is_sell=is_sell)


def _trade_date_text(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
    except Exception:
        return str(value or "")[:10]


def get_t1_sellable_quantity(account: VirtualAccount, code: str, today: Optional[str] = None) -> int:
    if code not in account.positions:
        return 0

    trade_day = today or now_beijing().strftime("%Y-%m-%d")
    today_buy_quantity = sum(
        int(trade.quantity)
        for trade in account.trades
        if trade.code == code and trade.direction == "buy" and _trade_date_text(trade.time) == trade_day
    )
    return max(int(account.positions[code].quantity) - today_buy_quantity, 0)


def load_account() -> VirtualAccount:
    if os.path.exists(ACCOUNT_FILE):
        try:
            with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            account = VirtualAccount(
                balance=data.get("balance", DEFAULT_BALANCE),
                frozen=data.get("frozen", 0.0),
                total_fee=data.get("total_fee", 0.0),
            )
            for code, pos_data in data.get("positions", {}).items():
                account.positions[code] = Position(
                    code=pos_data["code"],
                    name=pos_data["name"],
                    quantity=pos_data["quantity"],
                    avg_cost=pos_data["avg_cost"],
                    current_price=pos_data.get("current_price", 0),
                )
            for t in data.get("trades", []):
                account.trades.append(TradeRecord(**t))
            return account
        except Exception:
            pass
    return VirtualAccount()


def save_account(account: VirtualAccount):
    data = {
        "balance": account.balance,
        "frozen": account.frozen,
        "total_fee": account.total_fee,
        "positions": {k: {
            "code": v.code,
            "name": v.name,
            "quantity": v.quantity,
            "avg_cost": v.avg_cost,
            "current_price": v.current_price,
        } for k, v in account.positions.items()},
        "trades": [asdict(t) for t in account.trades],
    }
    with open(ACCOUNT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def execute_buy(account: VirtualAccount, code: str, name: str, price: float, quantity: int) -> dict:
    if quantity <= 0 or price <= 0:
        return {"success": False, "message": "价格或数量无效"}

    amount = price * quantity
    fee = _calc_fee(amount, is_sell=False)
    total_cost = amount + fee

    if total_cost > account.available_balance:
        return {"success": False, "message": f"余额不足，需要 {round(total_cost, 2)}，可用 {round(account.available_balance, 2)}"}

    account.balance -= total_cost
    account.total_fee += fee

    if code in account.positions:
        pos = account.positions[code]
        total_quantity = pos.quantity + quantity
        pos.avg_cost = (pos.avg_cost * pos.quantity + amount) / total_quantity
        pos.quantity = total_quantity
    else:
        account.positions[code] = Position(
            code=code, name=name, quantity=quantity, avg_cost=price, current_price=price
        )

    trade = TradeRecord(
        id=f"T{now_beijing().strftime('%Y%m%d%H%M%S%f')}",
        code=code, name=name, direction="buy",
        price=price, quantity=quantity, amount=amount, fee=fee,
        time=now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
    )
    account.trades.append(trade)
    save_account(account)

    return {"success": True, "message": "买入成功", "trade": asdict(trade)}


def execute_sell(account: VirtualAccount, code: str, name: str, price: float, quantity: int) -> dict:
    if quantity <= 0 or price <= 0:
        return {"success": False, "message": "价格或数量无效"}

    if code not in account.positions:
        return {"success": False, "message": "无持仓"}

    pos = account.positions[code]
    sellable_quantity = get_t1_sellable_quantity(account, code)
    if sellable_quantity < quantity:
        return {
            "success": False,
            "message": f"T+1限制：今日买入不可卖出，当前可卖 {sellable_quantity} 股，持仓 {pos.quantity} 股",
        }

    amount = price * quantity
    fee = _calc_fee(amount, is_sell=True)
    net_amount = amount - fee

    account.balance += net_amount
    account.total_fee += fee

    pos.quantity -= quantity
    if pos.quantity == 0:
        del account.positions[code]

    trade = TradeRecord(
        id=f"T{now_beijing().strftime('%Y%m%d%H%M%S%f')}",
        code=code, name=name, direction="sell",
        price=price, quantity=quantity, amount=amount, fee=fee,
        time=now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
    )
    account.trades.append(trade)
    save_account(account)

    return {"success": True, "message": "卖出成功", "trade": asdict(trade)}


def reset_account() -> VirtualAccount:
    account = VirtualAccount()
    save_account(account)
    return account


def update_position_prices(account: VirtualAccount, prices: Dict[str, float]):
    for code, price in prices.items():
        if code in account.positions:
            account.positions[code].current_price = price
    save_account(account)
