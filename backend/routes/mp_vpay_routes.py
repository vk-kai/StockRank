# -*- coding: utf-8 -*-
"""微信小程序虚拟支付(道具直购):「去广告终身卡」一次性买断。

官方文档:
  https://developers.weixin.qq.com/miniprogram/dev/platform-capabilities/business-capabilities/virtual-payment/person

  POST /api/mp/sec/vpay/params   下单:code 换 session_key → 生成 signData + paySig + signature,
                                 落一条 pending 订单,返回 payData 给 wx.requestVirtualPayment
  GET  /api/mp/sec/vpay/status   查询用户去广告权益(ad_free)与最近订单
  POST /api/mp/sec/vpay/notify   微信平台推送(xpay_goods_deliver_notify 发货 / xpay_refund_notify 退款),
                                 XML/JSON 均支持;幂等以平台单号 wx_order_id 为准

发货双路径:
  路径A 发货推送(主):平台推 Event=xpay_goods_deliver_notify,回 <xml><ErrCode>0</ErrCode></xml>
  路径B query_order 兜底:后台线程每 5 分钟扫描 pending 订单调 /xpay/query_order,已支付则补发货

环境变量:（无——AppKey 与环境均走配置文件,便于部署时直接替换）

配置文件(config/mp_vpay_config.json,仓库内为示例值,部署时替换为真实值):
  app_key       虚拟支付 AppKey(MP后台-虚拟支付-基本配置 的现网AppKey)【必填】
  offer_id      OfferID(支付账号,现网 1450640154)
  product_id    道具 ID(MP后台-虚拟支付-道具管理 里创建并发布,须与此一致)
  product_name  商品显示名(仅本服务端/前端展示用)
  goods_price   道具单价(分),必须与后台道具价格一致
  env           支付环境:1=沙箱(联调期用,不产生真实扣费) 0=正式

消息推送:MP后台【开发管理-消息推送】统一配置一个 URL(现为 /api/mp/sec/callback);
xpay_* 推送(XML 格式)在该处分流到本模块,本模块的 /notify 亦独立可用(便于单独配置)。

鉴权:params/status 走与内容安全代理相同的 auth_key(X-Auth-Key 头或 body 字段);
notify 是微信服务器调用,只做消息推送签名校验,不走 auth_key。

数据(data/mp_vpay.db):
  vpay_orders       订单:out_trade_no(业务单号 VP+时间+随机) / wx_order_id(平台单号,幂等键) / status
  vpay_entitlements 去广告权益:openid 唯一,status=active/revoked(退款撤销)
"""
import os
import json
import time
import hmac
import random
import sqlite3
import threading
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests
from flask import Blueprint, Response, jsonify, request

from core.config import CONFIG_DIR, UNIFIED_DB_FILE
from core.logger import get_logger
from routes.mp_sec_routes import (
    WX_API_BASE,
    MpSecError,
    _check_auth_key,
    _check_push_signature,
    _wx_get_json,
    get_access_token,
)

mp_vpay_bp = Blueprint('mp_vpay', __name__, url_prefix='/api/mp/sec/vpay')
logger = get_logger('system')
error_logger = get_logger('error')

VPAY_DB_FILE = UNIFIED_DB_FILE  # 统一库: data/stockrank.db(含 vpay_* 表)
VPAY_CONFIG_FILE = os.path.join(CONFIG_DIR, 'mp_vpay_config.json')

# 支付模式:道具直购(一次性买断)
VPAY_MODE = 'short_series_goods'
# C 端下单签名 uri(wx.requestVirtualPayment 的 paySig 固定用它)
PAYMENT_URI = 'requestVirtualPayment'
# B 端查单接口路径(paySig 的 uri 用实际路径)
QUERY_ORDER_PATH = '/xpay/query_order'

# 待支付订单兜底查单窗口:超过该时长仍未支付的订单不再查询(留给人工/后台对账)
PENDING_QUERY_MAX_HOURS = 24
# 兜底查单线程间隔(秒):官方建议 5 分钟
PENDING_CHECK_INTERVAL = 300

