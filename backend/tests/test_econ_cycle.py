# -*- coding: utf-8 -*-
"""经济周期模块测试:差分还原/趋势态/评分/五态规则/信号灯/API/月报。

用临时 SQLite 库,不碰真实数据。
"""
import os
import tempfile
import unittest

from flask import Flask

from econ_cycle import db, engine, signals, backtest
from econ_cycle.notify import monthly_report
from routes import econ_cycle_routes


def _seed(code, pairs, vt='level'):
    db.upsert_series(code, [(p, v, '') for p, v in pairs], value_type=vt)


class EconCycleTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self._old_db = db.DB_FILE
        db.DB_FILE = os.path.join(tmp, 'econ_test.db')
        db._tables_ready = False
        db._db()  # 建表
        # 指标目录:全国 3 个(含 yoy) + 西安 1 个(cum_yoy)
        db.upsert_indicators([
            dict(code='PMI', name='制造业PMI', layer='leading', region='national',
                 unit='', weight=1.0, value_type='level'),
            dict(code='M1_YOY', name='M1同比', layer='leading', region='national',
                 unit='%', weight=1.0, value_type='yoy'),
            dict(code='IND_YOY', name='工业增加值同比', layer='coincident', region='national',
                 unit='%', weight=1.0, value_type='yoy'),
            dict(code='XA_IND_YOY', name='西安工业累计同比', layer='coincident', region='xian',
                 unit='%', weight=1.2, value_type='cum_yoy'),
        ])
        app = Flask(__name__)
        app.register_blueprint(econ_cycle_routes.bp)
        self.client = app.test_client()

    def tearDown(self):
        db.DB_FILE = self._old_db
        db._tables_ready = False

    # ---------------- 单元:差分与趋势 ----------------

    def test_derive_monthly_from_cum(self):
        # 1-6月累计同比 5,6,7 → 单月: 1月5, 2月7, 3月9 (2*6-5=7, 3*7-2*6=9)
        out = engine.derive_monthly_from_cum([('2026-01', 5.0), ('2026-02', 6.0), ('2026-03', 7.0)])
        self.assertEqual(out[0], ('2026-01', 5.0))
        self.assertAlmostEqual(out[1][1], 7.0)
        self.assertAlmostEqual(out[2][1], 9.0)

    def test_derive_monthly_gap_fallback(self):
        # 序列断裂(缺2月):3月只能用累计值近似
        out = engine.derive_monthly_from_cum([('2026-01', 5.0), ('2026-03', 7.0)])
        self.assertAlmostEqual(out[1][1], 7.0)

    def test_trend_state(self):
        self.assertEqual(engine.trend_state([('a', 1), ('b', 2), ('c', 3)])[0], 'rising')
        self.assertEqual(engine.trend_state([('a', 3), ('b', 2), ('c', 1)])[0], 'falling')
        self.assertEqual(engine.trend_state([('a', 5), ('b', 5.05)])[0], 'flat')

    # ---------------- 单元:评分与五态 ----------------

    def test_score_pmi_boom_line(self):
        # PMI 50 → 荣枯映射 50 分;动量 0 → 50 分
        s = engine.score_indicator_by_code(
            'PMI', [('2026-07', 50.0), ('2026-08', 50.0), ('2026-09', 50.0)], 'leading')
        self.assertAlmostEqual(s[0], 50.0)

    def test_score_yoy_zero_center(self):
        # 同比类 0 中心:PPI -2 → level 46,动量平 50 → 0.6*46+0.4*50
        s = engine.score_indicator_by_code(
            'PPI_YOY', [('2026-08', -2.0), ('2026-09', -2.0)], 'leading')
        self.assertAlmostEqual(s[0], 0.6 * 46 + 0.4 * 50, places=1)

    def test_score_percentile_for_level(self):
        # 水平值类走历史分位:递增序列最新值分位 100;
        # 动量分 slope=1 → 50+15=65;总分 0.6*100+0.4*65=86
        pairs = [('m%02d' % i, float(i)) for i in range(10)]
        s = engine.score_indicator_by_code('SHRZ', pairs, 'leading')
        self.assertEqual(s[0], 86.0)

    def test_decide_phase_five_states(self):
        # 强分+同步多数上行 → expansion
        score = dict(score=62, indicators=[
            dict(code='PMI', layer='leading', state='rising', slope=0.5),
            dict(code='M1_YOY', layer='leading', state='rising', slope=0.4),
            dict(code='IND_YOY', layer='coincident', state='rising', slope=0.3),
        ])
        phase, s, _ = engine.decide_phase(score, '2026-09', persist=False)
        self.assertEqual(phase, 'expansion')
        # 低分+动量负 → downturn/bottoming 二选一
        score2 = dict(score=35, indicators=[
            dict(code='PMI', layer='leading', state='falling', slope=-0.5),
            dict(code='IND_YOY', layer='coincident', state='falling', slope=-0.4),
        ])
        phase2, _, _ = engine.decide_phase(score2, '2026-09', persist=False)
        self.assertIn(phase2, ('downturn', 'bottoming'))

    # ---------------- 集成:引擎与信号灯 ----------------

    def test_judge_national_end_to_end(self):
        _seed('PMI', [('2026-07', 49.5), ('2026-08', 49.8), ('2026-09', 50.1)])
        _seed('M1_YOY', [('2026-07', 3.8), ('2026-08', 4.0), ('2026-09', 3.2)], vt='yoy')
        _seed('IND_YOY', [('2026-07', 4.5), ('2026-08', 5.2)], vt='yoy')
        r = engine.judge('national', persist=True)
        self.assertIsNotNone(r)
        self.assertEqual(r['phase'], r['phase'] and engine.PHASE_NAMES[r['phase']] and r['phase'])
        self.assertTrue(0 <= r['score'] <= 100)
        self.assertTrue(r['indicators'])
        # 落库可查
        rows = db.get_phases('national')
        self.assertEqual(rows[-1]['month'], '2026-09')

    def test_judge_xian_derives_cum(self):
        # 西安累计同比 2026-01..03 = 1,2,3 → 差分单月 1,3,5
        # 差分公式 M(N)=N*C(N)-(N-1)*C(N-1): 2月=2*2-1*1=3, 3月=3*3-2*2=5
        _seed('XA_IND_YOY', [('2026-01', 1.0), ('2026-02', 2.0), ('2026-03', 3.0)], vt='cum_yoy')
        r = engine.judge('xian', month='2026-03', persist=False)
        self.assertIsNotNone(r)
        xa = [i for i in r['indicators'] if i['code'] == 'XA_IND_YOY'][0]
        self.assertAlmostEqual(xa['value'], 5.0)

    def test_job_switch_light_green(self):
        # 新逻辑:岗位供给为王。PMI_EMP>=50(+40) + PMI_ORDER>=50(+20) + M1>0(+10) + IND>=6(+15) = 85
        _seed('PMI_EMP', [('2026-09', 50.5)])
        _seed('PMI_ORDER', [('2026-09', 50.6)])
        _seed('PMI', [('2026-09', 50.5)])
        _seed('M1_YOY', [('2026-09', 5.0)], vt='yoy')
        _seed('IND_YOY', [('2026-09', 6.5)], vt='yoy')
        out = signals.job_switch_light()
        self.assertEqual(out['light'], 'green')

    def test_job_switch_layoff_blocks_green(self):
        # 回归:PMI总值>50 但从业人员 48.7(净减员)时不得给绿灯——用户体感"岗位变少"必须被捕捉
        _seed('PMI_EMP', [('2026-09', 48.7)])
        _seed('PMI_ORDER', [('2026-09', 50.6)])
        _seed('PMI', [('2026-09', 50.1)])
        _seed('M1_YOY', [('2026-09', 3.2)], vt='yoy')
        _seed('IND_YOY', [('2026-09', 5.2)], vt='yoy')
        out = signals.job_switch_light()
        self.assertEqual(out['light'], 'yellow')
        self.assertLess(out['score'], 55)

    def test_startup_light_red_when_all_weak(self):
        # 新逻辑:RETAIL -1(0) + IND 2(+10) + PPI -3(+5) = 15 → 红
        _seed('RETAIL_YOY', [('2026-09', -1.0)], vt='yoy')
        _seed('IND_YOY', [('2026-09', 2.0)], vt='yoy')
        _seed('PPI_YOY', [('2026-09', -3.0)], vt='yoy')
        out = signals.startup_light()
        self.assertEqual(out['light'], 'red')
        self.assertLess(out['score'], 40)

    def test_signals_read_by_value_type(self):
        # 回归:value_type 错误曾导致 yoy 指标读不到(红灯假象)
        _seed('M1_YOY', [('2026-09', 9.9)], vt='yoy')
        ind = next(i for i in db.get_indicators() if i['code'] == 'M1_YOY')
        self.assertEqual(ind['value_type'], 'yoy')
        s = db.get_series('M1_YOY', value_type='yoy')
        self.assertEqual(s[-1][1], 9.9)

    # ---------------- API ----------------

    def test_api_overview(self):
        _seed('PMI', [('2026-08', 49.8), ('2026-09', 50.1)])
        _seed('M1_YOY', [('2026-09', 3.5)], vt='yoy')
        _seed('IND_YOY', [('2026-09', 5.5)], vt='yoy')
        resp = self.client.get('/api/econ/overview')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body['success'])
        self.assertIn('national', body['data'])
        self.assertIn('job_switch', body['data'])
        self.assertIn('startup', body['data'])

    def test_api_phases_scope_guard(self):
        resp = self.client.get('/api/econ/phases/badscope')
        self.assertEqual(resp.status_code, 400)
        resp2 = self.client.get('/api/econ/phases/national')
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.get_json()['scope'], 'national')
        self.assertIsInstance(resp2.get_json()['bands'], list)

    def test_api_series(self):
        _seed('PMI', [('2026-08', 49.8), ('2026-09', 50.1)])
        resp = self.client.get('/api/econ/series/PMI')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(len(body['points']), 2)
        self.assertEqual(body['indicator']['code'], 'PMI')

    def test_api_collect_requires_auth(self):
        resp = self.client.post('/api/econ/collect', json={})
        self.assertEqual(resp.status_code, 401)

    # ---------------- 月报 ----------------

    def test_monthly_report_format(self):
        _seed('PMI', [('2026-09', 50.1)])
        _seed('M1_YOY', [('2026-09', 3.2)], vt='yoy')
        _seed('IND_YOY', [('2026-09', 5.2)], vt='yoy')
        text = monthly_report()
        self.assertIn('经济周期月报', text)
        self.assertIn('全国', text)
        self.assertIn('换工作窗口', text)
        self.assertIn('创业窗口', text)

    # ---------------- 知识库与预判 ----------------

    def test_playbook_structure(self):
        from econ_cycle.playbook import playbook
        p = playbook()
        self.assertIn('PMI_EMP', p['guide'])
        self.assertEqual(len(p['phase_path']), 5)
        self.assertEqual(len(p['chain']), 6)
        # 传导链首环必须是订单
        self.assertEqual(p['chain'][0]['key'], 'PMI_ORDER')

    def test_forecast_requires_streak(self):
        from econ_cycle.playbook import build_forecast
        # 新订单仅 1 个月过线 → 不形成预判
        _seed('PMI_ORDER', [('2026-08', 49.0), ('2026-09', 50.6)])
        f = build_forecast()
        self.assertFalse(f['ready'])
        # 连续 2 月 ≥50 → 形成预判,窗口为起点+6~12 月
        _seed('PMI_ORDER', [('2026-08', 50.6), ('2026-09', 50.5)])
        f2 = build_forecast()
        self.assertTrue(f2['ready'])
        self.assertEqual(f2['order_streak_start'], '2026-08')
        self.assertEqual(f2['earliest'], '2027-02')
        self.assertEqual(f2['latest'], '2027-08')

    def test_forecast_break_on_49(self):
        from econ_cycle.playbook import build_forecast
        # 中途跌破 49 → 计时作废,只有最后 1 月 → 不 ready
        _seed('PMI_ORDER', [('2026-05', 51.0), ('2026-06', 48.5), ('2026-09', 50.5)])
        f = build_forecast()
        self.assertFalse(f['ready'])

    def test_api_playbook(self):
        resp = self.client.get('/api/econ/playbook')
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body['success'])
        self.assertIn('guide', body['data'])
        self.assertIn('forecast', body['data'])

    # ---------------- 回测 ----------------

    def test_backtest_bands_and_hit_rate_structure(self):
        # 灌 10 个月数据,回放应产出阶段带;hit_rate 结构固定
        _seed('PMI', [('2025-%02d' % m, 49.0 + m * 0.2) for m in range(1, 11)])
        _seed('M1_YOY', [('2025-%02d' % m, 2.0 + m * 0.1) for m in range(1, 11)], vt='yoy')
        _seed('IND_YOY', [('2025-%02d' % m, 4.0 + m * 0.1) for m in range(1, 11)], vt='yoy')
        bands = backtest.phase_bands('national')
        self.assertTrue(bands)
        self.assertIn('phase_cn', bands[-1])
        self.assertIn('color', bands[-1])
        hr = backtest.hit_rate('national')
        self.assertIn(3, hr)
        self.assertIn(6, hr)
        for h, r in hr.items():
            self.assertIn('signals', r)
            self.assertIn('rate', r)


if __name__ == '__main__':
    unittest.main()
