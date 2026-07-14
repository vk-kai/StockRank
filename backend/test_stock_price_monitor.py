# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

import stock_price_monitor as m


class LazyRotationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        m.REALTIME_DIR = self.tmp  # 重定向数据目录

    def test_append_keeps_same_day_samples(self):
        m.append_sample('sh600519', {'ts': '2026-07-14 09:30:00', 'price': 1685, 'pct': 0.5,
                                     'open': 1685, 'prev_close': 1676, 'high': 1688, 'low': 1684},
                        date='2026-07-14')
        m.append_sample('sh600519', {'ts': '2026-07-14 09:30:25', 'price': 1690, 'pct': 0.8,
                                     'open': 1685, 'prev_close': 1676, 'high': 1692, 'low': 1684},
                        date='2026-07-14')
        data = m.load_quotes('2026-07-14')
        self.assertEqual(len(data['sh600519']), 2)

    def test_new_day_wipes_previous(self):
        m.append_sample('sh600519', {'ts': '2026-07-13 15:00:00', 'price': 1680, 'pct': 0.2,
                                     'open': 1678, 'prev_close': 1676, 'high': 1685, 'low': 1675},
                        date='2026-07-13')
        # 次交易日第一笔到来
        m.append_sample('sh600519', {'ts': '2026-07-14 09:30:00', 'price': 1685, 'pct': 0.5,
                                     'open': 1685, 'prev_close': 1676, 'high': 1688, 'low': 1684},
                        date='2026-07-14')
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'stock_quotes_2026-07-13.json')))
        data = m.load_quotes('2026-07-14')
        self.assertEqual(len(data['sh600519']), 1)  # 旧日数据被清


if __name__ == '__main__':
    unittest.main()
