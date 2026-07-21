# -*- coding: utf-8 -*-
import unittest

from data.stock_resolver import (
    classify_board, get_limit_pct,
    parse_sina_suggest, resolve_identifier, NameCodeCache,
)


class BoardLimitTests(unittest.TestCase):
    def test_main_board_sh(self):
        self.assertEqual(classify_board('sh600519'), 'main')
        self.assertEqual(get_limit_pct('sh600519', '贵州茅台'), 10.0)

    def test_main_board_sz_prefixes(self):
        for code in ('sz000001', 'sz001872', 'sz002594', 'sz003816'):
            self.assertEqual(classify_board(code), 'main', code)

    def test_creative_board_300_301_302(self):
        for code in ('sz300750', 'sz301236', 'sz302001'):
            self.assertEqual(classify_board(code), 'creative', code)
        self.assertEqual(get_limit_pct('sz301236', '某某'), 20.0)

    def test_star_board_688_689(self):
        self.assertEqual(classify_board('sh688981'), 'star')
        self.assertEqual(get_limit_pct('sh688981', '某某'), 20.0)

    def test_bse_board(self):
        for code in ('bj430047', 'bj830799', 'bj920002'):
            self.assertEqual(classify_board(code), 'bse', code)
        self.assertEqual(get_limit_pct('bj920002', '某某'), 30.0)

    def test_st_override_only_on_main_board(self):
        self.assertEqual(get_limit_pct('sh600519', '*ST 茅台'), 5.0)   # 主板 ST -> 5
        self.assertEqual(get_limit_pct('sz301236', 'ST 某某'), 20.0)    # 创业板 ST -> 仍 20
        self.assertEqual(get_limit_pct('sh688981', '*ST 某某'), 20.0)   # 科创板 ST -> 仍 20
        self.assertEqual(get_limit_pct('bj920002', 'ST 某某'), 30.0)    # 北交所 ST -> 仍 30

    def test_unknown_falls_back_to_ten(self):
        self.assertEqual(classify_board('zz999999'), 'unknown')
        self.assertEqual(get_limit_pct('zz999999', '某某'), 10.0)


class ResolveTests(unittest.TestCase):
    def test_parse_sina_suggest_returns_name_code_exchange(self):
        sample = "11\t贵州茅台\tsh600519\tgzmaotai\n11\t茅台转债\tsh113511\tmaotaizhuanzhuan\n"
        rows = parse_sina_suggest(sample)
        self.assertEqual(rows[0], ('贵州茅台', 'sh600519'))
        self.assertEqual(len(rows), 2)

    def test_parse_sina_suggest_comma_format(self):
        # 新浪 suggest3 当前实际返回格式: var suggestdata="字段0,..,name,..;...",分号分隔多条
        sample = ('var suggestdata="中信证券,11,600030,sh600030,中信证券,,中信证券,99,1,ESG,,;'
                  '中信银行,11,601998,sh601998,中信银行,,中信银行,99,1,ESG,,";')
        rows = parse_sina_suggest(sample)
        self.assertEqual(rows[0], ('中信证券', 'sh600030'))
        self.assertEqual(rows[1], ('中信银行', 'sh601998'))
        self.assertEqual(len(rows), 2)

    def test_resolve_name_uses_injected_fetcher_and_caches(self):
        calls = {'n': 0}

        def fake_fetch(keyword):
            calls['n'] += 1
            return "11\t贵州茅台\tsh600519\tgzmaotai\n"

        cache = NameCodeCache(path=None)
        name, code = resolve_identifier('贵州茅台', hint='name', fetcher=fake_fetch, cache=cache)
        self.assertEqual(code, 'sh600519')
        self.assertEqual(name, '贵州茅台')
        resolve_identifier('贵州茅台', hint='name', fetcher=fake_fetch, cache=cache)
        self.assertEqual(calls['n'], 1)

    def test_resolve_code_normalizes_prefix(self):
        self.assertEqual(resolve_identifier('600519', hint='code', fetcher=None)[1], 'sh600519')
        self.assertEqual(resolve_identifier('sh600519', hint='code', fetcher=None)[1], 'sh600519')
        self.assertEqual(resolve_identifier('sz301236', hint='code', fetcher=None)[1], 'sz301236')

    def test_resolve_unresolvable_returns_none(self):
        self.assertIsNone(resolve_identifier('不存在的公司xyz', hint='name',
                                             fetcher=lambda k: '\n', cache=NameCodeCache(path=None)))


if __name__ == '__main__':
    unittest.main()
