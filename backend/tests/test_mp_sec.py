# -*- coding: utf-8 -*-
"""小程序内容安全代理接口测试:token缓存/重试、鉴权、签名、结果闭环。"""
import hashlib
import json
import os
import tempfile
import unittest

from flask import Flask

from routes import mp_sec_routes as m


class MpSecTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # 重定向数据/配置落盘位置,隔离真实文件
        m.TOKEN_FILE = os.path.join(self.tmp, 'token.json')
        m.RESULTS_FILE = os.path.join(self.tmp, 'results.json')
        m.MEDIA_DIR = os.path.join(self.tmp, 'media')
        m.MP_SEC_CONFIG_FILE = os.path.join(self.tmp, 'mp_sec_config.json')
        m._TOKEN_CACHE.update(token=None, expires_at=0.0)
        with open(m.MP_SEC_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({'appid': 'wx1234', 'appsecret': 'secret',
                       'push_token': 'tok123', 'auth_key': 'key123',
                       'media_base_url': 'https://example.com'}, f)

        app = Flask(__name__)
        app.register_blueprint(m.mp_sec_bp)
        self.client = app.test_client()

        # mock 微信HTTP
        self._wx_calls = []
        m._wx_post_json = self._fake_post
        m._wx_get_json = self._fake_get
        self.post_responses = []
        self.get_responses = []

    def _fake_post(self, url, params, payload, timeout=10):
        self._wx_calls.append(('POST', url, params, payload))
        return self.post_responses.pop(0) if self.post_responses else {}

    def _fake_get(self, url, params, timeout=10):
        self._wx_calls.append(('GET', url, params, None))
        return self.get_responses.pop(0) if self.get_responses else {}

    def _sign(self, timestamp='1700000000', nonce='n1', token='tok123'):
        return hashlib.sha1(''.join(sorted([token, timestamp, nonce])).encode()).hexdigest()


class AuthKeyTests(MpSecTestCase):
    def test_missing_auth_key_rejected(self):
        resp = self.client.post('/api/mp/sec/msg-check',
                                json={'openid': 'oX', 'content': 'hi'})
        self.assertEqual(resp.status_code, 401)

    def test_body_auth_key_accepted(self):
        self.post_responses.append({'access_token': 'T1', 'expires_in': 7200})
        self.post_responses.append({'errcode': 0, 'result': {'suggest': 'pass', 'label': 100}})
        resp = self.client.post('/api/mp/sec/msg-check',
                                json={'openid': 'oX', 'content': 'hi', 'auth_key': 'key123'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()['safe'])

    def test_header_auth_key_accepted(self):
        self.post_responses.append({'access_token': 'T1', 'expires_in': 7200})
        self.post_responses.append({'errcode': 0, 'result': {'suggest': 'pass', 'label': 100}})
        resp = self.client.post('/api/mp/sec/msg-check', json={'openid': 'oX', 'content': 'hi'},
                                headers={'X-Auth-Key': 'key123'})
        self.assertEqual(resp.status_code, 200)


class TokenTests(MpSecTestCase):
    def _auth_headers(self):
        return {'X-Auth-Key': 'key123'}

    def test_token_cached_across_calls(self):
        self.post_responses.append({'access_token': 'T1', 'expires_in': 7200})
        self.assertEqual(m.get_access_token(), 'T1')
        # 第二次直接走内存缓存,不再发token请求
        self.post_responses.append({'errcode': 0, 'result': {'suggest': 'pass', 'label': 100}})
        self.client.post('/api/mp/sec/msg-check', json={'openid': 'oX', 'content': 'x'},
                         headers=self._auth_headers())
        token_calls = [c for c in self._wx_calls if 'stable_token' in c[1]]
        self.assertEqual(len(token_calls), 1)
        check_calls = [c for c in self._wx_calls if 'msg_sec_check' in c[1]]
        self.assertEqual(check_calls[0][2]['access_token'], 'T1')

    def test_token_restored_from_file(self):
        # 模拟重启:内存缓存清空,但文件缓存仍在
        m._save_token_file('TFILE', 9999999999.0)
        m._TOKEN_CACHE.update(token=None, expires_at=0.0)
        self.assertEqual(m.get_access_token(), 'TFILE')

    def test_invalid_credential_forces_refresh_and_retry(self):
        self.post_responses.append({'access_token': 'T1', 'expires_in': 7200})
        self.post_responses.append({'errcode': 40001, 'errmsg': 'invalid credential'})
        self.post_responses.append({'access_token': 'T2', 'expires_in': 7200})
        self.post_responses.append({'errcode': 0, 'result': {'suggest': 'risky', 'label': 20002}})
        resp = self.client.post('/api/mp/sec/msg-check', json={'openid': 'oX', 'content': 'x'},
                                headers=self._auth_headers())
        body = resp.get_json()
        self.assertTrue(body['success'])
        self.assertFalse(body['safe'])
        self.assertEqual(body['label_name'], '色情')


class MsgCheckTests(MpSecTestCase):
    def _ok_token(self):
        self.post_responses.append({'access_token': 'T1', 'expires_in': 7200})

    def test_review_not_safe(self):
        self._ok_token()
        self.post_responses.append({'errcode': 0, 'result': {'suggest': 'review', 'label': 21000}})
        resp = self.client.post('/api/mp/sec/msg-check',
                                json={'openid': 'oX', 'content': 'x', 'auth_key': 'key123'})
        body = resp.get_json()
        self.assertFalse(body['safe'])
        self.assertEqual(body['suggest'], 'review')

    def test_missing_openid(self):
        resp = self.client.post('/api/mp/sec/msg-check',
                                json={'content': 'x', 'auth_key': 'key123'})
        self.assertEqual(resp.status_code, 400)

    def test_wechat_error_passed_through(self):
        self._ok_token()
        self.post_responses.append({'errcode': 61010, 'errmsg': 'code is expired'})
        resp = self.client.post('/api/mp/sec/msg-check',
                                json={'openid': 'oX', 'content': 'x', 'auth_key': 'key123'})
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.get_json()['errcode'], 61010)


class MediaCheckFlowTests(MpSecTestCase):
    """送检 → checking → callback推送 → 查询结果 的完整闭环。"""

    def _headers(self):
        return {'X-Auth-Key': 'key123'}

    def test_full_flow(self):
        # 1) 送检
        self.post_responses.append({'access_token': 'T1', 'expires_in': 7200})
        self.post_responses.append({'errcode': 0, 'errmsg': 'ok', 'trace_id': 'tr-1'})
        resp = self.client.post('/api/mp/sec/media-check',
                                json={'openid': 'oX', 'media_url': 'https://x/1.png',
                                      'auth_key': 'key123'})
        body = resp.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(body['trace_id'], 'tr-1')
        # 请求体断言:2.0版参数齐全
        send_payload = [c for c in self._wx_calls if 'media_check_async' in c[1]][-1][3]
        self.assertEqual(send_payload['version'], 2)
        self.assertEqual(send_payload['media_type'], 2)  # .png 自动识别为图片
        self.assertEqual(send_payload['scene'], 2)

        # 2) 未推送前查询 = checking
        resp = self.client.get('/api/mp/sec/media-result?trace_id=tr-1', headers=self._headers())
        self.assertEqual(resp.get_json()['status'], 'checking')

        # 3) 微信推送结果(带签名)
        push = {'Event': 'wxa_media_check', 'trace_id': 'tr-1', 'errcode': 0,
                'result': {'suggest': 'pass', 'label': 100},
                'detail': [{'strategy': 'content_model', 'errcode': 0,
                            'suggest': 'pass', 'label': 100, 'prob': 99}]}
        resp = self.client.post(
            f'/api/mp/sec/callback?signature={self._sign()}&timestamp=1700000000&nonce=n1',
            json=push)
        self.assertEqual(resp.data, b'success')

        # 4) 再查询 = pass
        resp = self.client.get('/api/mp/sec/media-result?trace_id=tr-1', headers=self._headers())
        body = resp.get_json()
        self.assertEqual(body['status'], 'pass')
        self.assertEqual(body['label_name'], '正常')

    def test_risky_result_flow(self):
        self.post_responses.append({'access_token': 'T1', 'expires_in': 7200})
        self.post_responses.append({'errcode': 0, 'trace_id': 'tr-2'})
        self.client.post('/api/mp/sec/media-check',
                         json={'openid': 'oX', 'media_url': 'https://x/a.mp3',
                               'auth_key': 'key123'})
        push = {'Event': 'wxa_media_check', 'trace_id': 'tr-2', 'errcode': 0,
                'result': {'suggest': 'risky', 'label': 20002}}
        self.client.post(
            f'/api/mp/sec/callback?signature={self._sign()}&timestamp=1700000000&nonce=n1',
            json=push)
        resp = self.client.get('/api/mp/sec/media-result?trace_id=tr-2', headers=self._headers())
        self.assertEqual(resp.get_json()['status'], 'risky')

    def test_callback_bad_signature_rejected(self):
        resp = self.client.post(
            '/api/mp/sec/callback?signature=bad&timestamp=1700000000&nonce=n1',
            json={'Event': 'wxa_media_check', 'trace_id': 'tr-3', 'errcode': 0,
                  'result': {'suggest': 'pass', 'label': 100}})
        self.assertEqual(resp.status_code, 403)


class CallbackVerifyTests(MpSecTestCase):
    def test_echostr_ok(self):
        resp = self.client.get(
            f'/api/mp/sec/callback?signature={self._sign()}&timestamp=1700000000&nonce=n1&echostr=ABC123')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, b'ABC123')

    def test_echostr_bad_signature(self):
        resp = self.client.get(
            '/api/mp/sec/callback?signature=bad&timestamp=1700000000&nonce=n1&echostr=ABC')
        self.assertEqual(resp.status_code, 403)


class LoginProxyTests(MpSecTestCase):
    def test_code2session(self):
        # 微信返回里有 session_key,但接口绝不能透传给前端(合规检测硬性要求)
        self.get_responses.append({'openid': 'oABC', 'session_key': 'sk'})
        resp = self.client.post('/api/mp/sec/login',
                                json={'code': 'jscode', 'auth_key': 'key123'})
        body = resp.get_json()
        self.assertTrue(body['success'])
        self.assertEqual(body['openid'], 'oABC')
        self.assertNotIn('session_key', body)

    def test_login_without_code(self):
        resp = self.client.post('/api/mp/sec/login', json={'auth_key': 'key123'})
        self.assertEqual(resp.status_code, 400)


if __name__ == '__main__':
    unittest.main()
