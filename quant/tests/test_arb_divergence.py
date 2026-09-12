# -*- coding: utf-8 -*-
"""背离算法(divergence.align_series / evaluate)纯函数单测。

运行:cd TrendZen && .venv/Scripts/python.exe -X utf8 -m unittest tests.test_arb_divergence -v
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.arb import divergence  # noqa: E402


def minute_times(count: int, start_hour=9, start_minute=31):
    """生成 count 个连续 HH:MM(跨小时自然进位,只用于测试)。"""
    total = start_hour * 60 + start_minute
    return [f"{(total + i) // 60:02d}:{(total + i) % 60:02d}" for i in range(count)]


def build_stock_bench(count, stock_fn, bench_fn):
    times = minute_times(count)
    return divergence.align_series(
        [{"time": t, "pct": stock_fn(i)} for i, t in enumerate(times)],
        [{"time": t, "pct": bench_fn(i)} for i, t in enumerate(times)],
    )


def wave_increment(i, amp=0.1, period=2):
    """确定性交替波(避免随机数):period=2 时 +amp/-amp 交替,15分钟动量近 0。"""
    return amp if (i // period) % 2 == 0 else -amp


def cumsum(increments, start=0.0):
    """增量 → 累计序列(首元素为 start)。"""
    out = [start]
    for inc in increments:
        out.append(out[-1] + inc)
    return out


class TestAlignSeries(unittest.TestCase):
    def test_bench_earlier_open_forward_fill(self):
        """KOSPI 早盘(08:00 开)对齐 A 股(09:31 起): 基准前向填充到个股首点。"""
        bench = [
            {"time": "08:00", "pct": 0.5},
            {"time": "09:31", "pct": 0.8},
            {"time": "09:32", "pct": 0.9},
        ]
        stock = [
            {"time": "09:31", "pct": 0.2},
            {"time": "09:32", "pct": 0.3},
        ]
        merged = divergence.align_series(stock, bench)
        self.assertEqual([m[0] for m in merged], ["09:31", "09:32"])
        self.assertEqual(merged[0][2], 0.8)
        self.assertEqual(merged[1][2], 0.9)

    def test_bench_gap_forward_fill(self):
        """基准缺某个分钟(或 pct=None)时沿用上一有效值。"""
        bench = [
            {"time": "09:31", "pct": 0.5},
            {"time": "09:32", "pct": None},
            {"time": "09:33", "pct": 0.7},
        ]
        stock = [
            {"time": "09:31", "pct": 0.1},
            {"time": "09:32", "pct": 0.15},
            {"time": "09:33", "pct": 0.2},
        ]
        merged = divergence.align_series(stock, bench)
        self.assertEqual(merged[1][2], 0.5)
        self.assertEqual(merged[2][2], 0.7)

    def test_empty_bench(self):
        self.assertEqual(divergence.align_series([{"time": "09:31", "pct": 1.0}], []), [])


class TestEvaluate(unittest.TestCase):
    KW = dict(
        corr_window=30,
        corr_min=0.5,
        beta_window=90,
        beta_min=0.2,
        beta_max=5.0,
        sigma_window=60,
        spread_k=2.0,
        drift_minutes=5,
        bench_mom_window=15,
        bench_mom_z=1.0,
        min_samples=25,
    )

    def test_warmup_below_min_samples(self):
        merged = build_stock_bench(10, lambda i: 0.1 * i, lambda i: 0.2 * i)
        result = divergence.evaluate(merged, **self.KW)
        self.assertEqual(result["status"], "warmup")
        self.assertIsNone(result["signal"])

    def test_perfect_tracking_no_signal(self):
        """完全跟踪 S=2B,且基准无净动量 → 不给信号。"""
        count = 120

        def bench(i):
            return sum(wave_increment(k) for k in range(i))

        merged = build_stock_bench(count, lambda i: 2.0 * bench(i), bench)
        result = divergence.evaluate(merged, **self.KW)
        self.assertIsNone(result["signal"])
        self.assertIn(result["status"], ("ok", "flat"))

    def test_buy_when_bench_rises_stock_flat(self):
        """基准尾段拉升、个股横盘 → 滞涨买点。"""
        count = 120
        ramp = 0.12  # 基准尾15分钟每分钟涨幅%

        def bench(i):
            base = sum(wave_increment(k) for k in range(i))
            if i >= count - 15:
                base += ramp * (i - (count - 16))
            return base

        def stock(i):
            j = min(i, count - 11)  # 最后 10 分钟横盘
            return sum(wave_increment(k) for k in range(j))

        merged = build_stock_bench(count, stock, bench)
        result = divergence.evaluate(merged, **self.KW)
        self.assertEqual(result["status"], "ok")
        self.assertIsNotNone(result.get("corr"))
        self.assertGreaterEqual(result["corr"], 0.5)
        self.assertEqual(result["signal"], "buy")
        self.assertIn("买点", result["reason"])

    def test_sell_when_bench_falls_stock_flat(self):
        """基准尾段下杀、个股横盘 → 抗跌卖点。"""
        count = 120
        ramp = -0.12

        def bench(i):
            base = sum(wave_increment(k) for k in range(i))
            if i >= count - 15:
                base += ramp * (i - (count - 16))
            return base

        def stock(i):
            j = min(i, count - 11)
            return sum(wave_increment(k) for k in range(j))

        merged = build_stock_bench(count, stock, bench)
        result = divergence.evaluate(merged, **self.KW)
        self.assertEqual(result["signal"], "sell")
        self.assertIn("卖点", result["reason"])

    def test_sudden_bench_crash_after_sync_not_decoupled(self):
        """此前完全同步,基准尾段突然连续下杀而个股横盘 → 必须给卖点,不许判脱钩。

        回归场景:基准单边下杀+个股零响应(带真实盘中必然有的微小噪声),
        短窗(生产默认15分钟)ρ 被事件自身毒化 → 旧口径会报 decoupled 吞掉信号,
        且下杀持续多久就吞多久;长窗口径(β 同尺度)看到"近期一直联动",
        闸门保持放行,由漂移/动量门给出卖点。
        """
        count = 120
        wave = [wave_increment(k) for k in range(count - 1)]
        # 下杀段 18 分钟: 覆盖"短窗15+错位2"使任何短窗口径看不到前段耦合行情
        # (背离刚开始、最该提示的阶段);两端各带独立噪声模拟真实盘口
        bench_incs = [
            wave[i] if i < 102 else (-0.12 + (0.02 if i % 3 == 0 else -0.01))
            for i in range(count - 1)
        ]
        stock_incs = [
            wave[i] if i < 102 else (0.008 if i % 2 else -0.008)  # 冻结段微小噪声
            for i in range(count - 1)
        ]
        merged = list(zip(minute_times(count), cumsum(stock_incs), cumsum(bench_incs)))

        # 记录旧行为:生产默认短窗(15分钟)全是下杀段,个股只剩与基准
        # 不相关的噪声 → ρ 崩到门槛之下,旧口径 decoupled 吞信号
        s = [p[1] for p in merged]
        b = [p[2] for p in merged]
        rS = [s[i + 1] - s[i] for i in range(len(s) - 1)]
        rB = [b[i + 1] - b[i] for i in range(len(b) - 1)]
        r_short, _ = divergence._lagged_pearson(rS, rB, 15, 2)
        self.assertIsNotNone(r_short)
        self.assertLess(r_short, 0.5)  # 旧口径会吞信号

        result = divergence.evaluate(merged, **self.KW)
        self.assertEqual(result["status"], "ok")  # 不许 decoupled
        self.assertGreaterEqual(result["corr"], 0.5)
        self.assertEqual(result["signal"], "sell")
        self.assertIn("卖点", result["reason"])

    def test_tiny_bench_move_no_signal(self):
        """波动极小时 z 值容易过阈,但基准 15 分钟实际只动 0.018%(<0.25% 门槛) → 不给信号。"""
        count = 120
        ramp = 0.0012  # 等比缩小 buy 用例:z 值不变(scale 不变量),真实涨幅跌破门槛

        def bench(i):
            base = sum(wave_increment(k, amp=0.001) for k in range(i))
            if i >= count - 15:
                base += ramp * (i - (count - 16))
            return base

        def stock(i):
            j = min(i, count - 11)
            return sum(wave_increment(k, amp=0.001) for k in range(j))

        merged = build_stock_bench(count, stock, bench)
        result = divergence.evaluate(merged, **self.KW)
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["signal"])
        self.assertIn("幅度不够", result["reason"])

    def test_beta_clamped_high(self):
        """S=8B 时 β 夹取到上限 5。"""
        count = 60

        def bench(i):
            return sum(wave_increment(k) for k in range(i))

        merged = build_stock_bench(count, lambda i: 8.0 * bench(i), bench)
        result = divergence.evaluate(merged, **self.KW)
        self.assertAlmostEqual(result["beta"], 5.0, places=6)

    def test_beta_clamped_low(self):
        """S=0.05B 时 β 夹取到下限 0.2。"""
        count = 60

        def bench(i):
            return sum(wave_increment(k) for k in range(i))

        merged = build_stock_bench(count, lambda i: 0.05 * bench(i), bench)
        result = divergence.evaluate(merged, **self.KW)
        self.assertAlmostEqual(result["beta"], 0.2, places=6)

    def test_flat_bench_no_crash(self):
        """基准完全走平(增量零方差)→ flat,不抛异常不给信号。"""
        count = 40
        merged = build_stock_bench(count, lambda i: wave_increment(i) * i, lambda i: 0.0)
        result = divergence.evaluate(merged, **self.KW)
        self.assertEqual(result["status"], "flat")
        self.assertIsNone(result["signal"])

    def test_decoupled_low_corr(self):
        """个股与基准增量不相关(ρ 低)→ decoupled 不提示。"""
        count = 120

        def bench(i):
            return sum(wave_increment(k, period=2) for k in range(i))

        def stock(i):
            # 周期 7 的波,与基准周期 2 的波增量相关性低
            return sum(wave_increment(k, amp=0.15, period=7) for k in range(i))

        merged = build_stock_bench(count, stock, bench)
        result = divergence.evaluate(merged, **self.KW)
        self.assertIn(result["status"], ("decoupled", "flat"))
        self.assertIsNone(result["signal"])

    def test_amplitude_scaled_shape_still_coupled(self):
        """个股涨幅始终是基准3倍: 涨跌幅大小不参与脱钩判定,折线形状一致 ρ≈1。"""
        count = 120
        bench_incs = [0.1, 0.1, -0.1, -0.1] * 30  # 真·4分钟周期方块波
        merged = list(zip(
            minute_times(count), cumsum([3.0 * inc for inc in bench_incs]), cumsum(bench_incs)
        ))
        result = divergence.evaluate(merged, **self.KW)
        # 价差恒定(σ≈0)给 flat;浮点残差下走 ok 也合法,重点是不判脱钩、不给信号
        self.assertIn(result["status"], ("ok", "flat"))
        self.assertGreaterEqual(result["corr"], 0.99)
        self.assertIsNone(result["signal"])

    def test_lagged_jittery_tracking_not_decoupled(self):
        """个股慢一拍+涨幅3倍+分钟抖动: 肉眼看折线吻合。
        旧口径(平滑1/不容错位)ρ≈0.01 误判脱钩;新口径平滑+错位搜索应判吻合。"""
        count = 120
        bench_incs = [0.1, 0.1, -0.1, -0.1] * 30  # 真·4分钟周期方块波
        # 个股增量 = 3×基准(慢1分钟) + 独立抖动
        stock_incs = [3.0 * bench_incs[(i - 1) % 4] + (0.06 if i % 2 else -0.06)
                      for i in range(count - 1)]
        merged = list(zip(minute_times(count), cumsum(stock_incs), cumsum(bench_incs)))

        old_style = divergence.evaluate(merged, corr_smooth_window=1, corr_max_lag=0, **self.KW)
        self.assertEqual(old_style["status"], "decoupled")  # 记录旧行为:确实会误杀

        result = divergence.evaluate(merged, **self.KW)
        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["corr"], 0.9)
        self.assertEqual(result.get("corr_lag"), 1)  # 自动找到慢一拍
        self.assertIsNone(result["signal"])


def wave_inc(i, amp=0.03):
    """测试用共同波形(周期4分钟: ±amp 各两分钟),个股/基准同相→价差干净。"""
    return amp if (i // 2) % 2 == 0 else -amp


class TestAdaptiveGates(unittest.TestCase):
    """参数自适应口径: β 稳健回归 / MAD σ / 价差漂移与"自身今天的历史分布"比。"""

    KW = dict(
        corr_window=30,
        corr_min=0.5,
        beta_window=90,
        beta_min=0.2,
        beta_max=5.0,
        sigma_window=60,
        spread_k=2.0,
        drift_minutes=5,
        bench_mom_window=15,
        bench_mom_z=1.0,
        min_samples=25,
    )

    @staticmethod
    def _series(count, bench_ramp, wave_amp=0.08, extra_amp=0.07):
        """个股=共同波形+早盘6轮额外拉升(extra runs);尾段基准拉升而个股冻结。

        extra runs 每12分钟一轮(5分钟×extra_amp,全部放在早盘):让
        "5分钟价差漂移≈5×extra_amp"在该对自身历史里反复出现(常见);
        尾段基准 ramp 造成的新漂移与之比较。runs 放远端还避免污染 β 回归窗口。
        """
        bench_incs = [
            wave_inc(i, wave_amp) + (bench_ramp if i >= 105 else 0.0) for i in range(count - 1)
        ]
        stock_incs = [
            wave_inc(i, wave_amp) + (extra_amp if (i % 12 < 5 and i < 65) else 0.0)
            if i < 105 else 0.0
            for i in range(count - 1)
        ]
        return list(zip(minute_times(count), cumsum(stock_incs), cumsum(bench_incs)))

    def test_common_drift_not_signaled(self):
        """漂移幅度在该对今天的历史里反复出现(常见)→ 即使 σ 倍数口径过阈也不提示。

        自身历史 q95=5×0.07=0.35,当前漂移 0.27(常见)→ 不提示;
        旧 σ 倍数口径 z_s≈-2.2 会触发买点(每个冷却期都重复误报)。
        基准动量条件满足(z_B≈2.0),压制确实来自漂移门,不是动量门。
        """
        merged = self._series(120, bench_ramp=0.07)
        result = divergence.evaluate(merged, **self.KW)
        self.assertEqual(result["status"], "ok")
        self.assertLessEqual(result["drift_z"], -2.0)  # σ 倍数口径确实过阈(旧行为会误报)
        self.assertGreaterEqual(result["bench_mom_z"], 1.0)  # 动量门满足:压制确实来自漂移门
        self.assertIsNone(result["signal"])
        self.assertIn("基本同步", result["reason"])  # 走的是"无信号"分支,不是幅度不够/脱钩

    def test_unusual_drift_fires_with_tail_note(self):
        """漂移明显超过自身历史(少见)→ 提示,且 reason 注明"排前5%"。

        当前漂移 0.50 ≥ 自身历史 q95=0.35 → 提示。
        """
        merged = self._series(120, bench_ramp=0.12, wave_amp=0.10)
        result = divergence.evaluate(merged, **self.KW)
        self.assertEqual(result["signal"], "buy")
        self.assertIn("买点", result["reason"])
        self.assertIn("排前5%", result["reason"])

    def test_fallback_z_gate_when_history_short(self):
        """开盘初期自身历史样本不足(< drift_tail_min_samples)→ 退回 σ 倍数口径(旧行为)。"""
        count = 45

        def bench(i):
            base = sum(wave_increment(k) for k in range(i))
            if i >= count - 15:
                base += 0.12 * (i - (count - 16))
            return base

        def stock(i):
            j = min(i, count - 11)
            return sum(wave_increment(k) for k in range(j))

        merged = build_stock_bench(count, stock, bench)
        result = divergence.evaluate(merged, **self.KW)
        self.assertEqual(result["signal"], "buy")
        self.assertNotIn("排前", result["reason"])  # 走的是退回口径,没有尾部注记

    def test_theil_sen_beta_robust_to_outlier(self):
        """个股单分钟跳价(大K线)不拖偏 β——OLS 会把它拉到 ≈1.3,Theil-Sen 保持 ≈1。"""
        count = 120
        bench_incs = [0.1, 0.1, -0.1, -0.1] * 30
        stock_incs = [b for b in bench_incs]
        stock_incs[100] += 3.0  # 单根大K线(个股独有跳价)
        merged = list(zip(minute_times(count), cumsum(stock_incs), cumsum(bench_incs)))
        result = divergence.evaluate(merged, **self.KW)
        self.assertIsNotNone(result["beta"])
        self.assertLessEqual(abs(result["beta"] - 1.0), 0.1)

    def test_robust_sigma_unit(self):
        """MAD σ 不被少数跳变撑大;超过半数样本相同(网格报价)时退回标准差。"""
        wiggle = [0.01 if i % 2 else -0.01 for i in range(70)] + [1.0] * 3
        # 3 根大棒不参与定标: σ = 1.4826×MAD = 1.4826×0.02(钉住标度常数)
        self.assertAlmostEqual(divergence._robust_sigma(wiggle), 1.4826 * 0.02, places=9)
        gridded = [0.0] * 40 + [0.3] * 10  # 多数样本相同→MAD=0,退回标准差(钉住数值)
        self.assertAlmostEqual(divergence._robust_sigma(gridded), 0.12, places=9)

    def test_robust_sigma_stable_across_window_parity(self):
        """σ 不随窗口长度奇偶跳档(中位数统一取下中位)。

        旧口径的最近邻秩分位数在 q=0.5 受 round-half-to-even 影响:两值集中的
        序列每加一个样本,σ 在 MAD(≈0.0297)与 std 兜底(≈0.01)间跳 3 倍;
        窗口逐分钟增长的上午,z 值阈值会跟着跳。取下中位后奇偶长度同口径。
        """
        base = [-0.01 if i % 2 == 0 else 0.01 for i in range(64)]
        sigmas = [divergence._robust_sigma(base[:m]) for m in range(56, 65)]
        # 旧口径这里会 3 倍跳档(MAD↔std 兜底);新口径只剩 std 随样本数的自然微变
        self.assertLess(max(sigmas) / min(sigmas), 1.01)
        # 恰好一半为 0 的边界: 59/60 两种长度也必须走同一口径
        tie59 = [0.0] * 30 + [0.06] * 29
        tie60 = [0.0] * 30 + [0.06] * 30
        ratio = divergence._robust_sigma(tie59) / divergence._robust_sigma(tie60)
        self.assertGreater(ratio, 0.9)
        self.assertLess(ratio, 1.1)


if __name__ == "__main__":
    unittest.main()
