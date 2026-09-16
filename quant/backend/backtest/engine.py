import backtrader as bt
import pandas as pd
from datetime import datetime
from typing import Callable, Dict, Optional
import logging

from backend.backtest.strategies import get_backtest_strategy, get_backtest_strategy_min_bars
from backend.time_utils import to_chart_seconds, format_beijing_time
from backend.trading.fees import COMMISSION_RATE_DEFAULT, calc_a_share_fee_total

logger = logging.getLogger(__name__)


def _to_chart_timestamp(dt: datetime) -> int:
    return int(to_chart_seconds(pd.Timestamp(dt)))


class AShareCommInfo(bt.CommInfoBase):
    """A股交易费用:佣金(双边,最低 5 元)+ 印花税(仅卖出)+ 过户费(双边)。

    与 backend/trading/account.py 共享费用口径(见 backend/trading/fees.py)。
    percabs=True:commission 作为绝对小数费率(0.0001=万一),不做百分比 /100 换算。
    """

    params = (
        ("commission", COMMISSION_RATE_DEFAULT),
        ("percabs", True),
        ("stocklike", True),
        ("commtype", bt.CommInfoBase.COMM_PERC),
    )

    def _getcommission(self, size, price, pseudoexec=False):
        amount = abs(size * price)
        return calc_a_share_fee_total(
            amount, is_sell=(size < 0), commission_rate=self.p.commission
        )


def _sharpe_analyzer_kwargs(period: str) -> dict:
    """根据 K 线周期返回 SharpeRatio analyzer 的 timeframe/compression/factor。

    年化 factor = 每年约 252 交易日 × 每日 240 分钟 / 周期分钟。
    """
    period = str(period or "daily")
    minute_map = {"1": 1, "5": 5, "15": 15, "30": 30, "60": 60, "120": 120}
    if period in minute_map:
        comp = minute_map[period]
        return {
            "timeframe": bt.TimeFrame.Minutes,
            "compression": comp,
            "factor": 252 * 240 // comp,
            "annualize": True,
        }
    if period == "weekly":
        return {"timeframe": bt.TimeFrame.Weeks, "compression": 1, "factor": 52, "annualize": True}
    if period == "monthly":
        return {"timeframe": bt.TimeFrame.Months, "compression": 1, "factor": 12, "annualize": True}
    return {"timeframe": bt.TimeFrame.Days, "compression": 1, "factor": 252, "annualize": True}


class PortfolioValueAnalyzer(bt.Analyzer):
    def start(self):
        self.records = []

    def next(self):
        current_dt = bt.num2date(self.strategy.data.datetime[0])
        self.records.append(
            {
                "timestamp": _to_chart_timestamp(current_dt),
                "date": format_beijing_time(current_dt, "%Y-%m-%d %H:%M:%S"),
                "value": round(float(self.strategy.broker.getvalue()), 2),
            }
        )

    def get_analysis(self):
        return self.records


def _calculate_drawdown_detail(equity_curve: list[dict]) -> Optional[dict]:
    if not equity_curve:
        return None

    peak_point = equity_curve[0]
    max_drawdown = 0.0
    max_peak = peak_point
    max_trough = equity_curve[0]

    for point in equity_curve:
        if float(point.get("value", 0) or 0) >= float(peak_point.get("value", 0) or 0):
            peak_point = point
        peak_value = float(peak_point.get("value", 0) or 0)
        current_value = float(point.get("value", 0) or 0)
        if peak_value <= 0:
            continue
        drawdown = (peak_value - current_value) / peak_value * 100
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            max_peak = peak_point
            max_trough = point

    return {
        "drawdown_pct": round(max_drawdown, 2),
        "peak_date": max_peak.get("date"),
        "peak_timestamp": max_peak.get("timestamp"),
        "peak_value": round(float(max_peak.get("value", 0) or 0), 2),
        "trough_date": max_trough.get("date"),
        "trough_timestamp": max_trough.get("timestamp"),
        "trough_value": round(float(max_trough.get("value", 0) or 0), 2),
    }


