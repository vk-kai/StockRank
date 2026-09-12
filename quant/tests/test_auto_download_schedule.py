# -*- coding: utf-8 -*-
"""自动下载 today_done 状态机 + readiness 挂起分支计数口径回归测试(全 mock 无网络)。

背景(2026-09-09 线上问题):15:11 自动下载完成放行收盘扫描后,调度循环下一轮
把 today_done 清回 False,收盘挂起闸门整晚误报"尚未下载完成";同时挂起/下载中
分支把 local_ready_count 误接到下载状态的 qualified_count(启动即清0),面板
显示"立即扫描(0)/还有443只未满足条件",而逐股判定其实是 443。

运行:cd TrendZen && .venv/Scripts/python.exe -X utf8 -m unittest tests.test_auto_download_schedule -v
"""
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.history_download_service import (  # noqa: E402
    _auto_download_state,
    is_auto_download_done_today,
    set_auto_download_schedule_status,
)
from backend.live_scan import readiness  # noqa: E402


def _settings():
    return {
        "scan_period": "daily",
        "scan_scope_type": "all",
        "scan_scope_codes": [],
        "scan_focus_codes": [],
    }


def _candidates():
    return [{"code": "600000"}, {"code": "000001"}]


class IsAutoDownloadDoneTodayTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(_auto_download_state)

    def tearDown(self):
        _auto_download_state.clear()
        _auto_download_state.update(self._saved)

    def test_same_day_done_is_true(self):
        set_auto_download_schedule_status(today="2026-09-09", today_done=True, status="completed")
        self.assertTrue(is_auto_download_done_today("2026-09-09"))

    def test_cross_day_resets(self):
        set_auto_download_schedule_status(today="2026-09-09", today_done=True, status="completed")
        self.assertFalse(is_auto_download_done_today("2026-09-10"))

    def test_not_done_and_fresh_state(self):
        set_auto_download_schedule_status(today="2026-09-09", today_done=False, status="checking")
        self.assertFalse(is_auto_download_done_today("2026-09-09"))
        # 进程重启后内存态归零(today 为空)
        _auto_download_state["today"] = ""
        _auto_download_state["today_done"] = False
        self.assertFalse(is_auto_download_done_today("2026-09-09"))


class ScanReadinessCountingTests(unittest.TestCase):
    """挂起/下载中分支的 local_ready_count 必须是逐股判定值,不是 qualified_count。"""

    def _run(self, download_status):
        with mock.patch.object(readiness, "load_scan_universe_candidates", return_value=_candidates()), \
             mock.patch.object(readiness, "get_history_download_status", return_value=download_status), \
             mock.patch.object(readiness.db, "get_scan_settings", return_value=_settings()), \
             mock.patch.object(readiness, "get_local_history_ready", return_value=True), \
             mock.patch.object(readiness, "now_beijing", return_value=datetime(2026, 9, 9, 17, 0)), \
             mock.patch.object(readiness.akshare_data, "is_trading_date", return_value=True):
            return readiness.get_scan_readiness()

    def test_pending_branch_reports_per_stock_ready_count(self):
        result = self._run({
            "running": False,
            "qualified_count": 0,
            "auto_download_enabled": True,
            "auto_download_today": "2026-09-09",
            "auto_download_today_done": False,
        })
        self.assertFalse(result["scan_ready"])
        self.assertIn("挂起", result["message"])
        # 回归点:旧代码这里返回 qualified_count=0,面板显示"立即扫描(0)"
        self.assertEqual(result["local_ready_count"], 2)
        self.assertEqual(result["scan_universe_count"], 2)

    def test_running_branch_reports_per_stock_ready_count(self):
        result = self._run({
            "running": True,
            "qualified_count": 0,
            "auto_download_enabled": True,
            "auto_download_today": "2026-09-09",
            "auto_download_today_done": False,
        })
        self.assertFalse(result["scan_ready"])
        self.assertEqual(result["local_ready_count"], 2)
        self.assertEqual(result["scan_universe_count"], 2)

    def test_done_today_releases_gate(self):
        result = self._run({
            "running": False,
            "qualified_count": 0,
            "auto_download_enabled": True,
            "auto_download_today": "2026-09-09",
            "auto_download_today_done": True,
        })
        self.assertTrue(result["scan_ready"])
        self.assertEqual(result["local_ready_count"], 2)
        self.assertEqual(len(result["candidates"]), 2)


if __name__ == "__main__":
    unittest.main()
