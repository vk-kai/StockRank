# -*- coding: utf-8 -*-
"""小程序数据后台管理接口测试:鉴权(仅vk登录)、趋势聚合、成绩/计数/房间增删改查。"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

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
            conn.execute("INSERT INTO stats(key, count) VALUES ('tool_foodwheel', 2)")
            conn.execute("INSERT INTO rooms(room_code, quiz_id, openid_a, state, expires_at, created_at)"
                         " VALUES ('1234', 'pk', 'oA', 'finished', '2099-01-01 00:00:00', ?)",
                         (_utcnow_str(),))
        r = self.client.get('/api/mp-admin/overview').get_json()
        self.assertTrue(r['success'])
        d = r['data']
        # 口径:tests 只含 test_* 计数,tool_usage 只含 tool_*
        self.assertEqual(d['totals']['tests'], 5)
        self.assertEqual(d['totals']['tool_usage'], 2)
        self.assertEqual(d['totals']['players'], 2)
        self.assertEqual(d['totals']['quizzes'], 2)
        self.assertEqual(d['totals']['scores'], 2)
        self.assertEqual(d['totals']['rooms'], 1)
        self.assertEqual(d['totals']['rooms_finished'], 1)
        # 两榜拆分:测试榜/工具榜,带中文名(内置映射兜底,映射按小写key匹配)
        self.assertEqual(d['test_counts'],
                         [{'key': 'test_a', 'name': 'test_a', 'count': 5}])
        self.assertEqual(d['tool_counts'],
                         [{'key': 'tool_foodwheel', 'name': '吃什么转盘', 'count': 2}])
        # 近30天:今天应有 2 条新增成绩、1 个房间;无流水则计数趋势为0
        self.assertEqual(len(d['daily']['days']), 30)
        self.assertEqual(d['daily']['scores'][-1], 2)
        self.assertEqual(d['daily']['rooms'][-1], 1)
        self.assertEqual(sum(d['daily']['scores']), 2)
        self.assertEqual(sum(d['daily']['tests']), 0)
        self.assertEqual(sum(d['daily']['tools']), 0)
        # 热度排行:两测试并列,人数对;name 无映射时回退 quiz_id
        by_quiz = {q['quiz_id']: q['players'] for q in d['quiz_top']}
        self.assertEqual(by_quiz, {'test_a': 1, 'test_b': 1})
        for q in d['quiz_top']:
            self.assertEqual(q['name'], q['quiz_id'])

    def test_name_priority_stored_over_builtin(self):
        # 名称优先级:小程序上报的 name > 内置映射 > 原样 key
        self._login()
        self.client.post('/api/mp/game/stat/inc',
                         json={'key': 'test_mbti', 'openid': 'oA', 'name': '自定义名'})
        self.client.post('/api/mp/game/stat/inc',
                         json={'key': 'tool_foodWheel', 'openid': 'oB'})  # 无name→内置(驼峰自动归一小写)
        self.client.post('/api/mp/game/stat/inc',
                         json={'key': 'test_zzz', 'openid': 'oC'})          # 无映射→key
        r = self.client.get('/api/mp-admin/stats').get_json()
        names = {i['key']: i['name'] for i in r['data']['items']}
        self.assertEqual(names['test_mbti'], '自定义名')
        self.assertEqual(names['tool_foodwheel'], '吃什么转盘')
        self.assertEqual(names['test_zzz'], 'test_zzz')

    def test_stat_inc_feeds_daily_trend(self):
        # 集成:小程序计数接口真实+1后,趋势图当天人次应增加;工具key进工具曲线
        self._login()
        base_t = self.client.get('/api/mp-admin/overview').get_json()['data']['daily']['tests'][-1]
        base_g = self.client.get('/api/mp-admin/overview').get_json()['data']['daily']['tools'][-1]
        self.client.post('/api/mp/game/stat/inc',
                         json={'key': 'test_careerFit', 'openid': 'oZ'})
        self.client.post('/api/mp/game/stat/inc',
                         json={'key': 'tool_danmaku', 'openid': 'oZ'})
        d = self.client.get('/api/mp-admin/overview').get_json()['data']['daily']
        self.assertEqual(d['tests'][-1], base_t + 1)
        self.assertEqual(d['tools'][-1], base_g + 1)


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

    def test_expired_display_and_days_window(self):
        self._login()
        ten_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)) \
            .strftime('%Y-%m-%d %H:%M:%S')
        with m._db() as conn:
            # 10天前建的活跃房间:默认近7天不显示,days=0 显示
            conn.execute('''INSERT INTO rooms(room_code, quiz_id, openid_a, state, expires_at, created_at)
                VALUES ('1111', 'pk', 'oA', 'waiting', '2099-01-01 00:00:00', ?)''',
                (ten_days_ago,))
            # 已过期的房间:统一展示为 expired
            conn.execute('''INSERT INTO rooms(room_code, quiz_id, openid_a, state, expires_at, created_at)
                VALUES ('2222', 'pk', 'oB', 'waiting', '2000-01-01 00:00:00', ?)''',
                (_utcnow_str(),))
        default = self.client.get('/api/mp-admin/rooms').get_json()
        self.assertEqual(default['data']['total'], 1)  # 只有今天建的那个
        self.assertEqual(default['data']['items'][0]['room_code'], '2222')
        self.assertEqual(default['data']['items'][0]['state'], 'expired')
        all_days = self.client.get('/api/mp-admin/rooms?days=0').get_json()
        self.assertEqual(all_days['data']['total'], 2)


class CleanupTests(MpAdminTestCase):
    def test_cleanup_dev_data(self):
        self._login()
        with m._db() as conn:
            # 遗留 quiz + 联调 openid 的成绩
            for quiz, oid in (('selftest_tmp', 'oReal'), ('wealth', 'oReal'),
                              ('test_a', 'vkself001'), ('test_a', 'otest001'),
                              ('test_a', 'oReal')):
                conn.execute('''INSERT INTO scores(quiz_id, openid, nickname, score,
                    full_score, duration_ms, created_at) VALUES (?, ?, ?, 1, 100, 60000, ?)''',
                    (quiz, oid, 'n', _utcnow_str()))
            # 联调 openid 的房间
            conn.execute('''INSERT INTO rooms(room_code, quiz_id, openid_a, state, expires_at, created_at)
                VALUES ('9001', 'pk', 'vkself001', 'waiting', '2099-01-01 00:00:00', ?)''',
                (_utcnow_str(),))
            # 计数:test_a=10,探针=4;流水:联调贡献3次、真人贡献2次
            conn.execute("INSERT INTO stats(key, count) VALUES ('test_a', 10)")
            conn.execute("INSERT INTO stats(key, count) VALUES ('tool_probe_diag', 4)")
            for oid in ('vkself001', 'vkself002', 'otest001', 'oReal', 'oReal2'):
                conn.execute("INSERT INTO stat_log(key, ts, openid) VALUES ('test_a', ?, ?)",
                             (int(datetime.now(timezone.utc).timestamp()), oid))
            conn.execute("INSERT INTO stat_log(key, ts, openid) VALUES ('tool_probe_diag', 123, 'oReal')")
        r = self.client.post('/api/mp-admin/cleanup-dev-data',
                             json={'password': 'pw'}).get_json()
        self.assertTrue(r['success'])
        res = r['result']
        self.assertEqual(res['scores'], 4)            # selftest_tmp+wealth+vkself+otest
        self.assertEqual(res['rooms'], 1)
        self.assertEqual(res['log_rows'], 3)          # vkself×2 + otest×1
        self.assertEqual(res['decremented'], {'test_a': 3})
        self.assertTrue(res['probe_cleared'])
        with m._db() as conn:
            left_scores = conn.execute('SELECT COUNT(*) AS c FROM scores').fetchone()['c']
            left_logs = conn.execute('SELECT COUNT(*) AS c FROM stat_log').fetchone()['c']
            test_a = conn.execute("SELECT count FROM stats WHERE key='test_a'").fetchone()['count']
            probe = conn.execute("SELECT count FROM stats WHERE key='tool_probe_diag'").fetchone()['count']
        self.assertEqual(left_scores, 1)              # 只剩 oReal 的 test_a
        self.assertEqual(left_logs, 2)                # 真人的2条 + 探针日志已删
        self.assertEqual(test_a, 7)                   # 10 - 联调3次
        self.assertEqual(probe, 0)
        # 可重复执行:再跑一遍不报错、不再删东西
        r2 = self.client.post('/api/mp-admin/cleanup-dev-data',
                              json={'password': 'pw'}).get_json()
        self.assertTrue(r2['success'])
        self.assertEqual(r2['result']['scores'], 0)

    def test_cleanup_requires_password(self):
        self._login()
        r = self.client.post('/api/mp-admin/cleanup-dev-data', json={})
        self.assertEqual(r.status_code, 401)


if __name__ == '__main__':
    unittest.main()
