import json
import os
import tempfile
import time
import unittest
from unittest import mock

from data import news_collector


def _reset_cache():
    """重置模块级缓存，保证测试间隔离。"""
    if hasattr(news_collector, '_news_status_cache'):
        news_collector._news_status_cache = None
    if hasattr(news_collector, '_news_status_signature'):
        news_collector._news_status_signature = None


class LoadAllNewsStatusCacheTests(unittest.TestCase):
    """load_all_news_status 的 mtime 缓存测试。"""

    def setUp(self):
        _reset_cache()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.news_dir = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()
        _reset_cache()

    def _write(self, name, items):
        with open(os.path.join(self.news_dir, name), 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False)

    def test_caches_result_when_dir_unchanged(self):
        """目录未变时，二次调用应返回同一缓存对象（不重读磁盘）。"""
        self._write('2026-07-21.json', [
            {'title': 't1', 'content': 'c1', 'pushed': True,
             'ai_analyzed': False, 'pushed_channels': ['feishu']}
        ])
        with mock.patch.object(news_collector, 'NEWS_DIR', self.news_dir):
            r1 = news_collector.load_all_news_status()
            r2 = news_collector.load_all_news_status()
        self.assertIs(r1, r2, '目录未变时应命中缓存、返回同一对象')

    def test_reloads_when_file_content_changes(self):
        """文件 mtime 变化时，应重新加载（避免缓存过度失效/不过期）。"""
        self._write('2026-07-21.json', [{'title': 't1', 'content': 'c1', 'pushed': False}])
        with mock.patch.object(news_collector, 'NEWS_DIR', self.news_dir):
            r1 = news_collector.load_all_news_status()
            self.assertIn(('t1', 'c1'), r1)
            time.sleep(0.05)  # 确保 mtime 变化
            self._write('2026-07-21.json', [{'title': 't2', 'content': 'c2', 'pushed': True}])
            r2 = news_collector.load_all_news_status()
        self.assertIn(('t2', 'c2'), r2)
        self.assertNotIn(('t1', 'c1'), r2)

    def test_reloads_when_file_added(self):
        """新增文件(条数变化)应使缓存失效。"""
        self._write('2026-07-21.json', [{'title': 't1', 'content': 'c1', 'pushed': False}])
        with mock.patch.object(news_collector, 'NEWS_DIR', self.news_dir):
            news_collector.load_all_news_status()
            self._write('2026-07-22.json', [{'title': 't2', 'content': 'c2', 'pushed': False}])
            r2 = news_collector.load_all_news_status()
        self.assertIn(('t2', 'c2'), r2)

    def test_force_reload_bypasses_cache(self):
        """force_reload=True 时即使签名不变也重新读盘。"""
        self._write('2026-07-21.json', [{'title': 't1', 'content': 'c1', 'pushed': False}])
        with mock.patch.object(news_collector, 'NEWS_DIR', self.news_dir):
            r1 = news_collector.load_all_news_status()
            r2 = news_collector.load_all_news_status(force_reload=True)
        # 强制重读得到新对象(内容相同但非同一对象)
        self.assertEqual(r1, r2)
        self.assertIsNot(r1, r2)


if __name__ == '__main__':
    unittest.main()
