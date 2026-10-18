# -*- coding: utf-8 -*-
"""许愿箱/出题投稿接口测试:覆盖接口文档自测清单 + vpay 奖励下发幂等。"""
import json
import os
import sqlite3
import tempfile
import unittest

from flask import Flask

from routes import mp_game_routes as m
from routes import mp_sec_routes as sec
from routes import mp_vpay_routes as v


def _draft_body(title='测测你是哪种约会人格', n_q=3, n_r=3, n_opts=3):
    return {
        'title': title,
        'questions': [{'q': f'问题{i}：周末你更想干嘛？', 'opts': [f'选项{j}' for j in range(n_opts)]}
                      for i in range(n_q)],
        'results': [{'name': f'结果人格{i}', 'desc': '你的快乐源泉是沙发和外卖'} for i in range(n_r)],
    }


class FeedbackDraftTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.db_file = os.path.join(tmp, 'game.db')
        m.DB_FILE = self.db_file
        v.VPAY_DB_FILE = self.db_file          # 与 game 同一库(线上同为 UNIFIED_DB_FILE)
        m._rl_store.clear()
        sec.MP_SEC_CONFIG_FILE = os.path.join(tmp, 'sec.json')
        self._set_auth_key('')                 # 默认免鉴权,鉴权单独测

        app = Flask(__name__)
        app.register_blueprint(m.mp_game_bp)
        app.register_blueprint(v.mp_vpay_bp)
        self.client = app.test_client()
        # vpay 依赖配置/环境,测试只关心 reward_until 字段,直接 mock
        v.load_vpay_config = lambda: {'appid': 'wxT', 'product_id': 'p1',
                                      'product_name': '测试商品', 'goods_price': 1}
        v.get_vpay_env = lambda: 0

    def _set_auth_key(self, key):
        with open(sec.MP_SEC_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({'auth_key': key}, f)

    def _fb(self, openid='oA', title='想要恋爱测试', **kw):
        body = {'openid': openid, 'title': title}
        body.update(kw)
        return self.client.post('/api/mp/game/feedback', json=body)

    def _draft(self, openid='oDRAFT', **kw):
        body = _draft_body(**kw)
        body['openid'] = openid
        return self.client.post('/api/mp/game/draft', json=body)

    # ---- 鉴权 ----
    def test_no_auth_key_rejected(self):
        self._set_auth_key('k1')
        resp = self._fb()
        self.assertEqual(resp.status_code, 401)
        self.assertFalse(resp.get_json()['success'])
        # 带 key 恢复正常
        resp = self.client.post('/api/mp/game/feedback',
                                json={'openid': 'oA', 'title': '想要恋爱测试'},
                                headers={'X-Auth-Key': 'k1'})
        self.assertTrue(resp.get_json()['success'])

    # ---- 许愿 ----
    def test_feedback_ok_and_dedup(self):
        r1 = self._fb(category='love', detail='想测').get_json()
        self.assertTrue(r1['success'])
        self.assertIsInstance(r1['id'], int)
        # 同日同 title 重复提交 → 幂等,返回原 id
        r2 = self._fb(category='love', detail='换个说法再发一次').get_json()
        self.assertTrue(r2['success'])
        self.assertEqual(r2['id'], r1['id'])

    def test_feedback_daily_limit(self):
        for i in range(5):
            r = self._fb(title=f'愿望{i}号').get_json()
            self.assertTrue(r['success'], f'第{i + 1}条应成功: {r}')
        r6 = self._fb(title='第六条愿望').get_json()
        self.assertFalse(r6['success'])
        self.assertIn('次数', r6['error'])

    def test_feedback_validation(self):
        self.assertFalse(self._fb(title='').get_json()['success'])            # 缺 title
        self.assertFalse(self._fb(title='x' * 31).get_json()['success'])      # 超长
        self.assertFalse(self._fb(detail='x' * 201).get_json()['success'])    # 详情超长
        r = self._fb(category='hack', detail='').get_json()                   # 非法分类落 other
        self.assertTrue(r['success'])
        with sqlite3.connect(self.db_file) as conn:
            cat = conn.execute("SELECT category FROM test_feedback WHERE id = ?",
                               (r['id'],)).fetchone()[0]
        self.assertEqual(cat, 'other')

    # ---- 注入攻击实弹(字段会回显后台/采纳后展示给用户,入库前必须拦) ----
    def test_feedback_rejects_xss_and_sqli(self):
        if m._sec_checker is None:
            self.skipTest('Jarvis 未安装,注入检测降级中')
        with m._db() as conn:   # 先触发建表(载荷全被拦时 _db 不会被走到)
            pass
        payloads = [
            '<script>alert(1)</script>',
            '<img src=x onerror=alert(document.cookie)>',
            '<svg onload=alert(1)>',
            "javascript:alert(1)",
            "' OR '1'='1' --",
            "1; DROP TABLE test_feedback",
            '%3Cscript%3Ealert(1)%3C/script%3E',   # URL 编码变形(Jarvis 内部会解码)
        ]
        for i, p in enumerate(payloads):
            r = self._fb(title=f'愿望标题{i}', detail=p).get_json()
            self.assertFalse(r['success'], f'detail 注入未拦截: {p!r} → {r}')
            r2 = self._fb(title=p, detail='正常内容').get_json()
            self.assertFalse(r2['success'], f'title 注入未拦截: {p!r} → {r2}')
        # 库里不该有任何载荷痕迹
        with sqlite3.connect(self.db_file) as conn:
            n = conn.execute("SELECT COUNT(*) FROM test_feedback").fetchone()[0]
        self.assertEqual(n, 0)

    def test_draft_rejects_xss(self):
        if m._sec_checker is None:
            self.skipTest('Jarvis 未安装,注入检测降级中')
        with m._db() as conn:   # 先触发建表
            pass
        body = _draft_body()
        body['questions'][0]['opts'][0] = '<script>alert("xss")</script>'
        r = self.client.post('/api/mp/game/draft', json=body).get_json()
        self.assertFalse(r['success'], f'draft 选项注入未拦截: {r}')
        body2 = _draft_body()
        body2['results'][0]['desc'] = '<iframe src="javascript:alert(1)">'
        r2 = self.client.post('/api/mp/game/draft', json=body2).get_json()
        self.assertFalse(r2['success'], f'draft 结果描述注入未拦截: {r2}')
        with sqlite3.connect(self.db_file) as conn:
            n = conn.execute("SELECT COUNT(*) FROM test_draft").fetchone()[0]
        self.assertEqual(n, 0)

    # ---- 投稿 ----
    def test_draft_ok_and_structure(self):
        r = self._draft().get_json()
        self.assertTrue(r['success'], r)
        with sqlite3.connect(self.db_file) as conn:
            q, res = conn.execute("SELECT questions, results FROM test_draft WHERE id = ?",
                                  (r['id'],)).fetchone()
        self.assertEqual(json.loads(q)[0]['opts'], ['选项0', '选项1', '选项2'])
        self.assertEqual(json.loads(res)[0]['name'], '结果人格0')

    def test_draft_validation(self):
        cases = [
            dict(title='短'),                 # <4字
            dict(title='x' * 21),             # >20字
            dict(n_q=2),                      # 题目不足
            dict(n_q=11),                     # 题目超限
            dict(n_opts=1),                   # 选项不足
            dict(n_opts=5),                   # 选项超限
            dict(n_r=2),                      # 结果不足
            dict(n_r=5),                      # 结果超限
        ]
        for kw in cases:
            r = self._draft(**kw).get_json()
            self.assertFalse(r['success'], f'应拒绝: {kw} → {r}')
            self.assertTrue(r['error'])

    def test_draft_daily_limit(self):
        for i in range(3):
            r = self._draft(title=f'投稿标题第{i}篇').get_json()
            self.assertTrue(r['success'], f'第{i + 1}篇应成功: {r}')
        r4 = self._draft(title='投稿标题第四篇').get_json()
        self.assertFalse(r4['success'])
        self.assertIn('次数', r4['error'])

    # ---- 采纳奖励下发 ----
    def test_reward_issued_once(self):
        rid = self._draft().get_json()['id']
        # 人工采纳(后台只改 status)
        with sqlite3.connect(self.db_file) as conn:
            conn.execute('UPDATE test_draft SET status = 1 WHERE id = ?', (rid,))
        # 首次对账 → 返回 reward_until 并置 reward_given=1
        body = self.client.get('/api/mp/sec/vpay/status?openid=oDRAFT').get_json()
        self.assertIn('reward_until', body)
        self.assertIsInstance(body['reward_until'], int)
        self.assertGreater(body['reward_until'], 0)
        # 第二次对账 → 不再返回(防重复发放)
        body2 = self.client.get('/api/mp/sec/vpay/status?openid=oDRAFT').get_json()
        self.assertNotIn('reward_until', body2)
        with sqlite3.connect(self.db_file) as conn:
            flag = conn.execute('SELECT reward_given FROM test_draft WHERE id = ?',
                                (rid,)).fetchone()[0]
        self.assertEqual(flag, 1)
        # 未采纳用户 → 不返回 reward_until
        body3 = self.client.get('/api/mp/sec/vpay/status?openid=oNOBODY').get_json()
        self.assertNotIn('reward_until', body3)

    def test_reward_tolerates_missing_table(self):
        # 全新部署:game 接口从未被调过,test_draft 表不存在 → 不报错、无奖励字段
        body = self.client.get('/api/mp/sec/vpay/status?openid=oANY').get_json()
        self.assertTrue(body['success'])
        self.assertNotIn('reward_until', body)


class AdminReviewTestCase(FeedbackDraftTestCase):
    """后台审核闭环:admin 列表/审核 → 奖励自动到账 → 用户侧 mine 查询。"""

    def setUp(self):
        super().setUp()
        from routes.mp_admin_routes import mp_admin_bp
        app = Flask(__name__)
        app.secret_key = 'test'
        app.register_blueprint(mp_admin_bp)
        app.register_blueprint(m.mp_game_bp)
        app.register_blueprint(v.mp_vpay_bp)
        self.client = app.test_client()

    def _login(self):
        with self.client.session_transaction() as s:
            s['stockrank_user'] = 'vk'

    def test_admin_requires_session(self):
        r = self.client.get('/api/mp-admin/feedback').get_json()
        self.assertFalse(r['success'])
        self.assertEqual(self.client.get('/api/mp-admin/feedback').status_code, 401)

    def test_review_flow_end_to_end(self):
        self._login()
        # 提交许愿 + 投稿(走用户接口)
        fid = self._fb(openid='oA', title='想要情侣合盘测试').get_json()['id']
        did = self._draft(openid='oA').get_json()['id']
        # admin 列表:许愿字段齐全、投稿题库已解析
        fb = self.client.get('/api/mp-admin/feedback').get_json()
        self.assertTrue(fb['success'])
        row = fb['data']['items'][0]
        self.assertEqual((row['title'], row['category'], row['status']), ('想要情侣合盘测试', 'other', 0))
        dr = self.client.get('/api/mp-admin/draft').get_json()
        drow = dr['data']['items'][0]
        self.assertEqual(len(drow['questions']), 3)
        self.assertEqual(drow['questions'][0]['opts'], ['选项0', '选项1', '选项2'])
        self.assertFalse(drow['reward_given'])
        # 状态过滤
        fb1 = self.client.get('/api/mp-admin/feedback?status=1').get_json()
        self.assertEqual(fb1['data']['total'], 0)
        # 非法 status 拒绝
        self.assertEqual(
            self.client.post('/api/mp-admin/feedback/update',
                             json={'id': fid, 'status': 9}).status_code, 400)
        # 审核许愿:采纳
        r = self.client.post('/api/mp-admin/feedback/update',
                             json={'id': fid, 'status': 1}).get_json()
        self.assertTrue(r['success'])
        self.assertEqual(self.client.get('/api/mp-admin/feedback?status=1').get_json()['data']['total'], 1)
        # 审核投稿:采纳 → 用户冷启动对账 → 奖励自动到账一次
        self.assertTrue(self.client.post('/api/mp-admin/draft/update',
                                         json={'id': did, 'status': 1}).get_json()['success'])
        body = self.client.get('/api/mp/sec/vpay/status?openid=oA').get_json()
        self.assertIn('reward_until', body)
        body2 = self.client.get('/api/mp/sec/vpay/status?openid=oA').get_json()
        self.assertNotIn('reward_until', body2)   # 防重复发放
        # 用户侧 mine:状态与奖励同步可见
        mine_fb = self.client.get('/api/mp/game/feedback/mine?openid=oA').get_json()
        self.assertEqual(mine_fb['items'][0]['status_name'], '已采纳')
        mine_dr = self.client.get('/api/mp/game/draft/mine?openid=oA').get_json()
        self.assertEqual(mine_dr['items'][0]['status_name'], '已采纳')
        self.assertTrue(mine_dr['items'][0]['reward_given'])

    def test_mine_lists_and_validation(self):
        self._fb(openid='oB', title='愿望一')
        self._fb(openid='oB', title='愿望二')
        self._draft(openid='oB')
        mine = self.client.get('/api/mp/game/feedback/mine?openid=oB').get_json()
        self.assertTrue(mine['success'])
        self.assertEqual(len(mine['items']), 2)
        self.assertEqual(mine['items'][0]['title'], '愿望二')   # 倒序
        self.assertEqual(mine['items'][0]['status_name'], '待处理')
        mine_d = self.client.get('/api/mp/game/draft/mine?openid=oB').get_json()
        self.assertEqual(mine_d['items'][0]['status_name'], '审核中')
        self.assertFalse(mine_d['items'][0]['reward_given'])
        # 校验:openid 非法 / limit 越界钳制
        self.assertFalse(self.client.get('/api/mp/game/feedback/mine?openid=bad openid').get_json()['success'])
        self.assertTrue(self.client.get('/api/mp/game/draft/mine?openid=oB&limit=999').get_json()['success'])


if __name__ == '__main__':
    unittest.main()