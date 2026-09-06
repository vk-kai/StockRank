# -*- coding: utf-8 -*-
"""游戏化接口测试:排行榜校验/upsert/排名 + PK房间全生命周期 + 鉴权/限频。"""
import json
import os
import tempfile
import time
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
        m._overall_cache['ts'] = 0.0
        m._overall_cache['board'] = None
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
        # 每题至少0.5秒:20题下限10000ms,9999仍被拦(防脚本连发)
        r = self._score(dur=20 * 500 - 1).get_json()
        self.assertFalse(r['success'])
        self.assertIn('时长', r['message'])

    def test_fast_but_real_passes(self):
        # 客户端实测场景:10题5秒(每题0.5秒)曾因旧规则(每题0.8秒)被误杀,现应入库
        r = self._score(dur=5000, count=10, answers='A' * 10).get_json()
        self.assertTrue(r['success'])
        # 整体绝对下限1秒:10题999ms仍拦
        r2 = self._score(openid='oB', dur=999, count=10, answers='A' * 10).get_json()
        self.assertFalse(r2['success'])

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

    def test_rename_updates_nickname_even_with_lower_score(self):
        # 改名需求:低分重交也要更新昵称(分数仍只记最佳)
        self._score(openid='oA', score=85, dur=60000, nickname='旧名字')
        self._score(openid='oA', score=1, dur=60000, nickname='新名字')
        with m._db() as conn:
            row = conn.execute("SELECT nickname, score FROM scores WHERE openid='oA'").fetchone()
        self.assertEqual(row['nickname'], '新名字')   # 昵称已更新
        self.assertEqual(row['score'], 85)            # 成绩仍是最佳
        # 响应回带入库昵称,客户端可感知
        r = self._score(openid='oA', score=2, dur=60000, nickname='新名字').get_json()
        self.assertEqual(r.get('nickname'), '新名字')

    def test_sec_fail_keeps_existing_nickname(self):
        # 检测服务故障回退默认昵称时,不冲掉库中已过检的昵称
        self._score(openid='oA', score=80, dur=60000, nickname='好名字')
        self.sec_ok = False
        self._score(openid='oA', score=90, dur=60000, nickname='另一个名字')
        with m._db() as conn:
            row = conn.execute("SELECT nickname, score FROM scores WHERE openid='oA'").fetchone()
        self.assertEqual(row['nickname'], '好名字')   # 保留旧昵称
        self.assertEqual(row['score'], 90)            # 成绩照常更新

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
        # 玩家侧当不存在,但行保留7天给后台看漏斗,不立即删
        self.assertIsNotNone(self._room_row(code))
        # 超过保留期才会被懒清理真正删除
        m._purge_expired_rooms(force=True)
        self.assertIsNone(self._room_row(code))


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

    def test_inc_with_name_persists_last_wins(self):
        # 小程序带 name 上报:KV 存储,后写覆盖先写,供后台展示中文名
        self.client.post('/api/mp/game/stat/inc',
                         json={'key': 'test_mbti', 'openid': 'oA', 'name': '第一次的名字'})
        with m._db() as conn:
            row = conn.execute("SELECT name FROM stat_names WHERE key='test_mbti'").fetchone()
        self.assertEqual(row['name'], '第一次的名字')
        # 10秒窗口外不同人再报 → 覆盖;顺带校验 stat_log 带 openid
        m._stat_dedup.clear()
        self.client.post('/api/mp/game/stat/inc',
                         json={'key': 'test_mbti', 'openid': 'oB', 'name': 'MBTI人格测试'})
        with m._db() as conn:
            row = conn.execute("SELECT name FROM stat_names WHERE key='test_mbti'").fetchone()
            logs = conn.execute("SELECT openid FROM stat_log WHERE key='test_mbti'").fetchall()
        self.assertEqual(row['name'], 'MBTI人格测试')
        self.assertEqual(sorted(r['openid'] for r in logs), ['oA', 'oB'])


