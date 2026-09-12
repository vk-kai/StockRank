# -*- coding: utf-8 -*-
"""基准数据层解析单测(EM trends2 / 新浪 KOSPI / pytdx 板块,全部 monkeypatch 无网络)。

运行:cd TrendZen && .venv/Scripts/python.exe -X utf8 -m unittest tests.test_benchmark_parsing -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from backend.market import benchmark_data  # noqa: E402


class _FakeResponse:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text
        self.encoding = None

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _em_trends_payload(pre_close=100.0, with_pre_close=True):
    data = {
        "date": "20260819",
        "trends": [
            "2026-08-19 09:31,100.5,101.0,101.2,100.4,123,456000,101.0",
            "2026-08-19 09:32,101.1,101.5,101.6,101.0,150,500000,101.3",
            "2026-08-19 09:33,101.0,100.8,101.1,100.7,90,300000,100.9",
        ],
    }
    if with_pre_close:
        data["preClose"] = pre_close
    return {"data": data}


class TestEmTrends(unittest.TestCase):
    def setUp(self):
        benchmark_data._trends_cache.clear()
        benchmark_data._trends_retry_blocked_until.clear()

    def test_secid_rules(self):
        self.assertEqual(benchmark_data._em_secid("em_index", "000001"), "1.000001")
        self.assertEqual(benchmark_data._em_secid("em_index", "399001"), "0.399001")
        self.assertEqual(benchmark_data._em_secid("em_board", "BK0917"), "90.BK0917")
        self.assertEqual(benchmark_data._em_secid("em_global", "KS11"), "100.KS11")
        self.assertIsNone(benchmark_data._em_secid("em_board", "0917"))

    def test_parse_with_preclose(self):
        response = _FakeResponse(payload=_em_trends_payload(pre_close=100.0))
        with mock.patch.object(benchmark_data.requests, "get", return_value=response):
            payload = benchmark_data.get_benchmark_trends("em_index", "000001", allow_stale=False)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["source"], "em_trends2")
        self.assertEqual(payload["trade_date"], "2026-08-19")
        self.assertFalse(payload["pre_close_approx"])
        self.assertAlmostEqual(payload["pre_close"], 100.0)
        self.assertEqual(len(payload["points"]), 3)
        first = payload["points"][0]
        self.assertEqual(first["time"], "09:31")
        self.assertAlmostEqual(first["price"], 101.0)
        self.assertAlmostEqual(first["pct"], 1.0, places=4)
        self.assertAlmostEqual(payload["points"][1]["pct"], 1.5, places=4)
        self.assertTrue(all(p["timestamp"] > 0 for p in payload["points"]))

    def test_parse_preclose_missing_falls_back_to_open(self):
        response = _FakeResponse(payload=_em_trends_payload(with_pre_close=False))
        with mock.patch.object(benchmark_data.requests, "get", return_value=response):
            payload = benchmark_data.get_benchmark_trends("em_index", "000001", allow_stale=False)
        self.assertIsNotNone(payload)
        self.assertTrue(payload["pre_close_approx"])
        self.assertAlmostEqual(payload["pre_close"], 100.5)  # 首行开盘价兜底

    def test_stale_served_after_failure(self):
        """拉取失败后退避,未超龄缓存以 stale=True 提供(主源与 pytdx 兜底都断)。"""
        ok_response = _FakeResponse(payload=_em_trends_payload())
        with mock.patch.object(benchmark_data.requests, "get", return_value=ok_response):
            first = benchmark_data.get_benchmark_trends("em_index", "399001", allow_stale=False)
        self.assertIsNotNone(first)
        self.assertFalse(first["stale"])

        from backend.time_utils import now_beijing
        from datetime import timedelta

        key = "em_index:399001"
        fresh_ts = now_beijing() - timedelta(seconds=benchmark_data.ARB_TRENDS_CACHE_TTL + 1)
        with benchmark_data._trends_lock:
            benchmark_data._trends_cache[key] = (first, fresh_ts)

        failing = mock.Mock(side_effect=RuntimeError("上游故障"))
        with mock.patch.object(benchmark_data.requests, "get", failing), \
                mock.patch.object(benchmark_data.pytdx_data, "get_index_kline", side_effect=RuntimeError("tds也挂了")):
            stale = benchmark_data.get_benchmark_trends("em_index", "399001", allow_stale=True)
        self.assertIsNotNone(stale)
        self.assertTrue(stale["stale"])
        self.assertEqual(stale["points"], first["points"])


class TestSinaKospi(unittest.TestCase):
    RAW = (
        'var hq_str_b_KOSPI="韩国KOSPI指数，6471.1700,-398.66,-5.80,2:27 AM,14:27:00,'
        '2026-08-19,14:30:40,6528.7700,6869.8300,6614.3900,6400.8100,0";'
    )

    def test_snapshot_parse(self):
        response = _FakeResponse(text=self.RAW)
        with mock.patch.object(benchmark_data.requests, "get", return_value=response):
            snapshot = benchmark_data.get_kospi_snapshot_sina()
        self.assertIsNotNone(snapshot)
        self.assertAlmostEqual(snapshot["price"], 6471.17)
        self.assertAlmostEqual(snapshot["pct"], -5.80)
        self.assertAlmostEqual(snapshot["pre_close"], 6869.83)
        self.assertEqual(snapshot["trade_date"], "2026-08-19")  # 字段[6]交易日,休市判定用

    def test_snapshot_bad_payload(self):
        response = _FakeResponse(text='var hq_str_b_KOSPI="";')
        with mock.patch.object(benchmark_data.requests, "get", return_value=response):
            self.assertIsNone(benchmark_data.get_kospi_snapshot_sina())

    def test_accumulator_base_overlay_merge(self):
        """曲线 = 东财基线(历史段) + 新浪覆盖层(实时尾),同分钟新浪优先。"""
        from backend.time_utils import now_beijing

        base = {
            "trade_date": now_beijing().strftime("%Y-%m-%d"),
            "pre_close": 6800.0,
            "points": [
                {"time": "08:00", "price": 6810.0, "pct": 0.15},
                {"time": "08:01", "price": 6840.0, "pct": 0.59},
            ],
        }
        accumulator = benchmark_data._KospiAccumulator()
        accumulator.set_em_base(base)
        snap = accumulator.snapshot()
        self.assertIsNotNone(snap)
        self.assertEqual(snap["source"], "em_trends2")  # 只有基线
        self.assertEqual([p["time"] for p in snap["points"]], ["08:00", "08:01"])

        accumulator.upsert_minute("08:02", 6900.0, 1.47, pre_close=6800.0)
        snap = accumulator.snapshot()
        self.assertEqual(snap["source"], "sina_em")  # 基线+实时尾
        self.assertEqual([p["time"] for p in snap["points"]], ["08:00", "08:01", "08:02"])
        self.assertAlmostEqual(accumulator.latest_pct(), 1.47)
        self.assertAlmostEqual(snap["pre_close"], 6800.0)

    def test_accumulator_overlay_wins_same_minute(self):
        accumulator = benchmark_data._KospiAccumulator()
        accumulator.set_em_base({
            "trade_date": accumulator._today(),
            "pre_close": 6800.0,
            "points": [{"time": "08:01", "price": 6840.0, "pct": 0.59}],  # 东财延迟值
        })
        accumulator.upsert_minute("08:01", 6855.0, 0.81, pre_close=6800.0)  # 新浪实时值
        snap = accumulator.snapshot()
        self.assertEqual(len(snap["points"]), 1)
        self.assertAlmostEqual(snap["points"][0]["pct"], 0.81)
        self.assertAlmostEqual(accumulator.latest_pct(), 0.81)

    def test_accumulator_stale_base_dropped(self):
        """基线是昨日(如韩国休市日东财返回上一场)而新浪有今日点 → 只出今日的点。"""
        from datetime import timedelta

        from backend.time_utils import now_beijing

        accumulator = benchmark_data._KospiAccumulator()
        yesterday = (now_beijing() - timedelta(days=1)).strftime("%Y-%m-%d")
        accumulator.set_em_base({
            "trade_date": yesterday,
            "pre_close": 6800.0,
            "points": [{"time": "08:00", "price": 6810.0, "pct": 0.15}],
        })
        accumulator.upsert_minute("08:05", 6900.0, 1.47)
        snap = accumulator.snapshot()
        self.assertIsNotNone(snap)
        self.assertEqual([p["time"] for p in snap["points"]], ["08:05"])

    def test_accumulator_upsert_minute(self):
        accumulator = benchmark_data._KospiAccumulator()
        accumulator.upsert_minute("08:05", 6900.0, 1.47, pre_close=6800.0)
        self.assertAlmostEqual(accumulator.latest_pct(), 1.47)
        snap = accumulator.snapshot()
        self.assertIsNotNone(snap)
        self.assertEqual(snap["source"], "sina_accum")  # 只有新浪实时层
        self.assertEqual(len(snap["points"]), 1)

    def test_kospi_trends_sina_primary(self):
        """新浪实时优先链: 新浪可用即出曲线,东财基线挂了也不影响(只打日志)。"""
        fresh = benchmark_data._KospiAccumulator()
        sina = {"price": 6900.0, "pct": 1.47, "pre_close": 6800.0, "trade_date": None, "fetched_at": ""}
        with mock.patch.object(benchmark_data, "KOSPI_ACCUMULATOR", fresh), \
                mock.patch.object(benchmark_data, "ARB_KOSPI_ACCUM_WINDOW", ("00:00", "23:59")), \
                mock.patch.object(benchmark_data, "get_kospi_snapshot_sina", return_value=sina), \
                mock.patch.object(benchmark_data, "_fetch_em_trends", side_effect=RuntimeError("东财挂了")):
            payload = benchmark_data._fetch_kospi_trends()
        self.assertIsNotNone(payload)
        self.assertEqual(payload["source"], "sina_accum")
        self.assertEqual(len(payload["points"]), 1)
        self.assertAlmostEqual(payload["points"][0]["pct"], 1.47)
        # 东财失败只记退避,不抛异常
        self.assertFalse(fresh.base_expired(600))

    def test_kospi_trends_holiday_snapshot_not_upserted(self):
        """韩国休市: 新浪快照交易日是昨天 → 不 upsert,曲线不含旧 session 的值。"""
        from datetime import timedelta

        from backend.time_utils import now_beijing

        fresh = benchmark_data._KospiAccumulator()
        yesterday = (now_beijing() - timedelta(days=1)).strftime("%Y-%m-%d")
        stale = {"price": 6900.0, "pct": 1.47, "pre_close": 6800.0, "trade_date": yesterday, "fetched_at": ""}
        with mock.patch.object(benchmark_data, "KOSPI_ACCUMULATOR", fresh), \
                mock.patch.object(benchmark_data, "ARB_KOSPI_ACCUM_WINDOW", ("00:00", "23:59")), \
                mock.patch.object(benchmark_data, "get_kospi_snapshot_sina", return_value=stale), \
                mock.patch.object(benchmark_data, "_fetch_em_trends", side_effect=RuntimeError("东财挂了")):
            payload = benchmark_data._fetch_kospi_trends()
        self.assertIsNone(payload)
        self.assertIsNone(fresh.latest_pct())


class TestTdxBoardTrends(unittest.TestCase):
    def test_latest_date_filter_and_pct(self):
        df = pd.DataFrame({
            "datetime": [
                "2026-08-18 14:59:00",
                "2026-08-19 09:31:00",
                "2026-08-19 09:32:00",
            ],
            "open": [100.0, 101.0, 101.2],
            "close": [100.5, 101.5, 101.8],
        })
        quotes = [{"code": "880301", "pre_close": 100.0}]
        with mock.patch.object(benchmark_data.pytdx_data, "get_index_kline", return_value=df), \
                mock.patch.object(benchmark_data.pytdx_data, "get_realtime_quotes", return_value=quotes):
            fetched = benchmark_data._fetch_tdx_board_trends("880301")
        self.assertEqual(fetched["trade_date"], "2026-08-19")
        self.assertFalse(fetched["pre_close_approx"])
        self.assertAlmostEqual(fetched["pre_close"], 100.0)
        self.assertEqual([p["time"] for p in fetched["points"]], ["09:31", "09:32"])
        self.assertAlmostEqual(fetched["points"][0]["pct"], 1.5, places=4)

    def test_pre_close_fallback_to_first_open(self):
        df = pd.DataFrame({
            "datetime": ["2026-08-19 09:31:00"],
            "open": [200.0],
            "close": [201.0],
        })
        with mock.patch.object(benchmark_data.pytdx_data, "get_index_kline", return_value=df), \
                mock.patch.object(benchmark_data.pytdx_data, "get_realtime_quotes", return_value=[{}]):
            fetched = benchmark_data._fetch_tdx_board_trends("880302")
        self.assertTrue(fetched["pre_close_approx"])
        self.assertAlmostEqual(fetched["pre_close"], 200.0)
        self.assertAlmostEqual(fetched["points"][0]["pct"], 0.5, places=4)


class TestTwinCode(unittest.TestCase):
    def test_twin_code_requires_label(self):
        self.assertIsNone(benchmark_data._tdx_twin_code("em_board", None))
        self.assertIsNone(benchmark_data._tdx_twin_code("em_index", "国家大基金持股"))

    def test_twin_code_matches_by_name(self):
        fake_boards = {"loaded": True, "boards": {"880930": "国家大基金持股"}}
        with mock.patch.object(benchmark_data, "_load_tdx_board_names", return_value=fake_boards["boards"]):
            self.assertEqual(benchmark_data._tdx_twin_code("em_board", "国家大基金持股"), "880930")
            self.assertEqual(benchmark_data._tdx_twin_code("em_board", "国家大基金"), "880930")


class TestResolveBoardCode(unittest.TestCase):
    def test_builtin_alias_no_network(self):
        """内置别名(国家大基金持股→BK0717)优先于在线解析,零网络可用。"""
        for keyword in ("国家大基金持股", "国家大基金", "大基金"):
            items = benchmark_data.resolve_board_code(keyword)
            self.assertTrue(len(items) >= 1, keyword)
            self.assertEqual(items[0]["kind"], "em_board")
            self.assertEqual(items[0]["code"], "BK0717")
            self.assertEqual(items[0]["source"], "builtin")

    def test_empty_keyword(self):
        self.assertEqual(benchmark_data.resolve_board_code(""), [])


class TestEngineWindows(unittest.TestCase):
    def test_window_helpers(self):
        from backend.arb import engine
        from backend.config import ARB_PREOPEN_WINDOW, ARB_ALERT_SESSIONS

        self.assertTrue(engine._in_window("09:20", ARB_PREOPEN_WINDOW))
        self.assertFalse(engine._in_window("09:31", ARB_PREOPEN_WINDOW))
        self.assertTrue(engine._in_sessions("10:30", ARB_ALERT_SESSIONS))
        self.assertTrue(engine._in_sessions("13:45", ARB_ALERT_SESSIONS))
        self.assertFalse(engine._in_sessions("12:00", ARB_ALERT_SESSIONS))
        self.assertFalse(engine._in_sessions("15:01", ARB_ALERT_SESSIONS))


if __name__ == "__main__":
    unittest.main()
