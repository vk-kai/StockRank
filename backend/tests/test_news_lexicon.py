# -*- coding: utf-8 -*-
import unittest

from analysis.news_lexicon import (
    analyze_news_local,
    analyze_batch_local,
    format_markdown,
    analyze_news_local_sync,
)
from analysis.ai_analyzer import extract_score_from_analysis, is_important_news


class NewsLexiconTests(unittest.TestCase):
    def test_positive_event_scores_directional(self):
        r = analyze_news_local('公司中标5.2亿元大单', '公司与客户签署重大合同，金额5.2亿元')
        self.assertGreaterEqual(r['score'], 55)
        self.assertEqual(r['level'], '重大')
        self.assertEqual(r['action_suggestion'], '立即推送')
        self.assertTrue(is_important_news(r))
        self.assertIn('利好', r['core_event'])

    def test_negative_event_scores_directional_and_major(self):
        r = analyze_news_local('某公司因涉嫌信披违规被证监会立案调查', '公司于今日收到证监会立案调查通知书')
        self.assertLessEqual(r['score'], 45)
        self.assertEqual(r['level'], '重大')
        self.assertTrue(is_important_news(r))

    def test_neutral_narrative_stays_neutral(self):
        r = analyze_news_local('公司发布投资者关系活动记录表', '公司接待机构调研，介绍近期经营情况，无未披露重大信息')
        self.assertTrue(46 <= r['score'] <= 54)
        self.assertEqual(r['level'], '一般')
        self.assertEqual(r['action_suggestion'], '忽略')
        self.assertFalse(is_important_news(r))

    def test_negation_reverses_sentiment(self):
        pos = analyze_news_local('公司中标城市管廊项目', '')
        neg = analyze_news_local('公司未能中标城市管廊项目', '')
        self.assertGreater(pos['score'], neg['score'])
        self.assertLess(neg['score'], 50)

    def test_related_sector_extracted_from_text(self):
        r = analyze_news_local('先进封装需求旺盛，晶圆厂产能满载', '全球芯片代工产能利用率维持高位')
        self.assertIn('半导体', r['related_sector'])

    def test_impact_market_detection(self):
        us = analyze_news_local('美联储宣布降息25个基点', '美股三大指数集体收涨')
        self.assertEqual(us['impact_market'], '美股')
        a = analyze_news_local('公司中标国家电网项目', '')
        self.assertEqual(a['impact_market'], 'A股')

    def test_batch_output_schema(self):
        items = [
            {'id': 'n1', 'title': '公司业绩预增50%', 'content': ''},
            {'id': 'n2', 'title': '公司发布投资者关系活动记录表', 'content': '接待机构调研，无未披露重大信息'},
        ]
        out = analyze_batch_local(items)
        self.assertEqual(set(out.keys()), {'n1', 'n2'})
        for fields in out.values():
            for key in ('score', 'level', 'impact_type', 'event_type', 'core_event',
                        'reason', 'impact_market', 'related_sector', 'action_suggestion'):
                self.assertIn(key, fields)
        # 推送过滤字段下游兼容：业绩预增推送、中性调研记录不推送
        self.assertTrue(is_important_news(out['n1']))
        self.assertFalse(is_important_news(out['n2']))

    def test_markdown_score_extractable_by_existing_parser(self):
        r = analyze_news_local('公司回购股份用于注销', '拟回购2亿元股份并注销')
        md = format_markdown(r, '公司回购股份用于注销')
        score = extract_score_from_analysis(md)
        self.assertEqual(score, r['score'])

    def test_sync_entry_matches_analyze_news_shape(self):
        res = analyze_news_local_sync('公司业绩预增', '净利润同比增长80%')
        self.assertTrue(res['success'])
        self.assertIn('analysis', res)
        self.assertIn('duration', res)
        self.assertIn('/100', res['analysis'])


if __name__ == '__main__':
    unittest.main()