class OverallRankTests(GameTestCase):
    """综合排名:avg_beat=各测试击败率均值、3测试门槛、同分多测优先、缓存失效。"""

    def _overall(self, openid):
        return self.client.get(f'/api/mp/game/rank/overall?openid={openid}').get_json()

    def test_avg_beat_and_threshold(self):
        # o1/o2 各3个测试上榜;o5 只有2个 → found=false 带 quizzes 数
        self._score(openid='o1', quiz='quizA', score=90)
        self._score(openid='o2', quiz='quizA', score=80)
        self._score(openid='o3', quiz='quizA', score=70)
        self._score(openid='o4', quiz='quizA', score=60)
        self._score(openid='o1', quiz='quizB', score=50)
        self._score(openid='o2', quiz='quizB', score=60)
        self._score(openid='o5', quiz='quizB', score=70)
        self._score(openid='o1', quiz='quizC', score=100)
        self._score(openid='o2', quiz='quizC', score=90)
        self._score(openid='o5', quiz='quizC', score=80)
        r = self._overall('o1')
        self.assertTrue(r['success'])
        self.assertEqual(r['total'], 2)                 # 只有 o1/o2 达3个测试
        mine = r['mine']
        self.assertTrue(mine['found'])
        self.assertEqual(mine['rank'], 1)
        self.assertEqual(mine['quizzes'], 3)
        self.assertAlmostEqual(mine['avg_beat'], 47.2)  # (75 + 0 + 66.67)/3
        # best=击败率最高的测试:quizA(击败3/4,榜内第1);同分按时长的名次规则与 /rank 一致
        self.assertEqual(mine['best'], {'quiz_id': 'quizA', 'rank': 1, 'score': 90})
        self.assertEqual(set(r['top'][0].keys()), {'rank', 'nickname', 'avg_beat', 'quizzes'})
        self.assertEqual(r['top'][0]['rank'], 1)
        self.assertEqual(r['top'][0]['quizzes'], 3)
        self.assertEqual(r['top'][1]['avg_beat'], 38.9)  # (50+33.33+33.33)/3
        # 未达门槛:found=false 且带 quizzes 数,前端可算「再测 N 个解锁」
        r5 = self._overall('o5')
        self.assertFalse(r5['mine']['found'])
        self.assertEqual(r5['mine']['quizzes'], 2)
        # 完全没成绩的 openid
        r6 = self._overall('nobody')
        self.assertFalse(r6['mine']['found'])
        self.assertEqual(r6['mine']['quizzes'], 0)

    def test_tie_more_quizzes_first(self):
        # u1/u2 avg_beat 同为50.0:u2 参与5个测试 > u1 的3个 → u2 在前
        for quiz, seeds in (
            ('q1', (('u1', 90), ('u2', 80), ('u3', 70))),
            ('q2', (('u1', 80), ('u2', 90), ('u3', 70))),
            ('q3', (('u2', 80), ('u3', 90), ('u4', 100), ('u5', 70))),
            ('q4', (('u2', 90), ('u3', 80), ('u4', 70), ('u5', 60))),
            ('q5', (('u2', 80), ('u3', 90), ('u4', 70), ('u5', 60))),
            ('q6', (('u1', 90), ('u3', 100), ('u4', 80), ('u5', 70))),
        ):
            for openid, score in seeds:
                self._score(openid=openid, quiz=quiz, score=score)
        r2 = self._overall('u2')   # beats: 33.3+66.7+25+75+50 → avg 50.0, 5个测试
        self.assertTrue(r2['mine']['found'])
        self.assertEqual(r2['mine']['rank'], 1)
        self.assertEqual(r2['mine']['quizzes'], 5)
        self.assertEqual(r2['mine']['avg_beat'], 50.0)
        r1 = self._overall('u1')   # beats: 66.7+33.3+50 → avg 50.0, 3个测试
        self.assertTrue(r1['mine']['found'])
        self.assertEqual(r1['mine']['rank'], 2)
        self.assertEqual(r1['mine']['quizzes'], 3)
        self.assertEqual(r1['mine']['avg_beat'], 50.0)
        self.assertEqual(r2['total'], 5)                # u1..u5 全部≥3个测试
        self.assertEqual(r2['top'][0]['avg_beat'], 50.0)
        self.assertEqual(r2['top'][1]['avg_beat'], 50.0)

    def test_top10_limit(self):
        # 11人×3测试,分数递增:最高分 u11 第1;最低分 u01 在榜(total)但不在 top10
        for k in range(1, 12):
            for quiz in ('x1', 'x2', 'x3'):
                self._score(openid=f'u{k:02d}', quiz=quiz, score=k * 8)
        r11 = self._overall('u11')
        self.assertEqual(r11['total'], 11)
        self.assertEqual(len(r11['top']), 10)
        self.assertEqual(r11['top'][0]['rank'], 1)
        self.assertEqual(r11['top'][0]['avg_beat'], 90.9)  # 10/11 击败率
        self.assertEqual(r11['mine']['rank'], 1)
        # 三张榜并列最佳,取 quiz_id 最小的稳定结果
        self.assertEqual(r11['mine']['best']['quiz_id'], 'x1')
        self.assertEqual(r11['mine']['best']['rank'], 1)
        r01 = self._overall('u01')                         # 榜上第11名,超出 top10
        self.assertEqual(r01['mine']['rank'], 11)
        self.assertEqual(r01['mine']['quizzes'], 3)
        self.assertEqual(r01['mine']['avg_beat'], 0.0)

    def test_new_score_invalidates_overall_cache(self):
        for quiz in ('a1', 'a2', 'a3'):
            self._score(openid='o1', quiz=quiz, score=80)
            self._score(openid='o2', quiz=quiz, score=70)
        self.assertEqual(self._overall('o1')['total'], 2)
        # o5 原本只有2个测试 → 补第3个,上报后立即生效(缓存已被主动失效)
        for quiz in ('a1', 'a2'):
            self._score(openid='o5', quiz=quiz, score=90)
        self.assertFalse(self._overall('o5')['mine']['found'])
        self._score(openid='o5', quiz='a3', score=90)
        r2 = self._overall('o5')
        self.assertTrue(r2['mine']['found'])
        self.assertEqual(r2['total'], 3)
        self.assertEqual(r2['mine']['rank'], 1)          # 每个测试都击败所有人
        self.assertAlmostEqual(r2['mine']['avg_beat'], 66.7)  # 每榜击败 2/3

    def test_missing_or_bad_openid(self):
        r = self.client.get('/api/mp/game/rank/overall').get_json()
        self.assertFalse(r['success'])
        r2 = self.client.get('/api/mp/game/rank/overall?openid=坏key').get_json()
        self.assertFalse(r2['success'])