def _extract_trade_extreme(trade_records: list[dict], mode: str) -> Optional[dict]:
    closed_trades = [
        record
        for record in trade_records
        if record.get("direction") == "sell"
        and record.get("pnl_pct") is not None
        and not record.get("is_finalized")  # best/worst 只反映真实已平仓交易
    ]
    if not closed_trades:
        return None

    if mode == "best":
        target = max(closed_trades, key=lambda item: float(item.get("pnl_pct", 0) or 0))
    else:
        target = min(closed_trades, key=lambda item: float(item.get("pnl_pct", 0) or 0))

    return {
        "date": target.get("date"),
        "timestamp": target.get("timestamp"),
        "signal_time": target.get("signal_time"),
        "signal_timestamp": target.get("signal_timestamp"),
        "price": target.get("price"),
        "size": target.get("size"),
        "value": target.get("value"),
        "commission": target.get("commission"),
        "avg_cost": target.get("avg_cost"),
        "pnl": target.get("pnl"),
        "pnl_pct": target.get("pnl_pct"),
        "reason": target.get("reason"),
    }


def _summarize_closed_trade_records(trade_records: list[dict]) -> dict:
    closed_trades = [
        record
        for record in trade_records
        if record.get("direction") == "sell"
        and record.get("pnl") is not None
        and not record.get("is_finalized")  # 排除期末未平仓的估算记录,胜率只反映真实已平仓
    ]
    won_records = [record for record in closed_trades if float(record.get("pnl", 0) or 0) > 0]
    lost_records = [record for record in closed_trades if float(record.get("pnl", 0) or 0) < 0]
    round_trip_trades = len(closed_trades)
    won_trade_pnl = sum(float(record.get("pnl", 0) or 0) for record in won_records)
    lost_trade_pnl = sum(float(record.get("pnl", 0) or 0) for record in lost_records)
    won = len(won_records)
    lost = len(lost_records)
    win_rate = won / round_trip_trades * 100 if round_trip_trades > 0 else 0
    realized_total_profit = won_trade_pnl + lost_trade_pnl
    return {
        "round_trip_trades": round_trip_trades,
        "won_trades": won,
        "lost_trades": lost,
        "won_trade_pnl": round(won_trade_pnl, 2),
        "lost_trade_pnl": round(lost_trade_pnl, 2),
        "realized_total_profit": round(realized_total_profit, 2),
        "win_rate": round(win_rate, 2),
    }

