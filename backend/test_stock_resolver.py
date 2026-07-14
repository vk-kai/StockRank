# -*- coding: utf-8 -*-
import unittest

from stock_resolver import classify_board, get_limit_pct


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


if __name__ == '__main__':
    unittest.main()
