import json
import os
import tempfile
import unittest

import margin_collector


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


if __name__ == "__main__":
    unittest.main()