_ORDER_STATUSES = ('pending', 'paid', 'delivered', 'refunded', 'closed')

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
_VPAY_DEFAULTS = {
    'app_key': '',        # 现网AppKey;示例文件为占位,部署时替换为真实值
    'offer_id': '1450640154',
    'product_id': 'adfree_lifetime',
    'product_name': '去广告终身卡',
    'goods_price': 600,   # 分;必须与 MP后台道具价格一致
    'env': 0,             # 1 沙箱(联调) / 0 正式
}


def load_vpay_config():
    """读取虚拟支付商品配置;文件不存在时落一份模板,方便直接填写。"""
    cfg = dict(_VPAY_DEFAULTS)
    try:
        if os.path.exists(VPAY_CONFIG_FILE):
            with open(VPAY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg.update(json.load(f) or {})
        else:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(VPAY_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        error_logger.error(f'读取虚拟支付配置失败: {e}')
    return cfg


def get_vpay_app_key():
    """虚拟支付 AppKey 从配置文件读取(示例文件为占位值,部署时替换)。"""
    key = str(load_vpay_config().get('app_key') or '').strip()
    if not key:
        raise MpSecError('虚拟支付 AppKey 未配置(config/mp_vpay_config.json 的 app_key)', 50010)
    return key


def get_vpay_env():
    """支付环境:1=沙箱(联调) / 0=正式,取自配置文件。"""
    try:
        env = int(load_vpay_config().get('env') or 0)
    except (TypeError, ValueError):
        env = 0
    return 1 if env == 1 else 0


# ---------------------------------------------------------------------------
# 数据库:订单表 + 去广告权益表
# ---------------------------------------------------------------------------
def _db():
    conn = sqlite3.connect(VPAY_DB_FILE, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute('''CREATE TABLE IF NOT EXISTS vpay_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        out_trade_no TEXT UNIQUE NOT NULL,
        wx_order_id  TEXT UNIQUE,
        openid       TEXT NOT NULL,
        product_id   TEXT NOT NULL,
        quantity     INTEGER NOT NULL DEFAULT 1,
        goods_price  INTEGER NOT NULL,
        env          INTEGER NOT NULL DEFAULT 0,
        attach       TEXT,
        status       TEXT NOT NULL DEFAULT 'pending',
        source       TEXT,
        paid_at      TEXT,
        delivered_at TEXT,
        refunded_at  TEXT,
        last_query_at TEXT,
        query_note   TEXT,
        created_at   TEXT NOT NULL,
        updated_at   TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS vpay_entitlements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        openid       TEXT UNIQUE NOT NULL,
        status       TEXT NOT NULL DEFAULT 'active',
        out_trade_no TEXT,
        wx_order_id  TEXT,
        granted_at   TEXT,
        revoked_at   TEXT,
        updated_at   TEXT
    )''')
    return conn


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def gen_out_trade_no():
    """业务单号:VP + yyyymmddHHMMSS + 6位随机(8-32位,唯一,不能重复使用)。"""
    return 'VP' + datetime.now().strftime('%Y%m%d%H%M%S') + f'{random.randint(0, 999999):06d}'


# ---------------------------------------------------------------------------
# 签名算法(两套,严格对齐官方文档 5.5 节)
# ---------------------------------------------------------------------------
def calc_pay_sig(uri, post_body, app_key):
    """支付签名 paySig = HMAC-SHA256(appkey, uri + '&' + post_body)。

    uri 不带问号参数:C 端下单固定 requestVirtualPayment;B 端为接口路径如 /xpay/query_order。
    post_body 必须与实际发出的请求体字符串完全一致(不格式化、不改键顺序)。
    """
    msg = uri + '&' + post_body
    return hmac.new(app_key.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256).hexdigest()


def calc_signature(post_body, session_key):
    """用户态签名 signature = HMAC-SHA256(sessionKey, post_body)。"""
    return hmac.new(session_key.encode('utf-8'), post_body.encode('utf-8'),
                    hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# HTTP 薄封装(便于单测 mock;body 用原始字符串保证签名一致)
# ---------------------------------------------------------------------------
def _vpay_post(path, params, body_str, timeout=10):
    resp = requests.post(f'{WX_API_BASE}{path}', params=params,
                         data=body_str.encode('utf-8'),
                         headers={'Content-Type': 'application/json'}, timeout=timeout)
    return resp.json()


# ---------------------------------------------------------------------------
# 发货/退款核心逻辑(推送与查单兜底共用;全部幂等)
# ---------------------------------------------------------------------------
def _grant_entitlement(conn, openid, out_trade_no, wx_order_id):
    """授予去广告权益(幂等):不存在则插入;已 active 不动;revoked 则重新激活。"""
    now = _now()
    row = conn.execute('SELECT status FROM vpay_entitlements WHERE openid = ?', (openid,)).fetchone()
    if row is None:
        conn.execute('''INSERT INTO vpay_entitlements(openid, status, out_trade_no, wx_order_id,
                        granted_at, updated_at) VALUES (?, 'active', ?, ?, ?, ?)''',
                     (openid, out_trade_no, wx_order_id, now, now))
        logger.info(f'虚拟支付:授予去广告权益 openid={openid[:6]}… order={out_trade_no} wx={wx_order_id}')
    elif row['status'] != 'active':
        conn.execute('''UPDATE vpay_entitlements SET status = 'active', out_trade_no = ?,
                        wx_order_id = ?, granted_at = ?, revoked_at = NULL, updated_at = ?
                        WHERE openid = ?''', (out_trade_no, wx_order_id, now, now, openid))
        logger.info(f'虚拟支付:恢复去广告权益 openid={openid[:6]}… order={out_trade_no}')


def _revoke_entitlement(conn, out_trade_no=None, wx_order_id=None, openid=None):
    """撤销去广告权益(退款)。

    仅当权益来源单与退款单一致时才撤销,防止迟到的重复退款推送误伤
    用户之后重新购买产生的新权益。openid 只在权益来源信息缺失时兜底使用。
    """
    row = conn.execute('SELECT * FROM vpay_entitlements WHERE openid = ?',
                       (openid or '',)).fetchone()
    if row is None:
        return False
    if out_trade_no or wx_order_id:
        same = (out_trade_no and row['out_trade_no'] == out_trade_no) or \
               (wx_order_id and row['wx_order_id'] == wx_order_id)
        if not same:
            logger.warning(f'虚拟支付:退款单与权益来源不一致,跳过撤销 order={out_trade_no} '
                           f'wx={wx_order_id} 权益来源={row["out_trade_no"]}')
            return False
    if row['status'] != 'active':
        return False
    conn.execute('''UPDATE vpay_entitlements SET status = 'revoked', revoked_at = ?, updated_at = ?
                    WHERE openid = ?''', (_now(), _now(), row['openid']))
    logger.info(f'虚拟支付:退款撤销去广告权益 openid={row["openid"][:6]}… order={out_trade_no}')
    return True


def _deliver_order(openid, out_trade_no, wx_order_id, product_id, quantity, env, source):
    """发货:更新订单为 delivered + 授予权益。以 wx_order_id 幂等,重复通知只发一次货。"""
    now = _now()
    with _db() as conn:
        order = None
        if wx_order_id:
            order = conn.execute('SELECT * FROM vpay_orders WHERE wx_order_id = ?',
                                 (wx_order_id,)).fetchone()
        if order is None and out_trade_no:
            order = conn.execute('SELECT * FROM vpay_orders WHERE out_trade_no = ?',
                                 (out_trade_no,)).fetchone()

        if order is not None:
            if order['status'] == 'delivered':
                return False  # 幂等:已发货
            if openid and order['openid'] and openid != order['openid']:
                # 串单风险:不发货、不重试(回 0 终止平台重推),人工排查
                error_logger.error(
                    f'虚拟支付:发货推送 openid 与订单不一致!order={out_trade_no} '
                    f'wx={wx_order_id} 推送openid={openid[:6]}… 订单openid={order["openid"][:6]}…')
                return False
            conn.execute('''UPDATE vpay_orders SET wx_order_id = COALESCE(?, wx_order_id),
                            status = 'delivered', source = ?, delivered_at = ?, updated_at = ?
                            WHERE id = ?''', (wx_order_id, source, now, now, order['id']))
            openid = order['openid']
            out_trade_no = order['out_trade_no']
        else:
            # 本地无此单(推送先于下单落库/外部环境订单):落一条外来单记录,同样发货
            conn.execute('''INSERT INTO vpay_orders(out_trade_no, wx_order_id, openid, product_id,
                            quantity, goods_price, env, attach, status, source, delivered_at, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, 0, ?, NULL, 'delivered', ?, ?, ?, ?)''',
                         (out_trade_no or f'VPEXT{random.randint(10**11, 10**12 - 1)}', wx_order_id,
                          openid or '', product_id or '', int(quantity or 1), int(env or 0),
                          source, now, now, now))
            logger.warning(f'虚拟支付:收到无本地订单的发货推送,已按外来单发货 order={out_trade_no} '
                           f'wx={wx_order_id} openid={openid}')

        _grant_entitlement(conn, openid, out_trade_no, wx_order_id)
    return True


def _refund_order(out_trade_no, wx_order_id):
    """退款:订单标记 refunded + 撤销对应权益。幂等。"""
    now = _now()
    with _db() as conn:
        order = None
        if wx_order_id:
            order = conn.execute('SELECT * FROM vpay_orders WHERE wx_order_id = ?',
                                 (wx_order_id,)).fetchone()
        if order is None and out_trade_no:
            order = conn.execute('SELECT * FROM vpay_orders WHERE out_trade_no = ?',
                                 (out_trade_no,)).fetchone()
        if order is None:
            logger.warning(f'虚拟支付:收到无法匹配订单的退款推送 order={out_trade_no} wx={wx_order_id}')
            return False
        if order['status'] == 'refunded':
            return False  # 幂等
        conn.execute('''UPDATE vpay_orders SET status = 'refunded', refunded_at = ?, updated_at = ?
                        WHERE id = ?''', (now, now, order['id']))
        _revoke_entitlement(conn, out_trade_no=order['out_trade_no'],
                            wx_order_id=order['wx_order_id'], openid=order['openid'])
    return True


# ---------------------------------------------------------------------------
# 微信推送(XML/JSON)解析与分发
# ---------------------------------------------------------------------------
def _xml_to_dict(elem):
    """XML → dict(叶子节点取 text;节点值保持字符串)。"""
    children = list(elem)
    if not children:
        return (elem.text or '').strip()
    node = {}
    for child in children:
        node[child.tag] = _xml_to_dict(child)
    return node


def _extract_push_fields(data):
    """从推送体提取关键字段(兼容 XML/JSON 两种键风格)。"""
    pay_info = data.get('WeChatPayInfo') or data.get('wechat_pay_info') or {}
    goods_info = data.get('GoodsInfo') or data.get('goods_info') or {}
    order_like = data.get('order') or {}

    def _clean(v):
        v = str(v or '').strip()
        return v or None

    return {
        'openid': _clean(data.get('OpenId') or data.get('openid')
                         or data.get('FromUserName') or order_like.get('openid')),
        'out_trade_no': _clean(data.get('OutTradeNo') or data.get('out_trade_no')
                               or data.get('MchOrderId') or order_like.get('order_id')),
        'wx_order_id': _clean(pay_info.get('MchOrderNo') or data.get('WxOrderId')
                              or data.get('wx_order_id') or order_like.get('wx_order_id')),
        'product_id': _clean(goods_info.get('ProductId') or data.get('ProductId')
                             or order_like.get('product_id')),
        'quantity': goods_info.get('Quantity') or data.get('Quantity') or 1,
        'env': data.get('Env', order_like.get('env_type', 0)),
    }


def handle_xpay_push(data, was_xml):
    """分发 xpay_* 推送事件并构造平台要求的应答。

    发货/退款处理失败也回 ErrCode=0(避免 15 次无意义重推),异常进 error 日志人工排查;
    仅在签名校验失败时回 403。
    """
    event = str(data.get('Event') or data.get('event') or '')
    fields = _extract_push_fields(data or {})
    if event == 'xpay_goods_deliver_notify':
        try:
            _deliver_order(fields['openid'], fields['out_trade_no'], fields['wx_order_id'],
                           fields['product_id'], fields['quantity'],
                           fields['env'] if str(fields['env']).isdigit() else 0, 'push')
        except Exception as e:
            error_logger.error(f'虚拟支付:发货推送处理异常 order={fields["out_trade_no"]}: {e}')
    elif event == 'xpay_refund_notify':
        try:
            _refund_order(fields['out_trade_no'], fields['wx_order_id'])
        except Exception as e:
            error_logger.error(f'虚拟支付:退款推送处理异常 order={fields["out_trade_no"]}: {e}')
    else:
        logger.debug(f'虚拟支付:忽略未处理的推送事件 {event or "(无Event)"}')

    if was_xml:
        body = '<xml><ErrCode>0</ErrCode><ErrMsg><![CDATA[success]]></ErrMsg></xml>'
        return Response(body, mimetype='application/xml')
    return jsonify({'ErrCode': 0, 'ErrMsg': 'success'})


def _parse_push_body():
    """解析推送请求体:JSON 或 XML。返回 (data, was_xml)。"""
    raw = request.get_data(as_text=True) or ''
    trimmed = raw.strip()
    if trimmed.startswith('<'):
        try:
            return _xml_to_dict(ET.fromstring(trimmed)), True
        except ET.ParseError as e:
            error_logger.error(f'虚拟支付:推送XML解析失败: {e}')
            return {}, True
    try:
        return json.loads(trimmed) if trimmed else {}, False
    except ValueError:
        return {}, False


@mp_vpay_bp.route('/notify', methods=['POST'])
def vpay_notify():
    """微信平台推送接收(发货/退款)。签名校验用消息推送 Token,与内容安全回调一致。"""
    if not _check_push_signature(request.args):
        logger.warning('虚拟支付:推送签名校验失败,已拒绝')
        return 'forbidden', 403
    data, was_xml = _parse_push_body()
    return handle_xpay_push(data or {}, was_xml)


def handle_xpay_push_request(raw_xml):
    """供统一消息推送入口(/api/mp/sec/callback)分流 XML 推送:验签 → 解析 → 处理。"""
    if not _check_push_signature(request.args):
        logger.warning('虚拟支付:XML推送签名校验失败,已拒绝')
        return 'forbidden', 403
    try:
        data = _xml_to_dict(ET.fromstring(raw_xml))
    except ET.ParseError as e:
        error_logger.error(f'虚拟支付:推送XML解析失败: {e}')
        data = {}
    return handle_xpay_push(data or {}, was_xml=True)


# ---------------------------------------------------------------------------
# 业务接口
# ---------------------------------------------------------------------------
@mp_vpay_bp.route('/params', methods=['POST'])
def vpay_params():
    """下单:code 换 session_key,生成 payData 供 wx.requestVirtualPayment 拉起支付。

    body: {code}(wx.login 取得,服务端用它换取新鲜 session_key 参与用户态签名)
    返回: {pay_data: {mode, signData, paySig, signature}, out_trade_no, product}
          已拥有权益时返回 already_owned=true 且不给 pay_data(终身卡防重复购买)
    """
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        app_key = get_vpay_app_key()
        data = request.get_json(silent=True) or {}
        code = str(data.get('code') or '').strip()
        if not code:
            return jsonify({'success': False, 'message': '缺少 code 参数(先 wx.login)'}), 400

        mp_cfg = load_mp_cfg_safe()
        cfg = load_vpay_config()
        env = get_vpay_env()

        # code2session:拿 openid + 新鲜 session_key(session_key 不落盘不下发)
        resp = _wx_get_json(f'{WX_API_BASE}/sns/jscode2session', {
            'appid': mp_cfg['appid'], 'secret': mp_cfg['appsecret'],
            'js_code': code, 'grant_type': 'authorization_code',
        })
        openid = resp.get('openid')
        session_key = resp.get('session_key')
        if not openid or not session_key:
            return jsonify({'success': False, 'error': 'wechat_api_error',
                            'errcode': resp.get('errcode'), 'errmsg': resp.get('errmsg', '')}), 502

        with _db() as conn:
            owned = conn.execute(
                'SELECT status FROM vpay_entitlements WHERE openid = ?', (openid,)).fetchone()
        if owned and owned['status'] == 'active':
            return jsonify({'success': True, 'already_owned': True, 'ad_free': True,
                            'product': _product_view(cfg)})

        # 业务单号 + signData(字段顺序对齐官方示例;金额全程用分,不换算)
        out_trade_no = gen_out_trade_no()
        sign_obj = {
            'offerId': str(cfg['offer_id']),
            'buyQuantity': 1,
            'env': env,
            'currencyType': 'CNY',
            'productId': str(cfg['product_id']),
            'goodsPrice': int(cfg['goods_price']),
            'outTradeNo': out_trade_no,
            'attach': out_trade_no,
        }
        sign_data = json.dumps(sign_obj, separators=(',', ':'), ensure_ascii=False)
        pay_sig = calc_pay_sig(PAYMENT_URI, sign_data, app_key)
        signature = calc_signature(sign_data, session_key)

        with _db() as conn:
            conn.execute('''INSERT INTO vpay_orders(out_trade_no, openid, product_id, quantity,
                            goods_price, env, attach, status, created_at)
                            VALUES (?, ?, ?, 1, ?, ?, ?, 'pending', ?)''',
                         (out_trade_no, openid, cfg['product_id'], int(cfg['goods_price']),
                          env, out_trade_no, _now()))
        logger.info(f'虚拟支付:下单成功 openid={openid[:6]}… order={out_trade_no} '
                    f'price={cfg["goods_price"]}分 env={env}')

        return jsonify({
            'success': True,
            'already_owned': False,
            'out_trade_no': out_trade_no,
            'pay_data': {'mode': VPAY_MODE, 'signData': sign_data,
                         'paySig': pay_sig, 'signature': signature},
            'product': _product_view(cfg),
        })
    except MpSecError as e:
        return jsonify({'success': False, 'message': e.message, 'errcode': e.code}), 400
    except Exception as e:
        error_logger.error(f'vpay params 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


def load_mp_cfg_safe():
    """复用内容安全代理配置(appid/appsecret,code2session 需要)。"""
    from routes.mp_sec_routes import load_mp_sec_config
    cfg = load_mp_sec_config()
    if not cfg.get('appid'):
        raise MpSecError('小程序 appid 未配置(backend/config/mp_sec_config.json)', 50001)
    return cfg


def _product_view(cfg):
    return {'product_id': cfg['product_id'], 'product_name': cfg['product_name'],
            'goods_price': int(cfg['goods_price']), 'env': get_vpay_env()}


@mp_vpay_bp.route('/status', methods=['GET'])
def vpay_status():
    """查询去广告权益:GET ?openid=... → {ad_free, entitlement, last_order, product}。"""
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        openid = (request.args.get('openid') or '').strip()
        if not openid:
            return jsonify({'success': False, 'message': '缺少 openid 参数'}), 400
        with _db() as conn:
            ent = conn.execute('SELECT * FROM vpay_entitlements WHERE openid = ?',
                               (openid,)).fetchone()
            last = conn.execute('''SELECT out_trade_no, status, goods_price, env, created_at
                                   FROM vpay_orders WHERE openid = ?
                                   ORDER BY id DESC LIMIT 1''', (openid,)).fetchone()
        return jsonify({
            'success': True,
            'ad_free': bool(ent and ent['status'] == 'active'),
            'entitlement': dict(ent) if ent else None,
            'last_order': dict(last) if last else None,
            'product': _product_view(load_vpay_config()),
        })
    except Exception as e:
        error_logger.error(f'vpay status 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


# ---------------------------------------------------------------------------
# 兜底查单:query_order + 后台线程(官方建议 5 分钟一轮)
# ---------------------------------------------------------------------------
# query_order 的 order.status 枚举 → 本地处理动作
_QS_DELIVER = {2, 3, 4}          # 已支付待发货 / 发货中 / 已发货
_QS_REFUND = {5, 8}              # 已退款 / 用户退款完成
_QS_CLOSED = {6}                 # 已关闭


def query_wx_order(openid, out_trade_no, env, app_key):
    """调 /xpay/query_order 查平台订单。pay_sig 加在 query;body 为紧凑 JSON 原文。"""
    body = json.dumps({'openid': openid, 'env': int(env), 'order_id': out_trade_no},
                      separators=(',', ':'), ensure_ascii=False)
    pay_sig = calc_pay_sig(QUERY_ORDER_PATH, body, app_key)
    token = get_access_token()
    return _vpay_post(QUERY_ORDER_PATH, {'access_token': token, 'pay_sig': pay_sig}, body)


def check_pending_orders(max_age_hours=PENDING_QUERY_MAX_HOURS, batch_limit=50):
    """扫描 pending 订单调 query_order:已支付补发货、已退款补撤销、已关闭落 closed。"""
    try:
        app_key = get_vpay_app_key()
    except MpSecError:
        return 0
    env = get_vpay_env()
    cutoff = (datetime.now() - timedelta(hours=max_age_hours)).strftime('%Y-%m-%d %H:%M:%S')
    with _db() as conn:
        rows = conn.execute('''SELECT * FROM vpay_orders WHERE status = 'pending' AND env = ?
                               AND created_at >= ? ORDER BY id LIMIT ?''',
                            (env, cutoff, batch_limit)).fetchall()
    if not rows:
        return 0
    handled = 0
    for order in rows:
        try:
            resp = query_wx_order(order['openid'], order['out_trade_no'], order['env'], app_key)
        except MpSecError as e:
            logger.warning(f'虚拟支付:查单取凭证失败 order={order["out_trade_no"]}: {e.message}')
            continue
        except Exception as e:
            logger.warning(f'虚拟支付:查单请求失败 order={order["out_trade_no"]}: {e}')
            continue
        note = f'errcode={resp.get("errcode")} status={(resp.get("order") or {}).get("status")}'
        wx_status = (resp.get('order') or {}).get('status')
        wx_order_id = (resp.get('order') or {}).get('wx_order_id') or ''
        if resp.get('errcode') != 0:
            logger.info(f'虚拟支付:查单未果 order={order["out_trade_no"]} {note}')
        elif wx_status in _QS_DELIVER:
            _deliver_order(order['openid'], order['out_trade_no'], wx_order_id,
                           order['product_id'], order['quantity'], order['env'], 'query')
            handled += 1
            note = f'query补发货 wx={wx_order_id}'
        elif wx_status in _QS_REFUND:
            _refund_order(order['out_trade_no'], wx_order_id)
            handled += 1
            note = 'query发现已退款'
        elif wx_status in _QS_CLOSED:
            with _db() as conn:
                conn.execute('''UPDATE vpay_orders SET status = 'closed', updated_at = ?,
                                last_query_at = ?, query_note = ? WHERE id = ?''',
                             (_now(), _now(), 'query发现已关闭', order['id']))
            handled += 1
            note = 'query发现已关闭'
        # 0/1(初始化/创建成功)仍是待支付,只记录查询时间
        if wx_status not in _QS_CLOSED:
            with _db() as conn:
                conn.execute('''UPDATE vpay_orders SET last_query_at = ?, query_note = ?
                                WHERE id = ?''', (_now(), note, order['id']))
    if rows:
        logger.info(f'虚拟支付:兜底查单完成 待查={len(rows)} 处理={handled}')
    return handled


def cleanup_expired_pending_orders():
    """删除超过10分钟仍未支付的 pending 订单。"""
    ten_mins_ago = (datetime.now() - timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
    with _db() as conn:
        cursor = conn.execute("DELETE FROM vpay_orders WHERE status = 'pending' AND created_at < ?", (ten_mins_ago,))
        deleted = cursor.rowcount
    if deleted > 0:
        logger.info(f'虚拟支付:清理超过10分钟未支付订单 {deleted} 条')
    return deleted


def vpay_check_loop(interval=PENDING_CHECK_INTERVAL):
    """后台线程:每 5 分钟兜底查单(推送丢失时补发货),并清理超时未支付订单。"""
    from monitors.thread_monitor import register_thread, heartbeat
    register_thread('vpay_pending_checker')
    time.sleep(60)  # 启动避让,别与其他采集线程抢资源
    while True:
        heartbeat('vpay_pending_checker')
        try:
            check_pending_orders()
            cleanup_expired_pending_orders()
        except Exception as e:
            error_logger.error(f'虚拟支付:兜底查单线程异常: {e}')
        time.sleep(interval)
