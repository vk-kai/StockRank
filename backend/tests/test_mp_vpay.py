# -*- coding: utf-8 -*-
"""小程序虚拟支付测试:签名一致性、下单参数、发货/退款推送幂等、兜底查单、权益状态。"""
import os
import re
import json
import hmac
import hashlib
import tempfile
import unittest
from datetime import datetime

from flask import Flask

from routes import mp_vpay_routes as m
from routes import mp_sec_routes as sec


class VpayTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # 隔离落盘:虚拟支付DB/配置、内容安全配置(push_token/auth_key 置空跳过验签)
        m.VPAY_DB_FILE = os.path.join(self.tmp, 'mp_vpay.db')
        m.VPAY_CONFIG_FILE = os.path.join(self.tmp, 'mp_vpay_config.json')
        self._write_vpay_config({'app_key': 'test_app_key', 'offer_id': '1450640154',
                                 'product_id': 'adfree_test', 'product_name': '去广告终身卡',
                                 'goods_price': 600, 'env': 0})
        sec.MP_SEC_CONFIG_FILE = os.path.join(self.tmp, 'mp_sec_config.json')
        with open(sec.MP_SEC_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({'appid': 'wx1234', 'appsecret': 'secret',
                       'push_token': '', 'auth_key': ''}, f)

        app = Flask(__name__)
        app.register_blueprint(m.mp_vpay_bp)
        self.client = app.test_client()

        # mock 微信HTTP
        self.get_responses = []
        self.vpay_responses = []
        self.vpay_posts = []
        m._wx_get_json = self._fake_get
        m._vpay_post = self._fake_vpay_post
        m.get_access_token = lambda force=False: 'T'

    def _write_vpay_config(self, cfg):
        with open(m.VPAY_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f)

    def _fake_get(self, url, params, timeout=10):
        return self.get_responses.pop(0) if self.get_responses else {}

    def _fake_vpay_post(self, path, params, body_str, timeout=10):
        self.vpay_posts.append((path, params, body_str))
        return self.vpay_responses.pop(0) if self.vpay_responses else {}

    def _mk_order(self, out_trade_no='VPTEST1', openid='oBUYER', status='pending'):
        with m._db() as conn:
            conn.execute('''INSERT INTO vpay_orders(out_trade_no, openid, product_id, quantity,
                            goods_price, env, attach, status, created_at)
                            VALUES (?, ?, 'adfree_test', 1, 600, 0, ?, ?, ?)''',
                         (out_trade_no, openid, out_trade_no, status,
                          datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

    def _order(self, out_trade_no='VPTEST1'):
        with m._db() as conn:
            row = conn.execute('SELECT * FROM vpay_orders WHERE out_trade_no = ?',
                               (out_trade_no,)).fetchone()
            return dict(row) if row else None

    def _ent(self, openid='oBUYER'):
        with m._db() as conn:
            row = conn.execute('SELECT * FROM vpay_entitlements WHERE openid = ?',
                               (openid,)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def _deliver_xml(out_trade_no='VPTEST1', wx='WX1', openid='oBUYER'):
        return (f'<xml><FromUserName>{openid}</FromUserName>'
                f'<Event>xpay_goods_deliver_notify</Event><OpenId>{openid}</OpenId>'
                f'<OutTradeNo>{out_trade_no}</OutTradeNo>'
                f'<WeChatPayInfo><MchOrderNo>{wx}</MchOrderNo></WeChatPayInfo>'
                f'<GoodsInfo><ProductId>adfree_test</ProductId><Quantity>1</Quantity></GoodsInfo>'
                f'</xml>')

    @staticmethod
    def _refund_xml(wx='WX1', openid='oBUYER'):
        return (f'<xml><FromUserName>{openid}</FromUserName>'
                f'<Event>xpay_refund_notify</Event><OpenId>{openid}</OpenId>'
                f'<WeChatPayInfo><MchOrderNo>{wx}</MchOrderNo></WeChatPayInfo></xml>')


class SignTests(VpayTestCase):
    def test_out_trade_no_format(self):
        no = m.gen_out_trade_no()
        self.assertRegex(no, r'^VP\d{14}\d{6}$')
        self.assertTrue(8 <= len(no) <= 32)

    def test_pay_sig_algorithm(self):
        body = '{"openid":"oX","env":0,"order_id":"VP1"}'
        expect = hmac.new(b'test_app_key', b'/xpay/query_order&' + body.encode(),
                          hashlib.sha256).hexdigest()
        self.assertEqual(m.calc_pay_sig('/xpay/query_order', body, 'test_app_key'), expect)

    def test_signature_algorithm(self):
        expect = hmac.new(b'sk1', b'signDataStr', hashlib.sha256).hexdigest()
        self.assertEqual(m.calc_signature('signDataStr', 'sk1'), expect)


class ParamsTests(VpayTestCase):
    def test_missing_code_rejected(self):
        resp = self.client.post('/api/mp/sec/vpay/params', json={})
        self.assertEqual(resp.status_code, 400)

    def test_missing_app_key_rejected(self):
        self._write_vpay_config({'offer_id': 'x', 'product_id': 'p',
                                 'goods_price': 600, 'env': 0})
        resp = self.client.post('/api/mp/sec/vpay/params', json={'code': 'c1'})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()['errcode'], 50010)

    def test_params_success_and_order_pending(self):
        self.get_responses.append({'openid': 'oBUYER', 'session_key': 'sk1'})
        resp = self.client.post('/api/mp/sec/vpay/params', json={'code': 'c1'})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertFalse(body['already_owned'])

        pay = body['pay_data']
        self.assertEqual(pay['mode'], 'short_series_goods')
        sign = json.loads(pay['signData'])
        # signData 字段与顺序对齐官方示例
        self.assertEqual(list(sign.keys()),
                         ['offerId', 'buyQuantity', 'env', 'currencyType',
                          'productId', 'goodsPrice', 'outTradeNo', 'attach'])
        self.assertEqual(sign['offerId'], '1450640154')
        self.assertEqual(sign['buyQuantity'], 1)
        self.assertEqual(sign['env'], 0)
        self.assertEqual(sign['currencyType'], 'CNY')
        self.assertEqual(sign['productId'], 'adfree_test')
        self.assertEqual(sign['goodsPrice'], 600)
        self.assertEqual(sign['outTradeNo'], body['out_trade_no'])
        # 双签名可复算一致
        self.assertEqual(pay['paySig'],
                         m.calc_pay_sig('requestVirtualPayment', pay['signData'], 'test_app_key'))
        self.assertEqual(pay['signature'], m.calc_signature(pay['signData'], 'sk1'))
        # 订单落库 pending
        order = self._order(body['out_trade_no'])
        self.assertEqual(order['status'], 'pending')
        self.assertEqual(order['openid'], 'oBUYER')

    def test_already_owned_no_paydata(self):
        self.get_responses.append({'openid': 'oBUYER', 'session_key': 'sk1'})
        with m._db() as conn:
            conn.execute('''INSERT INTO vpay_entitlements(openid, status, out_trade_no, wx_order_id,
                            granted_at, updated_at) VALUES ('oBUYER', 'active', 'VPOLD', 'WXOLD',
                            '2026-09-01 00:00:00', '2026-09-01 00:00:00')''')
        resp = self.client.post('/api/mp/sec/vpay/params', json={'code': 'c2'})
        body = resp.get_json()
        self.assertTrue(body['already_owned'])
        self.assertNotIn('pay_data', body)


class NotifyTests(VpayTestCase):
    def test_deliver_xml_grants_entitlement(self):
        self._mk_order()
        resp = self.client.post('/api/mp/sec/vpay/notify', data=self._deliver_xml(),
                                content_type='application/xml')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'<ErrCode>0</ErrCode>', resp.data)
        order = self._order()
        self.assertEqual(order['status'], 'delivered')
        self.assertEqual(order['wx_order_id'], 'WX1')
        ent = self._ent()
        self.assertEqual(ent['status'], 'active')
        self.assertEqual(ent['wx_order_id'], 'WX1')

    def test_deliver_idempotent_on_duplicate_push(self):
        self._mk_order()
        xml = self._deliver_xml()
        self.client.post('/api/mp/sec/vpay/notify', data=xml, content_type='application/xml')
        first = self._order()['delivered_at']
        self.client.post('/api/mp/sec/vpay/notify', data=xml, content_type='application/xml')
        self.assertEqual(self._order()['delivered_at'], first)
        with m._db() as conn:
            count = conn.execute('SELECT COUNT(*) c FROM vpay_entitlements').fetchone()['c']
        self.assertEqual(count, 1)

    def test_openid_mismatch_not_delivered(self):
        self._mk_order()
        resp = self.client.post('/api/mp/sec/vpay/notify',
                                data=self._deliver_xml(openid='oEVIL'),
                                content_type='application/xml')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._order()['status'], 'pending')
        self.assertIsNone(self._ent())

    def test_refund_revokes_entitlement(self):
        self._mk_order()
        self.client.post('/api/mp/sec/vpay/notify', data=self._deliver_xml(),
                         content_type='application/xml')
        resp = self.client.post('/api/mp/sec/vpay/notify', data=self._refund_xml(),
                                content_type='application/xml')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._order()['status'], 'refunded')
        self.assertEqual(self._ent()['status'], 'revoked')

    def test_refund_of_other_order_keeps_new_entitlement(self):
        # 用户退款旧单后重新购买(新权益来自 WX2):迟到/重复的旧单退款推送不得误伤新权益
        self._mk_order()
        self.client.post('/api/mp/sec/vpay/notify', data=self._deliver_xml(wx='WX1'),
                         content_type='application/xml')
        with m._db() as conn:  # 模拟重新购买后权益来源变为 WX2
            conn.execute('''UPDATE vpay_entitlements SET wx_order_id = 'WX2',
                            out_trade_no = 'VPTEST2' WHERE openid = 'oBUYER' ''')
        self.client.post('/api/mp/sec/vpay/notify', data=self._refund_xml(wx='WX1'),
                         content_type='application/xml')
        self.assertEqual(self._ent()['status'], 'active')

    def test_json_push_gets_json_response(self):
        self._mk_order()
        payload = {'Event': 'xpay_goods_deliver_notify', 'OpenId': 'oBUYER',
                   'OutTradeNo': 'VPTEST1',
                   'WeChatPayInfo': {'MchOrderNo': 'WXJ1'},
                   'GoodsInfo': {'ProductId': 'adfree_test', 'Quantity': 1}}
        resp = self.client.post('/api/mp/sec/vpay/notify', json=payload)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()['ErrCode'], 0)
        self.assertEqual(self._order()['wx_order_id'], 'WXJ1')

    def test_unknown_event_returns_zero(self):
        resp = self.client.post('/api/mp/sec/vpay/notify',
                                data='<xml><Event>xpay_other_notify</Event></xml>',
                                content_type='application/xml')
        self.assertIn(b'<ErrCode>0</ErrCode>', resp.data)


