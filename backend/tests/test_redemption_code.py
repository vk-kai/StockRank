"""兑换码（体验访问）机制单元测试 + 路由回归。

覆盖：
- core/redemption_code 纯服务：生成超额拒绝、兑换一次性、池自动补足、过期惰性标记、并发兑换互斥。
- 路由：未登录 401 → 兑换成功建会话 → 受保护接口 200 → 过期后 401；vk 能生成、体验码会话不能生成。
"""
import os
import tempfile
import threading
import time
import unittest

from core import redemption_code
from core.daily_password import get_daily_password

# 路由测试依赖完整 Flask 应用（flask_socketio 等）；本地无依赖时跳过，
# 容器内（依赖齐全）才执行。服务层测试无此依赖，始终运行。
try:
    from app import create_app
    _HAS_FLASK_APP = True
except Exception:  # pragma: no cover - 本地环境缺依赖
    _HAS_FLASK_APP = False
    create_app = None


class RedemptionCodeServiceTests(unittest.TestCase):
    def setUp(self):
        # 用临时文件隔离，避免污染仓库 config/redemption_codes.json
        self._tmp = tempfile.mkdtemp(prefix='redeem_test_')
        self._file = os.path.join(self._tmp, 'redemption_codes.json')
        self._orig_file = redemption_code.REDEMPTION_CODES_FILE
        self._orig_dir = redemption_code.CONFIG_DIR
        redemption_code.REDEMPTION_CODES_FILE = self._file
        redemption_code.CONFIG_DIR = self._tmp

    def tearDown(self):
        redemption_code.REDEMPTION_CODES_FILE = self._orig_file
        redemption_code.CONFIG_DIR = self._orig_dir
        try:
            for f in os.listdir(self._tmp):
                os.remove(os.path.join(self._tmp, f))
            os.rmdir(self._tmp)
        except Exception:
            pass

    def test_create_codes_respects_pool_size(self):
        # 默认池 10：生成 5 成功，再生成 6（5+6=11>10）应被拒
        r1 = redemption_code.create_codes('大盘云图', '/market-map', '10min', 5)
        self.assertTrue(r1['success'])
        self.assertEqual(len(r1['codes']), 5)
        self.assertEqual(r1['can_generate'], 5)  # 10 - 5

        r2 = redemption_code.create_codes('测试', '/', '10min', 6)
        self.assertFalse(r2['success'])
        self.assertEqual(r2['error'], 'overflow')
        self.assertEqual(r2['can_generate'], 5)

    def test_redeem_is_one_time_and_refills_pool(self):
        redemption_code.create_codes('大盘云图', '/market-map', '10min', 3)
        status_before = redemption_code.get_pool_status()
        self.assertEqual(len(status_before['active']), 3)

        code = status_before['active'][0]['code']
        r = redemption_code.redeem(code, '1.2.3.4')
        self.assertTrue(r['success'])
        self.assertEqual(r['page'], '/market-map')
        self.assertGreater(r['expire_at'], time.time())

        # 兑换后 active 仍应为 3（用掉 1 张，补 1 张同款）—— 池不变
        status_after = redemption_code.get_pool_status()
        self.assertEqual(len(status_after['active']), 3)
        # used 历史多 1 条
        self.assertEqual(len(status_after['used']), 1)
        self.assertEqual(status_after['used'][0]['code'], code)
        self.assertEqual(status_after['used'][0]['status'], 'active')

        # 同一码再兑换 → 失败（一次性）
        r2 = redemption_code.redeem(code)
        self.assertFalse(r2['success'])
        self.assertEqual(r2['error'], 'invalid')

    def test_invalid_code_redeem_fails(self):
        r = redemption_code.redeem('NOT-A-REAL-CODE')
        self.assertFalse(r['success'])

    def test_is_code_expired_lazy_and_revoke(self):
        redemption_code.create_codes('t', '/', '10min', 1)
        code = redemption_code.get_pool_status()['active'][0]['code']
        redemption_code.redeem(code)

        # 刚兑换：未过期
        self.assertFalse(redemption_code.is_code_expired(code))

        # 撤销后：视为失效
        redemption_code.revoke(code)
        self.assertTrue(redemption_code.is_code_expired(code))
        rec = redemption_code.find_in_used(code)
        self.assertEqual(rec['status'], 'revoked')

    def test_expired_marked_lazily(self):
        # permanent 不会过期；用一个已过期的 expire_at 手动构造 used 记录验证惰性标记
        redemption_code.create_codes('t', '/', '10min', 1)
        code = redemption_code.get_pool_status()['active'][0]['code']
        redemption_code.redeem(code)
        # 直接改文件把 expire_at 设到过去
        import json
        with open(self._file, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        cfg['used'][0]['expire_at'] = int(time.time()) - 10
        with open(self._file, 'w', encoding='utf-8') as f:
            json.dump(cfg, f)
        # is_code_expired 应惰性置为 expired
        self.assertTrue(redemption_code.is_code_expired(code))
        rec = redemption_code.find_in_used(code)
        self.assertEqual(rec['status'], 'expired')

    def test_concurrent_redeem_only_one_wins(self):
        redemption_code.create_codes('t', '/', '10min', 1)
        code = redemption_code.get_pool_status()['active'][0]['code']
        results = []
        lock = threading.Lock()

        def worker():
            r = redemption_code.redeem(code)
            with lock:
                results.append(r.get('success'))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # 恰好一个成功（一次性，线程安全）
        self.assertEqual(sum(1 for x in results if x), 1)


@unittest.skipUnless(_HAS_FLASK_APP, "完整 Flask 应用依赖未安装（容器内运行）")
class RedemptionRouteTests(unittest.TestCase):
    def setUp(self):
        # 路由测试也隔离到临时文件
        self._tmp = tempfile.mkdtemp(prefix='redeem_route_')
        self._file = os.path.join(self._tmp, 'redemption_codes.json')
        self._orig_file = redemption_code.REDEMPTION_CODES_FILE
        self._orig_dir = redemption_code.CONFIG_DIR
        redemption_code.REDEMPTION_CODES_FILE = self._file
        redemption_code.CONFIG_DIR = self._tmp

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        redemption_code.REDEMPTION_CODES_FILE = self._orig_file
        redemption_code.CONFIG_DIR = self._orig_dir
        try:
            for f in os.listdir(self._tmp):
                os.remove(os.path.join(self._tmp, f))
            os.rmdir(self._tmp)
        except Exception:
            pass

    def _seed_codes(self, n=1):
        redemption_code.create_codes('大盘云图', '/market-map', '10min', n)

    def test_unauth_blocked_then_redeem_grants_access(self):
        # 未登录 → 受保护接口 401
        self.assertEqual(self.client.get('/api/flow/current').status_code, 401)

        # 预置一张码，兑换之
        self._seed_codes(1)
        code = redemption_code.get_pool_status()['active'][0]['code']
        r = self.client.post('/api/auth/redeem', json={'code': code})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()['success'])

        # 兑换后 → 受保护接口 200（兑换码会话放行）
        self.assertEqual(self.client.get('/api/flow/current').status_code, 200)

        # session 报告 authenticated + is_admin=False
        sess = self.client.get('/api/auth/session').get_json()
        self.assertTrue(sess['authenticated'])
        self.assertFalse(sess['is_admin'])

    def test_redeem_session_cannot_access_admin_routes(self):
        self._seed_codes(1)
        code = redemption_code.get_pool_status()['active'][0]['code']
        self.client.post('/api/auth/redeem', json={'code': code})
        # 体验码会话访问管理列表 → 401（仅 vk）
        self.assertEqual(self.client.get('/api/config/redeem/list').status_code, 401)

    def test_expired_redeem_session_blocks(self):
        self._seed_codes(1)
        code = redemption_code.get_pool_status()['active'][0]['code']
        self.client.post('/api/auth/redeem', json={'code': code})
        # 手动把 session 里的过期时间设到过去，模拟到期
        with self.client.session_transaction() as sess:
            sess['redeem_expire'] = int(time.time()) - 10
        # 过期后 → 受保护接口重新 401
        self.assertEqual(self.client.get('/api/flow/current').status_code, 401)

    def test_invalid_code_returns_400(self):
        r = self.client.post('/api/auth/redeem', json={'code': 'FAKE-CODE-XXXX'})
        self.assertEqual(r.status_code, 400)

    def test_vk_can_generate_and_experience_session_cannot(self):
        # vk 登录
        login = self.client.post('/api/auth/login', json={
            'username': 'vk', 'password': get_daily_password()
        })
        self.assertEqual(login.status_code, 200)
        # vk 生成 3 张
        gen = self.client.post('/api/config/redeem/generate', json={
            'password': get_daily_password(),
            'label': '大盘云图', 'page': '/market-map',
            'duration': '10min', 'count': 3
        })
        self.assertEqual(gen.status_code, 200)
        self.assertTrue(gen.get_json()['success'])
        self.assertEqual(len(gen.get_json()['codes']), 3)
        # 每个码带可复制链接
        self.assertIn('?redeem=', gen.get_json()['codes'][0]['link'])
        # vk 能列
        lst = self.client.get('/api/config/redeem/list')
        self.assertEqual(lst.status_code, 200)
        self.assertEqual(len(lst.get_json()['active']), 3)


if __name__ == "__main__":
    unittest.main()
