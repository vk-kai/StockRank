import json
import os
import tempfile
import unittest

from data import margin_collector


class MarginSeriesBalanceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_cache_file = margin_collector.STOCK_MARGIN_CACHE_FILE
        margin_collector.STOCK_MARGIN_CACHE_FILE = os.path.join(self.tmpdir.name, "stock_margin.json")
        with margin_collector._MEM["lock"]:
            margin_collector._MEM["mtime"] = -1
            margin_collector._MEM["data"] = None

    def tearDown(self):
        margin_collector.STOCK_MARGIN_CACHE_FILE = self.old_cache_file
        with margin_collector._MEM["lock"]:
            margin_collector._MEM["mtime"] = -1
            margin_collector._MEM["data"] = None
        self.tmpdir.cleanup()

    def test_returns_latest_financing_balance_for_modal_header(self):
        cache = {
            "updated_at": "2026-07-02 09:05:00",
            "latest_date": "20260701",
            "stocks": {
                "600941": {
                    "n": "中国移动",
                    "s": [
                        ["20260630", 100000000.0, 3000000.0],
                        ["20260701", 120000000.0, 5000000.0],
                    ],
                }
            },
        }
        with open(margin_collector.STOCK_MARGIN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)

        data = margin_collector.get_stock_margin_series("sh600941")

        self.assertEqual(data["latest_balance"], 120000000.0)
        self.assertEqual(data["latest_balance_date"], "20260701")
        self.assertEqual(data["series"][-1]["b"], 120000000.0)

    def _write_cache(self, stocks):
        cache = {"updated_at": "", "latest_date": "", "stocks": stocks}
        with open(margin_collector.STOCK_MARGIN_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        with margin_collector._MEM["lock"]:
            margin_collector._MEM["mtime"] = -1
            margin_collector._MEM["data"] = None

    def test_to_float_parses_comma_numbers(self):
        self.assertEqual(margin_collector._to_float("1,234,567.89"), 1234567.89)
        self.assertEqual(margin_collector._to_float(1234.5), 1234.5)
        self.assertEqual(margin_collector._to_float("-"), 0.0)

    def test_aggregate_smooths_transient_coverage_drop(self):
        """单日覆盖突变(某交易所接口当天失败) → 用前值平滑,不出现断崖。"""
        stocks = {}
        for i in range(2000):
            code = f"6{i:05d}"
            rows = [[f"202608{d:02d}", 1000000.0, 10000.0] for d in range(1, 6)]
            if i < 1000:  # 只有 6 日当天另一半缺失,次日恢复
                rows.append(["20260806", 1000000.0, 10000.0])
            rows += [[f"202608{d:02d}", 1000000.0, 10000.0] for d in range(7, 9)]
            stocks[code] = {"n": f"股{i}", "s": rows}
        self._write_cache(stocks)

        agg = margin_collector._aggregate_market_margin_total()
        history = agg["history"]

        # 6 日被平滑为前值,前后无断崖
        self.assertEqual(agg["filled_days"], 1)
        self.assertEqual(history[5]["total"], 2000 * 1000000.0)
        self.assertEqual(history[-1]["total"], 2000 * 1000000.0)

    def test_aggregate_persistent_coverage_drop_accepts_new_level(self):
        """覆盖持续下降(接口长期失败/口径变化) → 连续平滑最多3天后采信真实水平,不画假横线。"""
        stocks = {}
        for i in range(2000):
            code = f"6{i:05d}"
            rows = [[f"202608{d:02d}", 1000000.0, 10000.0] for d in range(1, 6)]
            if i < 1000:  # 6 日起只剩一半股票有数据
                rows += [[f"202608{d:02d}", 1000000.0, 10000.0] for d in range(6, 12)]
            stocks[code] = {"n": f"股{i}", "s": rows}
        self._write_cache(stocks)

        agg = margin_collector._aggregate_market_margin_total()
        history = agg["history"]

        # 6/7/8 三天平滑为旧值,9 日起接受新水平
        self.assertEqual(agg["filled_days"], 3)
        self.assertEqual(history[5]["total"], 2000 * 1000000.0)
        self.assertEqual(history[7]["total"], 2000 * 1000000.0)
        self.assertEqual(history[8]["total"], 1000 * 1000000.0)
        self.assertEqual(history[-1]["total"], 1000 * 1000000.0)


if __name__ == "__main__":
    unittest.main()
