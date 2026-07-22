"""AI 链综合环境灯 _ai_chain_summary 规则回归。

2026-07-22 调整：overall 改为“总量多数表决”(利好总数 vs 利空总数)，
取代原“宏观链一票否决”——避免宏观 1 个利空否决需求链 6 个利好的过度敏感。
"""
import unittest

from data.data_processor.ai_chain import _ai_chain_summary


def _ind(chain, impact):
    return {'chain': chain, 'impact': impact}


class AiChainSummaryTests(unittest.TestCase):
    def test_demand_bullish_macro_slightly_bearish_is_bullish(self):
        """用户场景：6 需求利好 vs 1 宏观利空(美元中性) → 偏多（原宏观否决会误判偏空）。"""
        indicators = (
            [_ind('demand', '利好') for _ in range(6)] +
            [_ind('macro', '中性'), _ind('macro', '利空')]
        )
        s = _ai_chain_summary(indicators)
        self.assertEqual(s['overall'], '偏多')
        self.assertEqual(s['bull_count'], 6)
        self.assertEqual(s['bear_count'], 1)
        # 链级 signal 仍分别给出，供前端展示
        self.assertEqual(s['demand_signal'], '偏多')
        self.assertEqual(s['macro_signal'], '偏空')

    def test_more_bear_than_bull_is_bearish(self):
        indicators = [_ind('demand', '利空') for _ in range(3)] + [_ind('macro', '利好')]
        self.assertEqual(_ai_chain_summary(indicators)['overall'], '偏空')

    def test_equal_bull_bear_is_neutral(self):
        indicators = [_ind('demand', '利好'), _ind('macro', '利空')]
        self.assertEqual(_ai_chain_summary(indicators)['overall'], '中性')


if __name__ == '__main__':
    unittest.main()
