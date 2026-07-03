import unittest
from unittest.mock import patch

import intraday_timeline


class IntradayTimelineTests(unittest.TestCase):
    def test_build_timeline_events_detects_sector_rank_changes_and_news(self):
        realtime_data = {
            "09:35": {
                "timestamp": "2026-07-03T09:35:00+08:00",
                "data": [
                    {"name": "机器人", "net_flow": 3000, "change": 0.01, "code": "BK0001"},
                    {"name": "半导体", "net_flow": 1000, "change": 0.005, "code": "BK0002"},
                ],
            },
            "09:40": {
                "timestamp": "2026-07-03T09:40:00+08:00",
                "data": [
                    {"name": "半导体", "net_flow": 9000, "change": 0.025, "code": "BK0002"},
                    {"name": "机器人", "net_flow": 3200, "change": 0.012, "code": "BK0001"},
                ],
            },
        }
        news = [
            {
                "id": "n1",
                "title": "半导体产业链出现新催化",
                "content": "半导体设备需求改善",
                "importance": "3",
                "time": "1783043100",
            }
        ]

        events = intraday_timeline.build_timeline_events(
            realtime_data=realtime_data,
            news_items=news,
            date_str="2026-07-03",
            market_summary=None,
        )

        event_types = [event["type"] for event in events]
        self.assertIn("sector_top_rank", event_types)
        self.assertIn("sector_rank_jump", event_types)
        self.assertIn("important_news", event_types)

        top_event = next(event for event in events if event["type"] == "sector_top_rank")
        self.assertEqual(top_event["target"], "半导体")
        self.assertEqual(top_event["time"], "09:40")
        self.assertEqual(top_event["importance"], 4)

    def test_get_stock_hover_summary_combines_market_margin_news_and_sector_rank(self):
        stock = {
            "code": "600000",
            "name": "浦发银行",
            "change": 0.0123,
            "turnover": 1.8,
            "market_cap": "2800亿",
            "industry": "银行",
        }
        margin = {
            "latest_date": "20260702",
            "latest_balance": 120000000.0,
            "series": [{"d": "20260702", "j": 3000000.0, "b": 120000000.0}],
        }
        realtime_data = {
            "10:00": {
                "data": [
                    {"name": "银行", "net_flow": 500000000, "change": 0.015, "code": "BK0475"},
                    {"name": "半导体", "net_flow": 200000000, "change": 0.01, "code": "BK1036"},
                ]
            }
        }
        news_result = {
            "news": [
                {"title": "银行板块估值修复", "content": "浦发银行相关", "time": "1783044000"},
                {"title": "其他新闻", "content": "无关", "time": "1783044100"},
            ]
        }

        with patch.object(intraday_timeline, "get_market_map_stocks", return_value={"stocks": [stock]}), \
            patch.object(intraday_timeline, "get_stock_margin_series", return_value=margin), \
            patch.object(intraday_timeline, "load_realtime_data", return_value=realtime_data), \
            patch.object(intraday_timeline, "get_recent_news", return_value=news_result):
            summary = intraday_timeline.get_stock_hover_summary("600000", "BK0475")

        self.assertTrue(summary["success"])
        self.assertEqual(summary["data"]["name"], "浦发银行")
        self.assertEqual(summary["data"]["sector_rank"], 1)
        self.assertEqual(summary["data"]["sector_name"], "银行")
        self.assertEqual(summary["data"]["margin"]["latest_net_inflow"], 3000000.0)
        self.assertEqual(len(summary["data"]["recent_news"]), 1)


if __name__ == "__main__":
    unittest.main()
