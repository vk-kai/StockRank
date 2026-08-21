# -*- coding: utf-8 -*-
"""小程序数据后台管理接口测试:鉴权(仅vk登录)、趋势聚合、成绩/计数/房间增删改查。"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from flask import Flask

from routes import mp_admin_routes as a
from routes import mp_game_routes as m
from routes import mp_sec_routes as sec


def _utcnow_str():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


class MpAdminTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        m.DB_FILE = os.path.join(tmp, 'game.db')
        m._rl_store.clear()
        m._rank_cache.clear()
        m._stat_cache.clear()
        m._stat_dedup.clear()
        m._nick_ok_cache.clear()
        m._last_purge = 0.0
        # 写操作密码校验打桩:测试密码固定 'pw',避免远程取北京时间
        a.verify_password = lambda p: p == 'pw'
        # 游戏接口 auth_key 置空(集成测试用)
        sec.MP_SEC_CONFIG_FILE = os.path.join(tmp, 'sec.json')
        with open(sec.MP_SEC_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({'auth_key': ''}, f)

        app = Flask(__name__)
        app.secret_key = 'test'
        app.register_blueprint(a.mp_admin_bp)
        app.register_blueprint(m.mp_game_bp)
        self.client = app.test_client()

    def _login(self):
        with self.client.session_transaction() as s:
            s['stockrank_user'] = 'vk'

    def _add_score(self, quiz='test_a', openid='oA', nickname='甲', score=80,
                   full=100, dur=60000):
        with m._db() as conn:
            conn.execute('''INSERT INTO scores
                (quiz_id, openid, nickname, score, full_score, duration_ms, answers, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (quiz, openid, nickname, score, full, dur, None, _utcnow_str()))


class AuthTests(MpAdminTestCase):
    def test_no_session_401(self):
        for url in ('/api/mp-admin/overview', '/api/mp-admin/scores',
                    '/api/mp-admin/stats', '/api/mp-admin/rooms'):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 401, msg=url)
        r = self.client.post('/api/mp-admin/scores/delete', json={'password': 'pw'})
        self.assertEqual(r.status_code, 401)

    def test_write_ops_require_password(self):
        self._login()
        r = self.client.post('/api/mp-admin/scores/update',
                             json={'quiz_id': 'q', 'openid': 'o', 'nickname': 'x'})
        self.assertEqual(r.status_code, 401)  # 密码错误
        r2 = self.client.post('/api/mp-admin/stats/save', json={'key': 'k', 'count': 1})
        self.assertEqual(r2.status_code, 401)


class OverviewTests(MpAdminTestCase):
    def test_overview_shape_and_totals(self):
        self._login()
        self._add_score(quiz='test_a', openid='oA', score=80)
        self._add_score(quiz='test_b', openid='oB', score=90)
        with m._db() as conn:
            conn.execute("INSERT INTO stats(key, count) VALUES ('test_a', 5)")
            conn.execute("INSERT INTO rooms(room_code, quiz_id, openid_a, state, expires_at, created_at)"
                         " VALUES ('1234', 'pk', 'oA', 'finished', '2099-01-01 00:00:00', ?)",
                         (_utcnow_str(),))
        r = self.client.get('/api/mp-admin/overview').get_json()
        self.assertTrue(r['success'])
        d = r['data']
        self.assertEqual(d['totals']['players'], 2)
        self.assertEqual(d['totals']['quizzes'], 2)
        self.assertEqual(d['totals']['scores'], 2)
        self.assertEqual(d['totals']['tests'], 5)
        self.assertEqual(d['totals']['rooms'], 1)
        self.assertEqual(d['totals']['rooms_finished'], 1)
        self.assertEqual(d['stat_counts'], [{'key': 'test_a', 'count': 5}])
        # 近30天:今天应有 2 条新增成绩、1 个房间
        self.assertEqual(len(d['daily']['days']), 30)
        self.assertEqual(d['daily']['scores'][-1], 2)
        self.assertEqual(d['daily']['rooms'][-1], 1)
        self.assertEqual(sum(d['daily']['scores']), 2)
        # 热度排行:两测试并列,人数对
        by_quiz = {q['quiz_id']: q['players'] for q in d['quiz_top']}
        self.assertEqual(by_quiz, {'test_a': 1, 'test_b': 1})

    def test_stat_inc_feeds_daily_trend(self):
        # 集成:小程序计数接口真实+1后,趋势图当天人次应增加
        self._login()
        base = self.client.get('/api/mp-admin/overview').get_json()['data']['daily']['tests'][-1]
        rv = self.client.post('/api/mp/game/stat/inc',
                              json={'key': 'test_careerFit', 'openid': 'oZ'})
        self.assertTrue(rv.get_json()['success'])
        after = self.client.get('/api/mp-admin/overview').get_json()['data']['daily']['tests'][-1]
        self.assertEqual(after, base + 1)


class ScoresTests(MpAdminTestCase):
    def test_list_pagination_and_filter(self):
        self._login()
        for i in range(25):
            self._add_score(quiz='test_a', openid=f'o{i:02d}')
        self._add_score(quiz='test_b', openid='oXX')
        r = self.client.get('/api/mp-admin/scores').get_json()
        self.assertEqual(r['data']['total'], 26)
        self.assertEqual(len(r['data']['items']), 20)
        self.assertEqual(r['data']['total_pages'], 2)
        r2 = self.client.get('/api/mp-admin/scores?quiz_id=test_b').get_json()
        self.assertEqual(r2['data']['total'], 1)
        self.assertEqual(r2['data']['items'][0]['quiz_id'], 'test_b')
        # 昵称为空时回退默认昵称
        with m._db() as conn:
            conn.execute('UPDATE scores SET nickname = NULL WHERE openid = ?', ('oXX',))
        r3 = self.client.get('/api/mp-admin/scores?quiz_id=test_b').get_json()
        self.assertEqual(r3['data']['items'][0]['nickname'], '匿名测试者')

    def test_update_and_delete(self):
        self._login()
        self._add_score(quiz='test_a', openid='oA', score=80)
        r = self.client.post('/api/mp-admin/scores/update', json={
            'password': 'pw', 'quiz_id': 'test_a', 'openid': 'oA',
            'nickname': '新名', 'score': 95, 'duration_ms': 30000,
        }).get_json()
        self.assertTrue(r['success'])
        with m._db() as conn:
            row = conn.execute("SELECT * FROM scores WHERE openid='oA'").fetchone()
        self.assertEqual(row['nickname'], '新名')
        self.assertEqual(row['score'], 95)
        self.assertEqual(row['duration_ms'], 30000)
        # 非法输入
        bad = self.client.post('/api/mp-admin/scores/update', json={
            'password': 'pw', 'quiz_id': 'test_a', 'openid': 'oA', 'score': -1})
        self.assertEqual(bad.status_code, 400)
        # 删除 + 404
        r2 = self.client.post('/api/mp-admin/scores/delete', json={
            'password': 'pw', 'quiz_id': 'test_a', 'openid': 'oA'}).get_json()
        self.assertTrue(r2['success'])
        r3 = self.client.post('/api/mp-admin/scores/delete', json={
            'password': 'pw', 'quiz_id': 'test_a', 'openid': 'oA'})
        self.assertEqual(r3.status_code, 404)


class StatsTests(MpAdminTestCase):
    def test_list_save_delete(self):
        self._login()
        with m._db() as conn:
            conn.execute("INSERT INTO stats(key, count) VALUES ('test_a', 3)")
        r = self.client.get('/api/mp-admin/stats').get_json()
        self.assertEqual(r['data']['total'], 1)
        self.assertEqual(r['data']['items'][0]['key'], 'test_a')
        # 新增(驼峰自动归一) + 缓存失效
        self.client.get('/api/mp/game/stat?keys=test_new')  # 0 进缓存
        r2 = self.client.post('/api/mp-admin/stats/save',
                              json={'password': 'pw', 'key': 'Test_New', 'count': 7}).get_json()
        self.assertTrue(r2['success'])
        q = self.client.get('/api/mp/game/stat?keys=test_new').get_json()
        self.assertEqual(q['counts']['test_new'], 7)
        # 非法
        bad = self.client.post('/api/mp-admin/stats/save',
                               json={'password': 'pw', 'key': '坏key', 'count': 1})
        self.assertEqual(bad.status_code, 400)
        # 删除
        r3 = self.client.post('/api/mp-admin/stats/delete',
                              json={'password': 'pw', 'key': 'test_new'}).get_json()
        self.assertTrue(r3['success'])
        q2 = self.client.get('/api/mp/game/stat?keys=test_new').get_json()
        self.assertEqual(q2['counts']['test_new'], 0)
        r4 = self.client.post('/api/mp-admin/stats/delete',
                              json={'password': 'pw', 'key': 'test_new'})
        self.assertEqual(r4.status_code, 404)


class RoomsTests(MpAdminTestCase):
    def test_list_and_delete(self):
        self._login()
        with m._db() as conn:
            conn.execute('''INSERT INTO rooms
                (room_code, quiz_id, openid_a, answers_a, openid_b, answers_b, state,
                 answer_count, match_percent, expires_at, created_at)
                VALUES ('1234', 'pk', 'oA', 'AB', 'oB', 'AC', 'finished', 2, 50,
                        '2099-01-01 00:00:00', ?)''', (_utcnow_str(),))
        r = self.client.get('/api/mp-admin/rooms').get_json()
        self.assertEqual(r['data']['total'], 1)
        item = r['data']['items'][0]
        self.assertEqual(item['players'], 2)
        self.assertTrue(item['a_submitted'] and item['b_submitted'])
        self.assertEqual(item['match_percent'], 50)
        # 按状态过滤
        r2 = self.client.get('/api/mp-admin/rooms?state=waiting').get_json()
        self.assertEqual(r2['data']['total'], 0)
        # 删除
        r3 = self.client.post('/api/mp-admin/rooms/delete',
                              json={'password': 'pw', 'room_code': '1234'}).get_json()
        self.assertTrue(r3['success'])
        r4 = self.client.post('/api/mp-admin/rooms/delete',
                              json={'password': 'pw', 'room_code': '1234'})
        self.assertEqual(r4.status_code, 404)


if __name__ == '__main__':
    unittest.main()
