# -*- coding: utf-8 -*-
"""时区纪律防回归测试。

历史教训(服务器时区 ≠ Asia/Shanghai,且反复翻车):
- 无时区参数的 datetime.now() → 服务器本地墙钟,调度/交易日/会话判断整体漂移;
- naive 与 aware datetime 直接比较 → TypeError(曾导致开启自动扫描后 /scan/status 全 500)。

规则:backend/ 内一律 now_beijing()(aware);
需要 naive 北京墙钟(与库内字符串互比)时用 now_beijing().replace(tzinfo=None)。
唯一豁免:time_utils.py(时间工具自身的实现细节)。

运行:cd TrendZen && .venv/Scripts/python.exe -X utf8 -m unittest tests.test_time_discipline -v
"""
import re
import unittest
from datetime import datetime, timedelta
from pathlib import Path

TRENDZEN_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = TRENDZEN_DIR / "backend"
ALLOWED_FILES = {"time_utils.py"}

FORBIDDEN_PATTERNS = [
    (re.compile(r"datetime\.now\(\s*\)"), "datetime.now() 无时区参数,应使用 now_beijing()"),
    (re.compile(r"datetime\.utcnow\(\)"), "datetime.utcnow() 已废弃且为 UTC 墙钟"),
    (re.compile(r"datetime\.today\(\)"), "datetime.today() 无时区"),
    (re.compile(r"\bdate\.today\(\)"), "date.today() 无时区"),
    (re.compile(r"utcfromtimestamp"), "utcfromtimestamp 已废弃"),
]


class TimeDisciplineTests(unittest.TestCase):
    def test_no_naive_now_in_backend(self):
        violations = []
        for py_file in sorted(BACKEND_DIR.rglob("*.py")):
            if py_file.name in ALLOWED_FILES:
                continue
            text = py_file.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue  # 教学注释里提及不算违规
                for pattern, label in FORBIDDEN_PATTERNS:
                    if pattern.search(line):
                        rel = py_file.relative_to(TRENDZEN_DIR)
                        violations.append(f"{rel}:{lineno} {label} | {stripped}")
        self.assertEqual(
            [],
            violations,
            "发现绕过 now_beijing() 的时间源:\n" + "\n".join(violations),
        )

    def test_now_beijing_anchored_to_utc8(self):
        from backend.time_utils import now_beijing

        now = now_beijing()
        self.assertIsNotNone(now.tzinfo, "now_beijing() 必须返回 aware datetime")
        self.assertEqual(now.utcoffset(), timedelta(hours=8), "北京时区全年固定 UTC+8(无夏令时)")

    def test_resolve_next_run_slot_accepts_aware_now(self):
        # 回归:e35a1a9 曾因 naive/aware 混比让开启自动扫描后 /scan/status 全 500
        from backend.live_scan.periods import resolve_next_run_slot
        from backend.time_utils import now_beijing

        resolve_next_run_slot(now_beijing(), "30min", is_trading_date=True)  # 不抛异常即通过

    def test_auth_and_db_now_helpers_use_beijing_wall(self):
        # 库内字符串两侧必须同为北京墙钟:写侧(db._now_text/auth._now)与读侧对齐。
        # 两次取 now 可能跨秒,允许 2 秒容差。
        from backend import db
        from backend import auth_service
        from backend.time_utils import now_beijing

        naive_bj = now_beijing().replace(tzinfo=None)
        db_dt = datetime.strptime(db._now_text(), "%Y-%m-%d %H:%M:%S")
        self.assertLessEqual(abs(db_dt - naive_bj), timedelta(seconds=2))
        self.assertLessEqual(abs(auth_service._now() - naive_bj), timedelta(seconds=2))


if __name__ == "__main__":
    unittest.main()
