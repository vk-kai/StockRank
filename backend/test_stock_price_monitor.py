# -*- coding: utf-8 -*-
import os
import json
import tempfile
import unittest

import stock_price_monitor as m


def _q(price, prev_close, high=None, low=None, pct=None):
    high = price if high is None else high
    low = price if low is None else low
    if pct is None:
        pct = round((price - prev_close) / prev_close * 100, 3)
    return {'price': price, 'prev_close': prev_close, 'high': high, 'low': low,
            'open': prev_close, 'pct': pct, 'ts': '2026-07-14 09:30:00'}


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


class DetectionTests(unittest.TestCase):
    def test_limit_up_main_board(self):
        q = _q(11.0, 10.0, pct=10.0)
        hits = m.detect_hits(q, series=[q], state={}, alerts_cfg=m.DEFAULT_ALERTS_CFG,
                             limit=10.0, name='某某')
        self.assertIn('limit_up', [h['type'] for h in hits])

    def test_rapid_rise_within_window(self):
        # 3 分钟前 -1%,现在 +3% -> 急速拉升 4%/3min(默认阈值 3%)
        prev = _q(9.9, 10.0, pct=-1.0); prev['ts'] = '2026-07-14 09:27:00'
        now = _q(10.3, 10.0, pct=3.0); now['ts'] = '2026-07-14 09:30:00'
        hit = m._rapid_move(now, [prev, now], m.DEFAULT_ALERTS_CFG)
        self.assertIsNotNone(hit)
        self.assertEqual(hit['type'], 'rapid_rise')

    def test_cum_move_default_threshold(self):
        now = _q(10.3, 10.0, pct=3.0)
        self.assertEqual(m._cum_move(now, m.DEFAULT_ALERTS_CFG)['type'], 'cum_move')

    def test_spike_fade(self):
        # 曾涨 4%(最高 10.40),现 +1.6% -> 高点回落 ≈ 2.3% 触发(peak≥3,back≥2)
        now = _q(10.16, 10.0, high=10.40, pct=1.6)
        self.assertEqual(m._spike_fade(now, m.DEFAULT_ALERTS_CFG)['type'], 'spike_fade')

    def test_amplitude(self):
        # 振幅 (10.7-9.5)/10 = 12% >= 7%
        now = _q(10.2, 10.0, high=10.7, low=9.5)
        self.assertEqual(m._amplitude(now, m.DEFAULT_ALERTS_CFG)['type'], 'amplitude')

    def test_disabled_type_not_fired(self):
        cfg = json.loads(json.dumps(m.DEFAULT_ALERTS_CFG))
        cfg['amplitude']['enabled'] = False
        now = _q(10.2, 10.0, high=10.7, low=9.5)
        self.assertIsNone(m._amplitude(now, cfg))


if __name__ == '__main__':
    unittest.main()