class EchoWallTests(GameTestCase):
    """弹幕墙:服务端强制复检、7天窗口、ts倒序、限频、openid 不出列表。"""

    def _check(self, suggest='pass', errcode=0):
        # 打桩服务端复检(echo 走 m 命名空间里的 _do_msg_sec_check 绑定)
        m._do_msg_sec_check = lambda openid, content, scene=1: {
            'errcode': errcode, 'result': {'suggest': suggest, 'label': 100}}

    def _post(self, openid='oA', wall='20260906', text='今天也在努力', nickname=None):
        body = {'openid': openid, 'wall_id': wall, 'text': text}
        if nickname is not None:
            body['nickname'] = nickname
        return self.client.post('/api/mp/game/echo', json=body).get_json()

    def _list(self, wall='20260906', limit=None):
        url = f'/api/mp/game/echo?wall_id={wall}' + (f'&limit={limit}' if limit else '')
        return self.client.get(url).get_json()

    def test_post_and_list_roundtrip(self):
        self._check()
        r = self._post(nickname='小明')
        self.assertTrue(r['success'])
        self.assertIsInstance(r['id'], int)
        self._post(openid='oB', text='我也是')
        lst = self._list()['list']
        self.assertEqual([x['text'] for x in lst], ['我也是', '今天也在努力'])  # 新的在前
        first = lst[1]
        self.assertEqual(first['nickname'], '小明')
        self.assertEqual(first['hugs'], 0)
        self.assertIsInstance(first['ts'], int)
        for item in lst:  # openid 绝不随列表下发
            self.assertTrue(set(item.keys()) <= {'id', 'text', 'nickname', 'hugs', 'ts'})
        # wall_id 隔离:另一面墙看不到
        self._post(openid='oC', wall='20260907', text='明天的墙')
        self.assertEqual(len(self._list(wall='20260907')['list']), 1)
        self.assertEqual(len(self._list()['list']), 2)

    def test_risky_text_rejected_not_stored(self):
        # 87014 老违规码已在 sec 层 _do_msg_sec_check 归一为 suggest=risky
        # (见 test_mp_sec 的 87014 用例),echo 只需处理归一化后的 risky
        self._check(suggest='risky')
        r = self._post()
        self.assertFalse(r['success'])
        self.assertEqual(r['message'], '内容含违规信息')
        self.assertEqual(self._list()['list'], [])

    def test_check_service_down_rejected(self):
        # 检测服务故障:fail-closed 拒绝入库,但提示语与「内容违规」区分开
        def boom(openid, content, scene=1):
            raise RuntimeError('wx down')
        m._do_msg_sec_check = boom
        r = self._post()
        self.assertFalse(r['success'])
        self.assertIn('稍后再试', r['message'])
        self.assertEqual(self._list()['list'], [])

    def test_text_limits(self):
        self._check()
        self.assertFalse(self._post(text='')['success'])          # 空
        self.assertFalse(self._post(text='长' * 51)['success'])   # 超50字
        self.assertTrue(self._post(text='刚' * 50)['success'])    # 恰好50字

    def test_attack_text_rejected_locally(self):
        # 注入防护先拦:复检 mock 成 pass 仍拒(留言回显给所有访问者)
        self._check()
        r = self._post(text='<img src=x onerror=alert(1)>')
        self.assertFalse(r['success'])
        self.assertEqual(r['message'], '内容含违规信息')

    def test_bad_params(self):
        self._check()
        self.assertFalse(self._post(wall='')['success'])
        self.assertFalse(self._post(wall='wall/2026')['success'])
        self.assertFalse(self._post(openid='<script>')['success'])
        self.assertFalse(self._list(wall='')['success'])
        self.assertFalse(self._list(wall='bad wall')['success'])

    def test_seven_day_window(self):
        self._check()
        self._post(text='新留言')
        with m._db() as conn:
            conn.execute('UPDATE echo_wall SET ts = ? WHERE text = ?',
                         (int(time.time()) - 8 * 86400, '新留言'))
        self.assertEqual(self._list()['list'], [])   # 8天前的不返回

    def test_limit_clamped_and_order(self):
        self._check()
        for i in range(3):
            self._post(openid=f'o{i}', text=f'留言{i}')
        lst = self._list(limit=2)['list']
        self.assertEqual([x['text'] for x in lst], ['留言2', '留言1'])  # ts倒序
        self.assertTrue(self._list(limit=0)['success'])    # 0 → 默认50
        self.assertTrue(self._list(limit=999)['success'])  # 999 → 钳到100

    def test_nickname_fallback(self):
        self._check()
        self.sec_ok = False    # 昵称送检失败(setUp 的 fake)→ 回退默认昵称,留言照发
        self._post(nickname='坏名字', text='正文没问题')
        item = self._list()['list'][0]
        self.assertEqual(item['nickname'], '匿名测试者')

    def test_rate_limit_10_per_minute(self):
        self._check()
        ok = 0
        for i in range(12):
            if self._post(text=f'第{i}条')['success']:
                ok += 1
        self.assertEqual(ok, 10)


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
