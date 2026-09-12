import json
import os
from datetime import datetime

from backend.time_utils import now_beijing
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
from backend.config import DEFAULT_BALANCE, BASE_DIR
from backend.trading.fees import calc_a_share_fee_total

# 模拟账户已入库(统一库 data/stockrank.db 的 virtual_* 表)。
# 旧 account.json 仅作一次性迁移源,导入成功后改名为 account.json.imported。
LEGACY_ACCOUNT_FILE = os.path.join(BASE_DIR, "account.json")
LEGACY_ACCOUNT_IMPORTED = LEGACY_ACCOUNT_FILE + ".imported"

# 已落库的成交单 id 集合(避免 save_account 反复全量重插历史成交)
_persisted_trade_ids: set = set()


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


def _ensure_account_tables(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS virtual_account (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            balance REAL NOT NULL,
            frozen REAL NOT NULL DEFAULT 0,
            total_fee REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS virtual_positions (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            avg_cost REAL NOT NULL,
            current_price REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS virtual_trades (
            id TEXT PRIMARY KEY,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            direction TEXT NOT NULL,
            price REAL NOT NULL,
            quantity INTEGER NOT NULL,
            amount REAL NOT NULL,
            fee REAL NOT NULL,
            time TEXT NOT NULL
        )
        """
    )


def _load_legacy_account_json() -> Optional[dict]:
    """读取旧 account.json(存在且未导入过时)。"""
    if not os.path.exists(LEGACY_ACCOUNT_FILE) or os.path.exists(LEGACY_ACCOUNT_IMPORTED):
        return None
    try:
        with open(LEGACY_ACCOUNT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_account() -> VirtualAccount:
    from backend import db

    with db.get_connection() as conn:
        _ensure_account_tables(conn)
        state = conn.execute("SELECT * FROM virtual_account WHERE id = 1").fetchone()

        # 首次运行:从旧 account.json 一次性导入(统一库无状态且旧文件在)
        if state is None:
            legacy = _load_legacy_account_json()
            if legacy is not None:
                account = VirtualAccount(
                    balance=legacy.get("balance", DEFAULT_BALANCE),
                    frozen=legacy.get("frozen", 0.0),
                    total_fee=legacy.get("total_fee", 0.0),
                )
                for code, pos_data in (legacy.get("positions") or {}).items():
                    account.positions[code] = Position(
                        code=pos_data["code"],
                        name=pos_data["name"],
                        quantity=pos_data["quantity"],
                        avg_cost=pos_data["avg_cost"],
                        current_price=pos_data.get("current_price", 0),
                    )
                for t in legacy.get("trades") or []:
                    try:
                        account.trades.append(TradeRecord(**t))
                    except Exception:
                        continue
                save_account(account)
                try:
                    os.replace(LEGACY_ACCOUNT_FILE, LEGACY_ACCOUNT_IMPORTED)
                except OSError:
                    pass
                return account
            account = VirtualAccount()
            save_account(account)
            return account

        account = VirtualAccount(
            balance=state["balance"],
            frozen=state["frozen"],
            total_fee=state["total_fee"],
        )
        for row in conn.execute("SELECT * FROM virtual_positions").fetchall():
            account.positions[row["code"]] = Position(
                code=row["code"], name=row["name"], quantity=row["quantity"],
                avg_cost=row["avg_cost"], current_price=row["current_price"],
            )
        for row in conn.execute(
            "SELECT * FROM virtual_trades ORDER BY time, id"
        ).fetchall():
            account.trades.append(TradeRecord(
                id=row["id"], code=row["code"], name=row["name"],
                direction=row["direction"], price=row["price"],
                quantity=row["quantity"], amount=row["amount"],
                fee=row["fee"], time=row["time"],
            ))
            _persisted_trade_ids.add(row["id"])
        return account


def save_account(account: VirtualAccount):
    from backend import db

    ts = now_beijing().strftime("%Y-%m-%d %H:%M:%S")
    with db.get_connection() as conn:
        _ensure_account_tables(conn)
        conn.execute(
            """
            INSERT INTO virtual_account (id, balance, frozen, total_fee, updated_at)
            VALUES (1, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                balance = excluded.balance,
                frozen = excluded.frozen,
                total_fee = excluded.total_fee,
                updated_at = excluded.updated_at
            """,
            (account.balance, account.frozen, account.total_fee, ts),
        )
        conn.execute("DELETE FROM virtual_positions")
        for v in account.positions.values():
            conn.execute(
                "INSERT OR REPLACE INTO virtual_positions "
                "(code, name, quantity, avg_cost, current_price, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (v.code, v.name, v.quantity, v.avg_cost, v.current_price, ts),
            )
        for t in account.trades:
            if t.id in _persisted_trade_ids:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO virtual_trades "
                "(id, code, name, direction, price, quantity, amount, fee, time) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (t.id, t.code, t.name, t.direction, t.price, t.quantity, t.amount, t.fee, t.time),
            )
            _persisted_trade_ids.add(t.id)


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
    from backend import db

    with db.get_connection() as conn:
        _ensure_account_tables(conn)
        conn.execute("DELETE FROM virtual_trades")
        conn.execute("DELETE FROM virtual_positions")
        conn.execute("DELETE FROM virtual_account")
    _persisted_trade_ids.clear()
    account = VirtualAccount()
    save_account(account)
    return account


def update_position_prices(account: VirtualAccount, prices: Dict[str, float]):
    for code, price in prices.items():
        if code in account.positions:
            account.positions[code].current_price = price
    save_account(account)