class StatusTests(VpayTestCase):
    def test_missing_openid_rejected(self):
        resp = self.client.get('/api/mp/sec/vpay/status')
        self.assertEqual(resp.status_code, 400)

    def test_status_before_and_after_grant(self):
        resp = self.client.get('/api/mp/sec/vpay/status?openid=oBUYER')
        self.assertFalse(resp.get_json()['ad_free'])
        self._mk_order()
        m._deliver_order('oBUYER', 'VPTEST1', 'WX1', 'adfree_test', 1, 0, 'push')
        resp = self.client.get('/api/mp/sec/vpay/status?openid=oBUYER')
        body = resp.get_json()
        self.assertTrue(body['ad_free'])
        self.assertEqual(body['entitlement']['wx_order_id'], 'WX1')
        self.assertEqual(body['last_order']['out_trade_no'], 'VPTEST1')
        self.assertEqual(body['product']['product_id'], 'adfree_test')


class PendingCheckTests(VpayTestCase):
    def test_no_app_key_skips(self):
        self._mk_order()
        self._write_vpay_config({'offer_id': 'x', 'product_id': 'p',
                                 'goods_price': 600, 'env': 0})
        self.assertEqual(m.check_pending_orders(), 0)
        self.assertEqual(self._order()['status'], 'pending')

    def test_paid_order_delivered_via_query(self):
        self._mk_order()
        self.vpay_responses.append(
            {'errcode': 0, 'order': {'status': 2, 'wx_order_id': 'WXQ1'}})
        m.check_pending_orders()
        order = self._order()
        self.assertEqual(order['status'], 'delivered')
        self.assertEqual(order['wx_order_id'], 'WXQ1')
        self.assertEqual(self._ent()['status'], 'active')
        # 查单请求:pay_sig 在 query,body 为紧凑 JSON
        path, params, body = self.vpay_posts[0]
        self.assertEqual(path, '/xpay/query_order')
        self.assertEqual(params['pay_sig'],
                         m.calc_pay_sig('/xpay/query_order', body, 'test_app_key'))
        self.assertEqual(json.loads(body),
                         {'openid': 'oBUYER', 'env': 0, 'order_id': 'VPTEST1'})

    def test_unpaid_order_stays_pending(self):
        self._mk_order()
        self.vpay_responses.append({'errcode': 0, 'order': {'status': 1}})
        m.check_pending_orders()
        order = self._order()
        self.assertEqual(order['status'], 'pending')
        self.assertIsNotNone(order['last_query_at'])

    def test_refunded_order_revoked_via_query(self):
        self._mk_order()
        m._deliver_order('oBUYER', 'VPTEST1', 'WX1', 'adfree_test', 1, 0, 'push')
        # 手动把订单放回 pending,模拟推送前查单即发现已退款
        with m._db() as conn:
            conn.execute("UPDATE vpay_orders SET status = 'pending' WHERE out_trade_no = 'VPTEST1'")
        self.vpay_responses.append(
            {'errcode': 0, 'order': {'status': 5, 'wx_order_id': 'WX1'}})
        m.check_pending_orders()
        self.assertEqual(self._order()['status'], 'refunded')
        self.assertEqual(self._ent()['status'], 'revoked')

    def test_closed_order_marked_closed(self):
        self._mk_order()
        self.vpay_responses.append(
            {'errcode': 0, 'order': {'status': 6, 'wx_order_id': 'WX1'}})
        m.check_pending_orders()
        self.assertEqual(self._order()['status'], 'closed')

    def test_query_error_keeps_pending(self):
        self._mk_order()
        self.vpay_responses.append({'errcode': 268490003, 'errmsg': '签名错误'})
        m.check_pending_orders()
        self.assertEqual(self._order()['status'], 'pending')


if __name__ == '__main__':
    unittest.main()
