# -*- coding: utf-8 -*-
import unittest

from data.stock_price_feed import parse_sina, parse_tencent, get_quotes


# 新浪字段顺序:0 名称,1 今开,2 昨收,3 现价,4 最高,5 最低,...
SINA_SAMPLE = (
    'var hq_str_sh600519="贵州茅台,1690.00,1676.50,1685.20,1698.00,1680.00,'
    '100,50,1685.20,100,1685.00,200,1686.00,300,1687.00,400,1688.00,500,1689.00,600,'
    '1690.00,700,1691.00,800,1692.00,900,300000,500000000,0,0,2026-07-14,09:30:00,00";\n'
)


def _build_tencent_sample():
    # 腾讯字段(以 ~ 分隔):1 名称,2 代码,3 现价,4 昨收,5 今开,...,30 日期,31 时间,33 最高,34 最低
    fields = ['1', '贵州茅台', '600519', '1685.20', '1676.50', '1690.00', '50', '100']  # idx 0-7
    fields += [''] * 22      # idx 8-29 占位
    fields += ['20260714', '09:30:00', '']  # idx 30 日期(YYYYMMDD), 31 时间, 32 占位
    fields += ['1698.00', '1680.00']  # idx 33 最高, 34 最低
    return 'v_sh600519="' + '~'.join(fields) + '";\n'


TENCENT_SAMPLE = _build_tencent_sample()


class FeedParseTests(unittest.TestCase):
    def test_parse_sina_extracts_fields(self):
        q = parse_sina(SINA_SAMPLE, ['sh600519'])['sh600519']
        self.assertAlmostEqual(q['price'], 1685.20)
        self.assertAlmostEqual(q['prev_close'], 1676.50)
        self.assertAlmostEqual(q['open'], 1690.00)
        self.assertAlmostEqual(q['high'], 1698.00)
        self.assertAlmostEqual(q['low'], 1680.00)
        self.assertAlmostEqual(q['pct'], round((1685.20 - 1676.50) / 1676.50 * 100, 3))

    def test_parse_tencent_extracts_fields(self):
        q = parse_tencent(TENCENT_SAMPLE, ['sh600519'])['sh600519']
        self.assertAlmostEqual(q['price'], 1685.20)
        self.assertAlmostEqual(q['prev_close'], 1676.50)
        self.assertAlmostEqual(q['high'], 1698.00)
        self.assertAlmostEqual(q['low'], 1680.00)

    def test_parse_tencent_synthesizes_ts(self):
        # 兜底源也必须带时间戳(对齐新浪 '%Y-%m-%d %H:%M:%S'),
        # 否则急涨急跌窗口/高低开窗口判定对兜底票整体失效(原 ts 恒为 '')
        q = parse_tencent(TENCENT_SAMPLE, ['sh600519'])['sh600519']
        self.assertEqual(q['ts'], '2026-07-14 09:30:00')

    def test_parse_tencent_ts_empty_when_fields_missing(self):
        # 30/31 字段缺失时退回空串,不抛异常
        fields = ['1', '贵州茅台', '600519', '1685.20', '1676.50', '1690.00']  # 无日期时间字段
        text = 'v_sh600519="' + '~'.join(fields) + '";\n'
        q = parse_tencent(text, ['sh600519'])['sh600519']
        self.assertEqual(q['ts'], '')

    def test_get_quotes_falls_back_to_tencent_when_sina_empty(self):
        calls = []

        def sina_fetch(codes):
            calls.append('sina')
            return ''  # 新浪空/失败

        def tencent_fetch(codes):
            calls.append('tencent')
            return TENCENT_SAMPLE

        q = get_quotes(['sh600519'], sina_fetcher=sina_fetch, tencent_fetcher=tencent_fetch)
        self.assertIn('sh600519', q)
        self.assertEqual(calls, ['sina', 'tencent'])

    def test_get_quotes_uses_sina_when_ok(self):
        def sina_fetch(codes):
            return SINA_SAMPLE

        def tencent_fetch(codes):
            raise AssertionError('新浪可用时不应调用腾讯')

        q = get_quotes(['sh600519'], sina_fetcher=sina_fetch, tencent_fetcher=tencent_fetch)
        self.assertIn('sh600519', q)


if __name__ == '__main__':
    unittest.main()
