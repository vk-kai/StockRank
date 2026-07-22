"""回归：data_processor 包化后 refresh_ths_cookie 的脚本定位。

历史 bug：data_processor.py 单文件→包(目录)后，refresh_ths_cookie 用单层 dirname(__file__)
会错指到包内(backend/data/data_processor/)，导致 ths_cookie_refresh.py 找不到、
Cookie 无法刷新、板块资金采集全线失败、首页折线图空。正确做法是取包父目录(backend/data/)。
"""
import os
import unittest

from data.data_processor import ths_client


class ThsCookieScriptPathTests(unittest.TestCase):
    def test_cookie_refresh_script_locatable(self):
        """ths_cookie_refresh.py 必须能被 refresh_ths_cookie 正确定位（包父目录）。"""
        script = ths_client._THS_COOKIE_REFRESH_SCRIPT
        self.assertTrue(
            os.path.exists(script),
            f"同花顺Cookie脚本定位失败: {script}\n"
            "data_processor 是包后应取包父目录(2层dirname)，而非 __file__ 同级。",
        )

    def test_script_path_points_to_package_sibling(self):
        """脚本须与 data_processor 包同级(在 backend/data/)，而非在包内。"""
        pkg_dir = os.path.dirname(os.path.abspath(ths_client.__file__))      # .../backend/data/data_processor
        parent_dir = os.path.dirname(pkg_dir)                                 # .../backend/data
        self.assertEqual(
            os.path.dirname(ths_client._THS_COOKIE_REFRESH_SCRIPT),
            parent_dir,
        )


if __name__ == '__main__':
    unittest.main()