class BacktraderStrategyAdapter(bt.Strategy):
    params = (
        ("strategy_name", "MA_BULL_PULLBACK_BOLL"),
        ("signal_map", {}),
        ("record_trade_records", True),
    )

    def __init__(self):
        self.order = None
        self.trade_records = []
        self.position_size = 0
        self.avg_cost = 0.0
        self.pending_order_reason = None
        self.pending_signal_price = None
        self.pending_signal_timestamp = None
        self.pending_signal_time = None
        self.pending_signal_quality = None
        self.last_buy_date = None

    def _build_trade_record(self, order, direction: str, reason: Optional[str] = None, quality: Optional[dict] = None):
        executed_at = bt.num2date(order.executed.dt)
        size = abs(int(order.executed.size))
        # price = 实际成交价(订单撮合价,即下一根开盘);signal_price = 信号触发价(当根收盘,诊断展示用)
        price = float(order.executed.price)
        signal_price = float(self.pending_signal_price) if self.pending_signal_price is not None else price
        gross_value = round(price * size, 2)
        commission = round(float(order.executed.comm), 2)
        record_time = self.pending_signal_time or executed_at.strftime("%Y-%m-%d %H:%M:%S")
        record_timestamp = self.pending_signal_timestamp or _to_chart_timestamp(executed_at)

        record = {
            "direction": direction,
            "price": round(price, 5),
            "signal_price": round(signal_price, 5),
            "size": size,
            "value": gross_value,
            "commission": commission,
            "date": record_time,
            "timestamp": record_timestamp,
            "signal_time": self.pending_signal_time,
            "signal_timestamp": self.pending_signal_timestamp,
            "avg_cost": None,
            "pnl": None,
            "pnl_pct": None,
            "reason": reason or "",
            "quality": quality,
        }

        if size <= 0:
            return record

        if direction == "buy":
            total_cost_before = self.avg_cost * self.position_size
            total_cost_after = total_cost_before + gross_value + commission
            self.position_size += size
            self.avg_cost = total_cost_after / self.position_size if self.position_size > 0 else 0.0
            record["avg_cost"] = round(self.avg_cost, 5)
            return record

        cost_basis = self.avg_cost * size
        net_amount = gross_value - commission
        pnl = net_amount - cost_basis
        pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else None

        record["avg_cost"] = round(self.avg_cost, 5) if self.avg_cost > 0 else None
        record["pnl"] = round(pnl, 2)
        record["pnl_pct"] = round(pnl_pct, 2) if pnl_pct is not None else None

        self.position_size = max(self.position_size - size, 0)
        if self.position_size == 0:
            self.avg_cost = 0.0

        return {
            **record,
        }

    def _is_untradable_bar(self, direction: str) -> bool:
        """判断当根 K 线是否因涨跌停/一字板无法按 direction 成交。

        direction="buy" → 检查涨停封板(买不进);"sell" → 检查跌停封板(卖不出)。
        一字板(high==low)双向都无法成交。涨跌停按普通股 ±10% 近似(ST 股 ±5% 未单独处理)。
        """
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        close = float(self.data.close[0])
        if high == low:  # 一字板,全天单一价格,无成交可能
            return True
        try:
            pre_close = float(self.data.close[-1])
        except (IndexError, ValueError):
            pre_close = close
        if pre_close <= 0:
            return False
        change_pct = (close - pre_close) / pre_close
        if direction == "buy" and change_pct >= 0.099:
            return True
        if direction == "sell" and change_pct <= -0.099:
            return True
        return False

    def next(self):
        if self.order:
            return

        current_dt = bt.num2date(self.data.datetime[0])
        current_ts = _to_chart_timestamp(current_dt)
        signal_info = self.p.signal_map.get(current_ts)
        if not signal_info:
            return

        action = signal_info.get("direction")
        reason = signal_info.get("reason", "")
        signal_price = signal_info.get("price")

        if action == "buy" and not self.position:
            if self._is_untradable_bar("buy"):
                return  # 涨停/一字板封板,买不进,放弃该信号
            cash = float(self.broker.getcash())
            price = float(signal_price) if signal_price is not None else float(self.data.close[0])
            commission_info = self.broker.getcommissioninfo(self.data)
            commission = float(getattr(commission_info.p, "commission", 0.0) or 0.0)
            # 实际成交在下一根开盘,用信号价估算 size 时预留 2% 价格缓冲,
            # 防开盘价高于信号价导致 Margin 拒单(满仓在跳空/强涨时本就买不满,属真实情况)
            size = int(cash / (price * 1.02 * (1 + commission)) / 100) * 100
            if size > 0:
                self.pending_order_reason = reason
                self.pending_signal_quality = signal_info.get("quality")
                self.pending_signal_price = price
                self.pending_signal_timestamp = current_ts
                self.pending_signal_time = current_dt.strftime("%Y-%m-%d %H:%M:%S")
                self.order = self.buy(size=size)
        elif action == "sell" and self.position:
            if self.last_buy_date is not None and current_dt.date() == self.last_buy_date:
                return
            if self._is_untradable_bar("sell"):
                return  # 跌停/一字板封板,卖不出,放弃该信号(继续套牢,模拟真实情况)
            self.pending_order_reason = reason
            self.pending_signal_quality = None
            self.pending_signal_price = (
                float(signal_price) if signal_price is not None else float(self.data.close[0])
            )
            self.pending_signal_timestamp = current_ts
            self.pending_signal_time = current_dt.strftime("%Y-%m-%d %H:%M:%S")
            self.order = self.close()

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                trade_record = self._build_trade_record(
                    order, "buy", self.pending_order_reason, quality=self.pending_signal_quality
                )
                if self.p.record_trade_records:
                    self.trade_records.append(trade_record)
                self.last_buy_date = bt.num2date(order.executed.dt).date()
            elif order.issell():
                trade_record = self._build_trade_record(order, "sell", self.pending_order_reason)
                if self.p.record_trade_records:
                    self.trade_records.append(trade_record)
                if self.position_size == 0:
                    self.last_buy_date = None
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected] and order == self.order:
            self.pending_order_reason = None
            self.pending_signal_price = None
            self.pending_signal_timestamp = None
            self.pending_signal_time = None
            self.pending_signal_quality = None
        if order == self.order:
            self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            pass

    def finalize_open_position_trade_record(self, last_price: float, last_dt: Optional[datetime] = None):
        if not self.p.record_trade_records:
            return
        if self.position_size <= 0 or self.avg_cost <= 0 or not self.trade_records:
            return

        if last_price <= 0:
            return

        last_record = self.trade_records[-1]
        if last_record.get("direction") != "buy":
            return

        final_dt = last_dt or bt.num2date(self.data.datetime[0])
        signal_time = final_dt.strftime("%Y-%m-%d %H:%M:%S")
        signal_timestamp = _to_chart_timestamp(final_dt)
        size = int(self.position_size)
        gross_value = round(last_price * size, 2)
        cost_basis = self.avg_cost * size
        pnl = gross_value - cost_basis
        pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else None

        self.trade_records.append(
            {
                "direction": "sell",
                "is_finalized": True,
                "price": round(last_price, 5),
                "signal_price": round(last_price, 5),
                "size": size,
                "value": gross_value,
                "commission": 0.0,
                "date": signal_time,
                "timestamp": signal_timestamp,
                "signal_time": signal_time,
                "signal_timestamp": signal_timestamp,
                "avg_cost": round(self.avg_cost, 5),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
                "reason": f"回测结束，按最后一根K线收盘价 {last_price:.5f} 视为平仓",
            }
        )
        self.position_size = 0
        self.avg_cost = 0.0
        self.last_buy_date = None


