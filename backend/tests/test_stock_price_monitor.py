# -*- coding: utf-8 -*-
import os
import json
import tempfile
import unittest
from datetime import datetime, timedelta

from monitors import stock_price_monitor as m
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


class CooldownTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        m.REALTIME_DIR = self.tmp
        m.ALERTS_FILE = os.path.join(self.tmp, 'stock_price_alerts.json')

    def test_no_cooldown_on_first_hit(self):
        self.assertFalse(m.is_in_cooldown('sh600519', 'rapid_rise', [], 30))

    def test_cooldown_blocks_same_type_within_window(self):
        t0 = datetime(2026, 7, 14, 10, 0, 0)
        alerts = [{'code': 'sh600519', 'type': 'rapid_rise', 'timestamp': t0.isoformat()}]
        later = t0 + timedelta(minutes=10)
        self.assertTrue(m.is_in_cooldown('sh600519', 'rapid_rise', alerts, 30, now=later))

    def test_different_type_not_blocked(self):
        t0 = datetime(2026, 7, 14, 10, 0, 0)
        alerts = [{'code': 'sh600519', 'type': 'rapid_rise', 'timestamp': t0.isoformat()}]
        self.assertFalse(m.is_in_cooldown('sh600519', 'cum_move', alerts, 30, now=t0))

    def test_expired_cooldown_releases(self):
        t0 = datetime(2026, 7, 14, 10, 0, 0)
        alerts = [{'code': 'sh600519', 'type': 'rapid_rise', 'timestamp': t0.isoformat()}]
        later = t0 + timedelta(minutes=31)
        self.assertFalse(m.is_in_cooldown('sh600519', 'rapid_rise', alerts, 30, now=later))


class SealStateTests(unittest.TestCase):
    """涨停/跌停封板状态去重:detect_hits 层验证状态机。

    核心规则:封板期间不重复计入 limit_up/limit_down;明显开板(回落过 limit*0.99)
    后重新封板才再次计入。limit*0.995(触线) 与 limit*0.99(开板线) 之间为滞回保持带。
    """

    def _limit_up_q(self, pct=10.0):
        # prev_close=10,price 按 pct 反推,仅 detect_hits 主要看 pct
        return _q(round(10 * (1 + pct / 100), 3), 10.0, pct=pct)

    def test_sealed_blocks_rereport(self):
        state = {}
        q = self._limit_up_q(10.0)
        h1 = m.detect_hits(q, [q], state, m.DEFAULT_ALERTS_CFG, limit=10.0, name='X')
        self.assertIn('limit_up', [h['type'] for h in h1])
        self.assertTrue(state.get('limit_up_sealed'))
        # 第二、三次仍在涨停价 -> 封板状态抑制,不再命中 limit_up
        h2 = m.detect_hits(q, [q], state, m.DEFAULT_ALERTS_CFG, limit=10.0, name='X')
        h3 = m.detect_hits(q, [q], state, m.DEFAULT_ALERTS_CFG, limit=10.0, name='X')
        self.assertNotIn('limit_up', [h['type'] for h in h2])
        self.assertNotIn('limit_up', [h['type'] for h in h3])

    def test_open_then_reseal_rereports(self):
        state = {}
        at_limit = self._limit_up_q(10.0)
        h1 = m.detect_hits(at_limit, [at_limit], state, m.DEFAULT_ALERTS_CFG, limit=10.0, name='X')
        self.assertIn('limit_up', [h['type'] for h in h1])
        # 回落到 limit*0.99(=9.9) 以下 = 开板,清除封板标记
        pulled = self._limit_up_q(9.5)
        m.detect_hits(pulled, [pulled], state, m.DEFAULT_ALERTS_CFG, limit=10.0, name='X')
        self.assertFalse(state.get('limit_up_sealed'))
        # 重新封板 -> 再次命中 limit_up
        h3 = m.detect_hits(at_limit, [at_limit], state, m.DEFAULT_ALERTS_CFG, limit=10.0, name='X')
        self.assertIn('limit_up', [h['type'] for h in h3])

    def test_hold_band_keeps_sealed(self):
        state = {}
        at_limit = self._limit_up_q(10.0)
        m.detect_hits(at_limit, [at_limit], state, m.DEFAULT_ALERTS_CFG, limit=10.0, name='X')
        self.assertTrue(state.get('limit_up_sealed'))
        # 9.92 落在 [9.9, 9.95) 滞回保持带:既不在涨停价、也不构成开板 -> 封板标记保持
        hold = self._limit_up_q(9.92)
        m.detect_hits(hold, [hold], state, m.DEFAULT_ALERTS_CFG, limit=10.0, name='X')
        self.assertTrue(state.get('limit_up_sealed'))
        # 回到涨停价 -> 期间未真正开板,不再报
        h3 = m.detect_hits(at_limit, [at_limit], state, m.DEFAULT_ALERTS_CFG, limit=10.0, name='X')
        self.assertNotIn('limit_up', [h['type'] for h in h3])

    def test_limit_down_sealed_symmetric(self):
        state = {}
        at_down = _q(9.0, 10.0, pct=-10.0)
        h1 = m.detect_hits(at_down, [at_down], state, m.DEFAULT_ALERTS_CFG, limit=10.0, name='X')
        self.assertIn('limit_down', [h['type'] for h in h1])
        self.assertTrue(state.get('limit_down_sealed'))
        # 仍在跌停价 -> 不再命中
        h2 = m.detect_hits(at_down, [at_down], state, m.DEFAULT_ALERTS_CFG, limit=10.0, name='X')
        self.assertNotIn('limit_down', [h['type'] for h in h2])
        # 反弹到 +5%(> -limit*0.99=-9.9) = 开板
        rebound = _q(10.5, 10.0, pct=5.0)
        m.detect_hits(rebound, [rebound], state, m.DEFAULT_ALERTS_CFG, limit=10.0, name='X')
        self.assertFalse(state.get('limit_down_sealed'))
        # 重新跌停 -> 再次命中
        h3 = m.detect_hits(at_down, [at_down], state, m.DEFAULT_ALERTS_CFG, limit=10.0, name='X')
        self.assertIn('limit_down', [h['type'] for h in h3])


class ProcessTickTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        m.REALTIME_DIR = self.tmp
        m.ALERTS_FILE = os.path.join(self.tmp, 'stock_price_alerts.json')
        m._stock_state.clear()

    def _cfg(self):
        return {'enabled': True, 'cooldown_minutes': 30,
                'watchlist': [{'id': '1', 'type': 'code', 'value': '600519',
                               'resolved_code': 'sh600519', 'resolved_name': '贵州茅台',
                               'enabled': True, 'price_alerts': m.DEFAULT_ALERTS_CFG}]}

    def _limit_up_quote(self):
        return {'price': 11.0, 'prev_close': 10.0, 'high': 11.0, 'low': 10.0,
                'open': 10.0, 'pct': 10.0, 'ts': '2026-07-14 09:30:00'}

    def test_hit_pushes_and_records(self):
        pushed = []
        m.process_tick('sh600519', '贵州茅台', self._limit_up_quote(), self._cfg(),
                       limit=10.0, pusher=lambda t, c: pushed.append((t, c)) or True)
        self.assertTrue(pushed)
        self.assertTrue(pushed[0][0].startswith('🔴'))  # 标题以 🔴 开头(利好=红)
        alerts = m._load_alerts()
        self.assertEqual(len(alerts), 1)            # 一次推送 = 一条记录
        self.assertEqual(alerts[0]['type'], 'limit_up')
        self.assertIn('cum_move', alerts[0]['types'])  # 联动的类型一并记录冷却

    def test_cooldown_skips_push(self):
        pushed = []
        push = lambda t, c: pushed.append((t, c)) or True
        m.process_tick('sh600519', '贵州茅台', self._limit_up_quote(), self._cfg(), limit=10.0, pusher=push)
        m.process_tick('sh600519', '贵州茅台', self._limit_up_quote(), self._cfg(), limit=10.0, pusher=push)
        self.assertEqual(len(pushed), 1)  # 第二次同票同类型 -> 全部冷却 -> 不再推

    def _limit_up_only_cfg(self):
        """只开 limit_up、关闭其余检测,便于隔离封板去重逻辑。"""
        cfg = self._cfg()
        alerts = json.loads(json.dumps(m.DEFAULT_ALERTS_CFG))
        for k in alerts:
            if k != 'limit_up':
                alerts[k]['enabled'] = False
        cfg['watchlist'][0]['price_alerts'] = alerts
        return cfg

    def test_sealed_not_rereported_after_cooldown(self):
        """封死涨停时,即使原冷却已过期,封板状态仍阻止重复推送(本次修复核心点)。"""
        pushed = []
        push = lambda t, c: pushed.append((t, c)) or True
        cfg = self._limit_up_only_cfg()
        m.process_tick('sh600519', '贵州茅台', self._limit_up_quote(), cfg, limit=10.0, pusher=push)
        self.assertEqual(len(pushed), 1)
        # 把已记录告警时间戳后移到 31 分钟前,模拟 30 分钟冷却已过期
        alerts = m._load_alerts()
        old_ts = (datetime.now() - timedelta(minutes=31)).isoformat()
        for a in alerts:
            a['timestamp'] = old_ts
        m._save_alerts(alerts)
        # 再次报价仍在涨停价 -> 封板状态抑制 limit_up,无其它类型可触发 -> 不再推送
        m.process_tick('sh600519', '贵州茅台', self._limit_up_quote(), cfg, limit=10.0, pusher=push)
        self.assertEqual(len(pushed), 1)


if __name__ == '__main__':
    unittest.main()
