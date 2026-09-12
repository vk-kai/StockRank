# -*- coding: utf-8 -*-
import unittest

from analysis.local_stock_scorer import score_batch, label_from_score


def _stock(**kw):
    base = {'name': '测试股', 'l1': '', 'l2': '', 'value': 100e8, 'pe': 25}
    base.update(kw)
    return base


class LocalStockScorerTests(unittest.TestCase):
    def test_scores_in_valid_range_and_schema(self):
        batch = [(f'60000{i}', _stock(l1='银行')) for i in range(10)]
        out = score_batch(batch)
        self.assertEqual(len(out), 10)
        for code, v in out.items():
            self.assertTrue(0 <= v['score'] <= 100)
            self.assertIn('score', v)
            self.assertIn('label', v)
            self.assertIn('reason', v)

    def test_distribution_has_spread(self):
        """混合行业/市值/估值的一批，分数必须有区分度（禁止全是50）。"""
        batch = [
            ('600001', _stock(name='芯原科技', l1='电子', l2='半导体', value=1500e8, pe=45)),
            ('600002', _stock(name='某某地产', l1='房地产', l2='房地产开发', value=200e8, pe=8)),
            ('600003', _stock(name='某某银行', l1='银行', l2='银行', value=3000e8, pe=5)),
            ('600004', _stock(name='某某水泥', l1='建材', l2='水泥', value=80e8, pe=70)),
            ('300001', _stock(name='智能装备', l1='机械设备', l2='机器人', value=300e8, pe=55)),
            ('830001', _stock(name='某某农业', l1='农林牧渔', l2='养殖', value=20e8, pe=90)),
        ]
        out = score_batch(batch)
        scores = [v['score'] for v in out.values()]
        self.assertGreaterEqual(max(scores) - min(scores), 25)
        # 半导体龙头应显著高于地产微盘
        self.assertGreater(out['600001']['score'], out['600002']['score'])

    def test_st_stock_clamped_low(self):
        out = score_batch([('000001', _stock(name='ST易联众', l1='计算机', pe=30))])
        self.assertLessEqual(out['000001']['score'], 15)
        self.assertEqual(out['000001']['reason'], 'ST/退市风险警示')

    def test_loss_company_penalized_more_than_valued_one(self):
        base = dict(l1='电子', l2='半导体', value=200e8)
        loss = score_batch([('600001', _stock(pe=-10, **base))])['600001']['score']
        valued = score_batch([('600001', _stock(pe=20, **base))])['600001']['score']
        self.assertGreater(valued, loss)

    def test_growth_industry_tolerates_high_pe(self):
        base = dict(name='某科技', l1='电子', l2='半导体', value=500e8)
        semi = score_batch([('600001', _stock(pe=80, **base))])['600001']['score']
        cement = score_batch([('600002', _stock(name='某水泥', pe=80, l1='建材', l2='水泥', value=500e8))])['600002']['score']
        self.assertGreater(semi, cement)

    def test_labels_match_bands(self):
        cases = [(95, '顶级'), (85, '优秀'), (75, '较优'), (65, '尚可'),
                 (55, '中性偏多'), (45, '中性偏空'), (30, '偏谨慎'), (15, '谨慎'), (5, '极谨慎')]
        for score, label in cases:
            with self.subTest(score=score):
                self.assertEqual(label_from_score(score), label)

    def test_reason_never_marks_insufficient(self):
        batch = [('600001', _stock(name='某公司', l1='无匹配行业', pe=None, value=0))]
        out = score_batch(batch)
        self.assertNotIn('信息不足', out['600001']['reason'])

    def test_deterministic(self):
        batch = [('600001', _stock(l1='银行'))]
        self.assertEqual(score_batch(batch), score_batch(batch))


class LocalScoringPipelineTests(unittest.TestCase):
    """AI 开关关闭 → start_scoring 走本地引擎的端到端验证（临时目录，不碰真实 scores.json）。"""

    def setUp(self):
        import shutil
        import tempfile
        import analysis.stock_scorer as ss

        self.ss = ss
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        self._orig = {k: getattr(ss, k) for k in (
            'STOCK_SCORES_DIR', 'STOCK_SCORES_FILE', 'STOCK_SCORE_STATUS_FILE',
            'load_ai_config', 'get_all_market_map_stocks')}
        self.addCleanup(self._restore)

        ss.STOCK_SCORES_DIR = self.tmp
        ss.STOCK_SCORES_FILE = self.tmp + '/scores.json'
        ss.STOCK_SCORE_STATUS_FILE = self.tmp + '/status.json'
        ss.load_ai_config = lambda: {'enabled': False}   # AI 关
        ss.get_all_market_map_stocks = lambda: {
            'sh600519': {'name': '贵州茅台', 'l1': '食品饮料', 'l2': '白酒', 'value': 20000e8, 'pe': 22},
            'sz000002': {'name': '某地产', 'l1': '房地产', 'l2': '房地产开发', 'value': 200e8, 'pe': 8},
            'sh688001': {'name': '某芯片', 'l1': '电子', 'l2': '半导体', 'value': 800e8, 'pe': 45},
        }
        ss._cancel_event.clear()
        ss._score_status.update(ss._default_status())

    def _restore(self):
        for k, v in self._orig.items():
            setattr(self.ss, k, v)

    def test_start_scoring_local_pipeline(self):
        ret = self.ss.start_scoring('all')
        self.assertTrue(ret['success'])
        self.assertIn('本地', ret['message'])
        self.ss._worker_thread.join(timeout=10)
        status = self.ss.get_status()
        self.assertEqual(status['status'], 'completed')
        self.assertEqual(status['done'], 3)
        scores = self.ss.load_scores()
        self.assertEqual(set(scores.keys()), {'600519', '000002', '688001'})
        for v in scores.values():
            self.assertIsNotNone(v['score'])
            self.assertTrue(v['label'])


if __name__ == '__main__':
    unittest.main()