def run_backtest(
    df: pd.DataFrame,
    strategy_name: str = "MA_BULL_PULLBACK_BOLL",
    cash: float = 100000.0,
    commission: float = 0.0001,
    progress_callback: Optional[Callable[[int, str, str], None]] = None,
    lightweight: bool = False,
    include_equity_curve: bool = False,
    period: str = "daily",
    benchmark_code: Optional[str] = "510300",
) -> Dict:
    if df is None or df.empty:
        return {"success": False, "message": "无数据"}

    try:
        if progress_callback:
            progress_callback(60, "正在清洗回测数据...", "数据校验")
        cerebro = bt.Cerebro()

        data_df = df.copy()
        time_col = "datetime" if "datetime" in data_df.columns else "date"
        required_price_cols = ["open", "high", "low", "close"]
        missing_price_cols = [col for col in required_price_cols if col not in data_df.columns]
        if missing_price_cols:
            return {"success": False, "message": f"回测数据缺少必要字段: {', '.join(missing_price_cols)}"}
        if "volume" not in data_df.columns:
            data_df["volume"] = data_df["vol"] if "vol" in data_df.columns else 0
        data_df[time_col] = pd.to_datetime(data_df[time_col])
        data_df = data_df.set_index(time_col)
        data_df = data_df[["open", "high", "low", "close", "volume"]]
        for col in ["open", "high", "low", "close", "volume"]:
            data_df[col] = pd.to_numeric(data_df[col], errors="coerce")
        data_df = data_df.dropna()

        if data_df.empty:
            return {"success": False, "message": "数据清洗后为空"}

        min_bars = get_backtest_strategy_min_bars(strategy_name)
        if len(data_df) < min_bars:
            return {
                "success": False,
                "message": f"当前区间K线数量不足，策略 {strategy_name} 至少需要 {min_bars} 根K线，当前仅有 {len(data_df)} 根。请扩大回测区间或切换更小周期。"
            }

        raw_df = df.copy()
        strategy = get_backtest_strategy(strategy_name)
        if progress_callback:
            progress_callback(72, "正在生成策略买卖信号...", "策略信号")
        signal_list = strategy.generate_signals(raw_df)
        signal_map = {}
        for signal in signal_list:
            try:
                signal_ts = _to_chart_timestamp(pd.Timestamp(signal.time).to_pydatetime())
                signal_map[signal_ts] = {
                    "direction": signal.direction,
                    "price": signal.price,
                    "reason": signal.reason,
                    "quality": (signal.extra or {}).get("quality")
                    if isinstance(signal.extra, dict)
                    else None,
                }
            except Exception:
                continue

        data = bt.feeds.PandasData(dataname=data_df)
        cerebro.adddata(data)

        cerebro.addstrategy(
            BacktraderStrategyAdapter,
            strategy_name=strategy_name,
            signal_map=signal_map,
            record_trade_records=True,
        )

        cerebro.broker.setcash(cash)
        cerebro.broker.addcommissioninfo(AShareCommInfo(commission=commission))  # name=None → 作为所有资产默认 comminfo
        # 信号基于当根 K 线收盘价判定,成交延迟到下一根开盘(Backtrader 默认撮合)。
        # 不使用 cheat-on-close:避免用当根收盘价成交造成未来函数,止损的跳空缺口
        # 也会自然反映进实际成交价(order.executed.price)。
        cerebro.broker.set_coc(False)

        cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        if not lightweight:
            cerebro.addanalyzer(
                bt.analyzers.SharpeRatio, _name="sharpe", **_sharpe_analyzer_kwargs(period)
            )
        if include_equity_curve:
            cerebro.addanalyzer(PortfolioValueAnalyzer, _name="equity_curve")

        start_value = cerebro.broker.getvalue()
        if progress_callback:
            progress_callback(84, "正在执行回测撮合...", "回测运行")
        results = cerebro.run()
        end_value = cerebro.broker.getvalue()

        strat = results[0]
        final_close_price = float(data_df["close"].iloc[-1]) if not data_df.empty else 0.0
        final_close_dt = data_df.index[-1].to_pydatetime() if not data_df.empty else None
        first_close_price = float(data_df["close"].iloc[0]) if not data_df.empty else 0.0
        if hasattr(strat, "finalize_open_position_trade_record"):
            strat.finalize_open_position_trade_record(final_close_price, final_close_dt)

        # 总收益率直接按资金变化计算，避免 Returns 分析器口径差异带来偏差。
        total_return = ((end_value - start_value) / start_value * 100) if start_value else 0

        # 区间股票涨跌幅：回测区间内股票自身的涨跌幅（首根K线收盘价 -> 末根K线收盘价），
        # 用于和策略总收益率对比，判断是否跑赢"单纯持有"。
        stock_change_pct = (
            (final_close_price - first_close_price) / first_close_price * 100
            if first_close_price else 0.0
        )

        sharpe = 0
        if not lightweight:
            try:
                sharpe = strat.analyzers.sharpe.get_analysis().get("sharperatio", 0)
                if sharpe is None:
                    sharpe = 0
            except Exception:
                sharpe = 0

        try:
            max_drawdown = strat.analyzers.drawdown.get_analysis().get("max", {}).get("drawdown", 0)
        except Exception:
            max_drawdown = 0

        total_profit = end_value - start_value
        trade_records = strat.trade_records if hasattr(strat, "trade_records") else []
        trade_summary = _summarize_closed_trade_records(trade_records)
        round_trip_trades = int(trade_summary["round_trip_trades"])
        won = int(trade_summary["won_trades"])
        lost = int(trade_summary["lost_trades"])
        won_trade_pnl = float(trade_summary["won_trade_pnl"])
        lost_trade_pnl = float(trade_summary["lost_trade_pnl"])
        realized_total_profit = float(trade_summary["realized_total_profit"])
        win_rate = float(trade_summary["win_rate"])
        won_trade_return = (won_trade_pnl / start_value * 100) if start_value else 0
        lost_trade_return = (lost_trade_pnl / start_value * 100) if start_value else 0
        realized_total_return = (realized_total_profit / start_value * 100) if start_value else 0
        first_buy_record = next((record for record in trade_records if record.get("direction") == "buy"), None)
        first_buy_price = float(first_buy_record.get("price", 0) or 0) if first_buy_record else 0.0
        stock_change_from_first_buy_pct = (
            (final_close_price - first_buy_price) / first_buy_price * 100
            if first_buy_price > 0 else 0.0
        )
        vs_hold_return = total_return - stock_change_from_first_buy_pct
        total_trades = len(trade_records)
        realized_trades = sum(1 for record in trade_records if record.get("pnl") is not None)
        open_position_size = int(getattr(strat, "position_size", 0) or 0)
        has_open_position = open_position_size > 0
        drawdown_detail = None
        equity_curve = None
        if include_equity_curve:
            try:
                equity_curve = strat.analyzers.equity_curve.get_analysis()
                drawdown_detail = _calculate_drawdown_detail(equity_curve)
            except Exception:
                drawdown_detail = None

        # 基准对比曲线(默认沪深300 ETF 510300 前复权,与个股K线同口径,归一化到策略起点 start_value)
        benchmark_curve = None
        if not lightweight and include_equity_curve and benchmark_code:
            try:
                from backend.market import akshare_data
                if str(benchmark_code).startswith(("51", "56", "58", "15", "16")):
                    bench_raw = akshare_data.get_etf_hist_daily(str(benchmark_code))
                else:
                    bench_raw = akshare_data.get_stock_hist_daily(str(benchmark_code))
                bench = bench_raw.copy() if bench_raw is not None and not bench_raw.empty else None
                if bench is not None and "close" in bench.columns:
                    time_c = "datetime" if "datetime" in bench.columns else "date"
                    bench[time_c] = pd.to_datetime(bench[time_c], errors="coerce", utc=True).dt.tz_localize(None)
                    start_ts = pd.Timestamp(data_df.index.min())
                    end_ts = pd.Timestamp(data_df.index.max())
                    mask = (bench[time_c] >= start_ts) & (bench[time_c] <= end_ts)
                    bench = bench.loc[mask].sort_values(time_c)
                    if not bench.empty:
                        first_close = float(bench["close"].iloc[0])
                        if first_close > 0:
                            benchmark_curve = [
                                {
                                    "timestamp": _to_chart_timestamp(pd.Timestamp(row[time_c]).to_pydatetime()),
                                    "value": round(start_value * float(row["close"]) / first_close, 2),
                                }
                                for _, row in bench.iterrows()
                            ]
            except Exception as e:
                logger.warning(f"基准曲线获取失败 {benchmark_code}: {e}")
                benchmark_curve = None
        if progress_callback:
            progress_callback(94, "正在汇总回测结果...", "结果统计")

        return {
            "success": True,
            "start_value": round(start_value, 2),
            "end_value": round(end_value, 2),
            "total_return": round(total_return, 2),
            "total_profit": round(total_profit, 2),
            "stock_change_pct": round(stock_change_pct, 2),
            "final_close_price": round(final_close_price, 5),
            "stock_change_from_first_buy_pct": round(stock_change_from_first_buy_pct, 2),
            "vs_hold_return": round(vs_hold_return, 2),
            "realized_total_return": round(realized_total_return, 2),
            "realized_total_profit": round(realized_total_profit, 2),
            "sharpe_ratio": round(float(sharpe), 2),
            "max_drawdown": round(float(max_drawdown), 2),
            "total_trades": total_trades,
            "closed_trade_count": realized_trades,
            "round_trip_trades": round_trip_trades,
            "won_trades": won,
            "lost_trades": lost,
            "won_trade_pnl": round(won_trade_pnl, 2),
            "lost_trade_pnl": round(lost_trade_pnl, 2),
            "won_trade_return": round(won_trade_return, 2),
            "lost_trade_return": round(lost_trade_return, 2),
            "has_open_position": has_open_position,
            "open_position_size": open_position_size,
            "win_rate": round(win_rate, 2),
            "trade_records": [] if lightweight else trade_records,
            "drawdown_detail": drawdown_detail,
            "equity_curve": (
                [{"timestamp": p.get("timestamp"), "value": p.get("value")} for p in equity_curve]
                if equity_curve else None
            ),
            "benchmark_curve": benchmark_curve,
            "best_trade": _extract_trade_extreme(trade_records, "best") if trade_records else None,
            "worst_trade": _extract_trade_extreme(trade_records, "worst") if trade_records else None,
        }
    except Exception as e:
        logger.error(f"回测执行失败: {e}")
        return {"success": False, "message": str(e)}
