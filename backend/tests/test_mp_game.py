# -*- coding: utf-8 -*-
"""游戏化接口测试:排行榜校验/upsert/排名 + PK房间全生命周期 + 鉴权/限频。"""
import json
import os
import tempfile
import unittest

from flask import Flask

from routes import mp_game_routes as m
from routes import mp_sec_routes as sec


class GameTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        m.DB_FILE = os.path.join(tmp, 'game.db')
        m._rl_store.clear()
        m._rank_cache.clear()
        m._nick_ok_cache.clear()
        m._last_purge = 0.0
        m._stat_dedup.clear()
        m._stat_cache.clear()
        # auth_key 置空 → 免鉴权专注业务;鉴权单独测
        sec.MP_SEC_CONFIG_FILE = os.path.join(tmp, 'sec.json')
        with open(sec.MP_SEC_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({'auth_key': ''}, f)

        app = Flask(__name__)
        app.register_blueprint(m.mp_game_bp)
        self.client = app.test_client()
        # mock msgSecCheck:默认通过
        self.sec_ok = True

        def fake_wx(path, payload):
            if path == '/wxa/msg_sec_check':
                return {'errcode': 0, 'result': {'suggest': 'pass' if self.sec_ok else 'risky',
                                                 'label': 100}}
            return {'errcode': 0}
        m._call_wx_api = fake_wx

    # ---- 便捷提交 ----
    def _score(self, openid='oA', quiz='q1', score=80, full=100, dur=60000, count=20,
               answers='A' * 20, nickname=None):
        body = {'quiz_id': quiz, 'openid': openid, 'score': score, 'full_score': full,
                'duration_ms': dur, 'answer_count': count}
        if answers is not None:
            body['answers'] = answers
        if nickname is not None:
            body['nickname'] = nickname
        return self.client.post('/api/mp/game/score', json=body)

    def _rank(self, openid, quiz='q1'):
        return self.client.get(f'/api/mp/game/rank?quiz_id={quiz}&openid={openid}').get_json()

    def _create(self, openid='oA1', quiz='pk', count=None):
        body = {'openid': openid, 'quiz_id': quiz}
        if count is not None:
            body['answer_count'] = count
        return self.client.post('/api/mp/game/room', json=body).get_json()

    def _join(self, code, openid):
        return self.client.post('/api/mp/game/room/join',
                                json={'room_code': code, 'openid': openid}).get_json()

    def _answer(self, code, openid, answers):
        return self.client.post('/api/mp/game/room/answer',
                                json={'room_code': code, 'openid': openid,
                                      'answers': answers, 'answer_count': len(answers)}).get_json()

    def _status(self, code, openid):
        return self.client.get(f'/api/mp/game/room/status?room_code={code}&openid={openid}').get_json()

    def _room_row(self, code):
        with m._db() as conn:
            return conn.execute('SELECT * FROM rooms WHERE room_code = ?', (code,)).fetchone()


class ScoreValidationTests(GameTestCase):
    def test_ok(self):
        r = self._score().get_json()
        self.assertTrue(r['success'])
        self.assertEqual(r['message'], '已记录')

    def test_score_above_full_rejected(self):
        r = self._score(score=101).get_json()
        self.assertFalse(r['success'])

    def test_full_score_over_1000_rejected(self):
        r = self._score(score=100, full=1001, answers='A' * 20).get_json()
        self.assertFalse(r['success'])

    def test_too_fast_rejected(self):
        r = self._score(dur=20 * 800 - 1).get_json()
        self.assertFalse(r['success'])
        self.assertIn('时长', r['message'])

    def test_answers_mismatch_ignored_but_score_kept(self):
        self._score(answers='ABC')  # 长度不符 → 忽略 answers,成绩照收
        row = None
        with m._db() as conn:
            row = conn.execute("SELECT * FROM scores WHERE openid='oA'").fetchone()
        self.assertEqual(row['score'], 80)
        self.assertIsNone(row['answers'])

    def test_nickname_too_long_falls_back_default(self):
        self._score(nickname='超' * 13)
        with m._db() as conn:
            row = conn.execute("SELECT nickname FROM scores WHERE openid='oA'").fetchone()
        self.assertEqual(row['nickname'], '匿名测试者')

    def test_nickname_sec_fail_falls_back_default(self):
        self.sec_ok = False
        self._score(nickname='坏名字')
        with m._db() as conn:
            row = conn.execute("SELECT nickname FROM scores WHERE openid='oA'").fetchone()
        self.assertEqual(row['nickname'], '匿名测试者')

    def test_nickname_ok_kept(self):
        self._score(nickname='小可爱')
        with m._db() as conn:
            row = conn.execute("SELECT nickname FROM scores WHERE openid='oA'").fetchone()
        self.assertEqual(row['nickname'], '小可爱')

    def test_upsert_keeps_best_only(self):
        self._score(openid='oA', score=80, dur=60000)
        self._score(openid='oA', score=70, dur=10000)   # 更低分 → 忽略
        r = self._rank('oA')
        self.assertEqual(r['mine']['score'], 80)
        self._score(openid='oA', score=80, dur=30000)   # 同分更快 → 覆盖
        r = self._rank('oA')
        self.assertEqual(r['mine']['score'], 80)
        top_dur = r['top'][0]['duration_ms']
        self.assertEqual(top_dur, 30000)

    def test_rate_limit_6_per_minute(self):
        for i in range(6):
            self.assertTrue(self._score(openid=f'lim{i == 0 and "x" or "x"}').get_json()['success'])
        # 第7次:同一 openid
        ok = 0
        for i in range(7):
            if self._score(openid='same').get_json()['success']:
                ok += 1
        self.assertEqual(ok, 6)


class RankTests(GameTestCase):
    def test_rank_beat_top(self):
        # 三人:oB 90分50秒(第1) oA 90分60秒(第2) oC 80分(第3)
        self._score(openid='oA', score=90, dur=60000)
        self._score(openid='oB', score=90, dur=50000)
        self._score(openid='oC', score=80, dur=70000)
        r = self._rank('oA')
        self.assertEqual(r['total'], 3)
        self.assertTrue(r['mine']['found'])
        self.assertEqual(r['mine']['rank'], 2)          # 同分但 oB 用时更短
        self.assertEqual(r['mine']['beat_percent'], 33.3)  # 严格小于90的只有 oC
        self.assertEqual(len(r['top']), 3)
        self.assertEqual(r['top'][0]['duration_ms'], 50000)  # 同分按时长排
        r_b = self._rank('oB')
        self.assertEqual(r_b['mine']['rank'], 1)
        r_c = self._rank('oC')
        self.assertEqual(r_c['mine']['rank'], 3)
        self.assertEqual(r_c['mine']['beat_percent'], 0.0)

    def test_not_found(self):
        self._score(openid='oA', score=90, dur=60000)
        r = self._rank('nobody')
        self.assertFalse(r['mine']['found'])
        self.assertEqual(r['total'], 1)

    def test_top_never_leaks_openid(self):
        self._score(openid='oSECRET', score=90, dur=60000, nickname='小明')
        r = self._rank('oA')
        for item in r['top']:
            self.assertTrue(set(item.keys()) <= {'nickname', 'score', 'duration_ms'})

    def test_new_score_invalidates_cache(self):
        self._score(openid='oA', score=90, dur=60000)
        self.assertEqual(self._rank('oA')['total'], 1)
        self._score(openid='oB', score=80, dur=60000)
        self.assertEqual(self._rank('oA')['total'], 2)  # 上报后缓存失效


class RoomFlowTests(GameTestCase):
    def test_full_pk_flow(self):
        created = self._create(openid='oA1', count=4)
        self.assertTrue(created['success'])
        code = created['room_code']
        self.assertTrue(code.isdigit() and len(code) == 4)
        self.assertEqual(created['expires_in'], 86400)

        # A 轮询:等待中
        st = self._status(code, 'oA1')
        self.assertEqual(st['state'], 'waiting')
        self.assertEqual(st['players'], 1)
        self.assertFalse(st['i_submitted'])

        # B 加入 → ready
        joined = self._join(code, 'oB1')
        self.assertTrue(joined['success'])
        self.assertEqual(joined['state'], 'ready')

        # A 先交卷:未齐
        r1 = self._answer(code, 'oA1', 'ABCD')
        self.assertTrue(r1['success'])
        self.assertFalse(r1['both_done'])
        self.assertNotEqual(r1['state'], 'finished')
        self.assertTrue(self._status(code, 'oA1')['i_submitted'])

        # B 交卷:ABCD vs ABAD → 3/4 = 75
        r2 = self._answer(code, 'oB1', 'ABAD')
        self.assertTrue(r2['success'])
        self.assertTrue(r2['both_done'])
        self.assertEqual(r2['state'], 'finished')
        self.assertEqual(self._status(code, 'oB1')['match_percent'], 75)

        # 逐题对照:A 视角 mine=A侧, theirs=B侧
        d = self.client.get(f'/api/mp/game/room/detail?room_code={code}&openid=oA1').get_json()
        self.assertEqual(d['match_percent'], 75)
        self.assertEqual(len(d['detail']), 4)
        self.assertEqual(d['detail'][1], {'q': 2, 'same': True, 'mine': 'B', 'theirs': 'B'})
        self.assertEqual(d['detail'][2], {'q': 3, 'same': False, 'mine': 'C', 'theirs': 'A'})
        # B 视角互换
        d2 = self.client.get(f'/api/mp/game/room/detail?room_code={code}&openid=oB1').get_json()
        self.assertEqual(d2['detail'][2]['mine'], 'A')
        self.assertEqual(d2['detail'][2]['theirs'], 'C')
        self.assertTrue(d2['detail'][0]['same'])

    def test_join_rules(self):
        code = self._create(openid='oA2')['room_code']
        self.assertEqual(self._join(code, 'oA2')['message'], '不能和自己 PK 哦')
        self.assertTrue(self._join(code, 'oB2')['success'])
        self.assertEqual(self._join(code, 'oC2')['message'], '房间已满')
        again = self._join(code, 'oB2')  # 幂等
        self.assertTrue(again['success'])
        self.assertEqual(again['state'], 'ready')

    def test_answer_rules(self):
        code = self._create(openid='oA3', count=4)['room_code']
        self._join(code, 'oB3')
        # 旁观者
        self.assertEqual(self._answer(code, 'oX', 'ABCD')['message'], '你不在该房间中')
        # 题数不符(房间存了 answer_count=4)
        self.assertIn('题目数', self._answer(code, 'oA3', 'ABC')['message'])
        # 房间不存在
        self.assertEqual(self._answer('9999', 'oA3', 'ABCD')['message'], '房间不存在或已过期')

    def test_answer_length_fallback_without_stored_count(self):
        # 创建时不带 answer_count:与对方已交答案长度比对
        code = self._create(openid='oA4')['room_code']
        self._join(code, 'oB4')
        self.assertTrue(self._answer(code, 'oA4', 'AB')['success'])
        self.assertEqual(self._answer(code, 'oB4', 'ABC')['message'], '双方题数不一致')
        r = self._answer(code, 'oB4', 'AB')
        self.assertTrue(r['success'])
        self.assertEqual(r['state'], 'finished')
        self.assertEqual(self._status(code, 'oA4')['match_percent'], 100)

    def test_detail_before_finished(self):
        code = self._create(openid='oA5')['room_code']
        self._join(code, 'oB5')
        d = self.client.get(f'/api/mp/game/room/detail?room_code={code}&openid=oA5').get_json()
        self.assertFalse(d['success'])
        self.assertEqual(d['message'], '对方还没交卷')

    def test_expired_room_treated_as_gone(self):
        code = self._create(openid='oA6')['room_code']
        with m._db() as conn:
            conn.execute("UPDATE rooms SET expires_at = '2000-01-01 00:00:00' WHERE room_code = ?",
                         (code,))
        st = self._status(code, 'oA6')
        self.assertEqual(st['message'], '房间不存在或已过期')
        self.assertIsNone(self._room_row(code))  # 顺手删掉


class StatTests(GameTestCase):
    """参与计数:不去重(产品要求)、10秒防脚本窗口、批量查询默认0。"""

    def _inc(self, key='test_caiyun', openid='oA'):
        r = self.client.post('/api/mp/game/stat/inc',
                             json={'key': key, 'openid': openid})
        return r.status_code, r.get_json()

    def _query(self, keys):
        r = self.client.get(f'/api/mp/game/stat?keys={keys}')
        return r.get_json()

    def test_inc_counts_up(self):
        _, b1 = self._inc()
        _, b2 = self._inc(openid='oB')  # 不同人:正常+1(不去重)
        self.assertTrue(b1['success'])
        self.assertEqual(b1['count'], 1)
        self.assertEqual(b2['count'], 2)
        q = self._query('test_caiyun')
        self.assertEqual(q['counts']['test_caiyun'], 2)

    def test_same_openid_within_10s_swallowed(self):
        _, b1 = self._inc(openid='oA')
        _, b2 = self._inc(openid='oA')  # 10秒内同openid+key:只计1次
        self.assertEqual(b1['count'], 1)
        self.assertTrue(b2['success'])
        self.assertEqual(b2['count'], 1)  # 未自增
        _, b3 = self._inc(openid='oC')
        self.assertEqual(b3['count'], 2)

    def test_invalid_key_rejected(self):
        for bad in ('Test-1', 'test caiyun', 'x' * 65, '', '测试'):
            code, body = self._inc(key=bad)
            self.assertFalse(body['success'], msg=bad)
            self.assertEqual(body.get('error'), 'key 格式不合法' if bad else '参数不完整')

    def test_missing_params(self):
        code, body = self._inc(key='')  # openid有key为空
        self.assertEqual(body.get('error'), '参数不完整')
        r = self.client.post('/api/mp/game/stat/inc', json={'key': 'test_x'})
        self.assertEqual(r.get_json().get('error'), '参数不完整')

    def test_query_missing_key_returns_zero(self):
        q = self._query('test_sbti,test_tianfu')
        self.assertTrue(q['success'])
        self.assertEqual(q['counts'], {'test_sbti': 0, 'test_tianfu': 0})

    def test_query_truncates_to_20_keys(self):
        keys = ','.join(f'test_k{i}' for i in range(25))
        q = self._query(keys)
        self.assertEqual(len(q['counts']), 20)

    def test_inc_invalidates_cache(self):
        self._inc(openid='oA')                     # count=1
        self.assertEqual(self._query('test_caiyun')['counts']['test_caiyun'], 1)  # 进缓存
        self._inc(openid='oB')                     # count=2,缓存失效
        self.assertEqual(self._query('test_caiyun')['counts']['test_caiyun'], 2)

    def test_mixed_case_key_counts_normally(self):
        # 回归:驼峰 key(test_careerFit)曾被 ^[a-z0-9_]+$ 拒绝 → 新测试永远不+1
        code, b1 = self._inc(key='test_careerFit')
        self.assertEqual(code, 200)
        self.assertTrue(b1['success'])
        self.assertEqual(b1['count'], 1)
        # 大小写归一为同一计数器:小写写法继续累加
        _, b2 = self._inc(key='test_careerfit', openid='oB')
        self.assertEqual(b2['count'], 2)

    def test_query_mixed_case_key_echoes_original_name(self):
        # 回归:未测过的驼峰 key 曾被静默过滤 → counts:{};规范要求按原名返回 0
        q = self._query('test_careerFit')
        self.assertTrue(q['success'])
        self.assertEqual(q['counts'], {'test_careerFit': 0})
        self._inc(key='test_careerFit')
        self.assertEqual(self._query('test_careerFit')['counts'], {'test_careerFit': 1})
        # 换小写问同一个计数器,也拿得到
        self.assertEqual(self._query('test_careerfit')['counts'], {'test_careerfit': 1})

    def test_query_dedup_after_normalization(self):
        # 同 key 不同大小写只算一个,首个写法为准
        q = self._query('test_X,test_x')
        self.assertEqual(q['counts'], {'test_X': 0})


class AuthGuardTests(GameTestCase):
    def test_auth_key_enforced(self):
        with open(sec.MP_SEC_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({'auth_key': 'k1'}, f)
        r = self.client.post('/api/mp/game/score',
                             json={'quiz_id': 'q', 'openid': 'oA', 'score': 1, 'full_score': 10,
                                   'duration_ms': 60000, 'answer_count': 5, 'answers': 'AAAAA'})
        self.assertEqual(r.status_code, 401)
        r2 = self.client.post('/api/mp/game/score',
                              json={'quiz_id': 'q', 'openid': 'oA', 'score': 1, 'full_score': 10,
                                    'duration_ms': 60000, 'answer_count': 5, 'answers': 'AAAAA'},
                              headers={'X-Auth-Key': 'k1'})
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.get_json()['success'])


if __name__ == '__main__':
    unittest.main()
