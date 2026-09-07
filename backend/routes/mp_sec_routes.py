# -*- coding: utf-8 -*-
"""微信小程序内容安全代理:msgSecCheck(文本,同步) + mediaCheckAsync(图片/音频,异步)。

背景:小程序《每日热门趣味测试》被审核要求接入内容安全API;access_token/appsecret
只能在服务器端使用,故由 StockRank 后端统一代理。

  POST /api/mp/sec/login         code2session 换 openid(用户需近2小时访问过小程序才能送检)
  POST /api/mp/sec/msg-check     文本同步检测(msgSecCheck 2.0)
  POST /api/mp/sec/upload        图片/音频上传,返回微信服务器可下载的 media_url
  POST /api/mp/sec/media-check   图片/音频异步送检(mediaCheckAsync 2.0),返回 trace_id
  GET  /api/mp/sec/media-result  按 trace_id 查异步结果(支持 ?wait=秒 长轮询,上限30s)
  GET  /api/mp/sec/callback      微信消息推送URL验证(echostr签名校验)
  POST /api/mp/sec/callback      接收微信 wxa_media_check 异步结果推送(明文+JSON格式)
  GET  /api/mp/sec/media/<file>  上传文件下载通道(微信检测服务器需能直接下载)

鉴权:config/mp_sec_config.json 的 auth_key 非空时,业务接口要求 X-Auth-Key 头
(或 body 里的 auth_key 字段);callback 与 media 下载是微信服务器调用的,
只做签名校验/直接放行,不走 auth_key。

配置文件(config/mp_sec_config.json):
  appid          小程序 AppID(微信公众平台-开发-开发设置)
  appsecret      小程序 AppSecret
  push_token     消息推送服务器配置里填的 Token(用于 callback 签名校验,两边必须一致)
  auth_key       小程序调用本代理的共享密钥(可自行修改,小程序端同步携带)
  media_base_url 上传文件拼公网URL的前缀,如 https://your-domain
"""
import os
import json
import re
import time
import uuid
import hashlib
import threading
import unicodedata
from datetime import datetime

import requests
from flask import Blueprint, jsonify, request, send_from_directory

from core.config import CONFIG_DIR, DATA_DIR, MP_SEC_CONFIG_FILE
from core.logger import get_logger

mp_sec_bp = Blueprint('mp_sec', __name__, url_prefix='/api/mp/sec')
logger = get_logger('system')
error_logger = get_logger('error')

# 上传文件与缓存落盘位置
MEDIA_DIR = os.path.join(DATA_DIR, 'mp_sec_media')
TOKEN_FILE = os.path.join(DATA_DIR, 'mp_sec_token.json')
RESULTS_FILE = os.path.join(DATA_DIR, 'mp_sec_results.json')

WX_API_BASE = 'https://api.weixin.qq.com'
# 微信内容安全 label 枚举 → 中文说明(展示用)
LABEL_NAMES = {
    100: '正常', 20001: '时政', 20002: '色情',
    20006: '违法犯罪', 21000: '其他',
}
# 上传格式白名单与 media_type 映射(与 mediaCheckAsync 支持范围一致)
IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'bmp', 'gif'}
AUDIO_EXTS = {'mp3', 'aac', 'ac3', 'wma', 'flac', 'wav', 'ogg', 'opus'}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 微信侧单文件上限 10M

# --------------------------------------------------------------------------
# 本地敏感词硬底线:msgSecCheck 对轻度辱骂可能判 pass(模型阈值/后台安全等级设置),
# 实测有辱骂留言在 scene=2 下仍返回 suggest=pass,这层不依赖微信可用性与判定,
# 先于微信调用本地拦截。词库保持克制——只收指向性辱骂/低俗,「废物/没用/去死」
# 这类自我否定不拦(共鸣墙留言本来就常是自我倾诉,拦了误伤产品本意)。
# --------------------------------------------------------------------------
_LOCAL_BLOCK_CN = (
    '傻逼', '傻b', '傻比', '煞笔', '煞逼', '傻笔', '傻批', '傻屄', '傻吊', '傻屌',
    '傻叉', '傻缺', '二逼', '妈逼', '你妈逼', '你妈b', '尼玛', '草泥马', '操你妈',
    '草你妈', '日你妈', '干你妈', '干你娘', '滚你妈', '你妈死了', '死全家', '婊子',
    '婊砸', '娼妓', '骚逼', '贱逼', '贱比', '贱人', '贱货', '贱b', '杂种', '王八蛋',
    '狗逼', '狗比', '狗娘养的', '脑残', '智障','习近平','中国共产党','法轮功'
)
_LOCAL_BLOCK_EN = ('sb', 'nmsl', 'cnm', 'nmb', 'fuck')
# 变体对抗:全角→半角(NFKC)、小写、去掉空白与常见分隔符(傻 逼/傻.逼/傻*逼 → 傻逼)
_LOCAL_STRIP_RE = re.compile(
    r'[\s·•.。,，、;；:：!！?？~\-—_#*\\/\|^$&@%()（）\[\]【】{}<>《》「」‘’“”\'"]+')
# 拉丁词边界用 ASCII 环视:Python 的 \b 把中文也算 \w,「大sb」会漏;usb/sbti 不误伤
_LOCAL_EN_RES = tuple(re.compile(rf'(?<![a-z0-9]){w}(?![a-z0-9])')
                      for w in _LOCAL_BLOCK_EN)


def local_text_blocked(text):
    """文本命中本地敏感词返回 True。永远先于微信送检执行,不耗微信配额。"""
    if not text:
        return False
    norm = unicodedata.normalize('NFKC', text).lower()
    norm = _LOCAL_STRIP_RE.sub('', norm)
    return any(w in norm for w in _LOCAL_BLOCK_CN) or \
        any(r.search(norm) for r in _LOCAL_EN_RES)

_token_lock = threading.Lock()
_results_lock = threading.Lock()
_TOKEN_CACHE = {'token': None, 'expires_at': 0.0}


class MpSecError(Exception):
    """业务错误:message 面向调用方,code 贯穿到响应体的 errcode。"""

    def __init__(self, message, code=50000):
        super().__init__(message)
        self.message = message
        self.code = code


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------
_CONFIG_DEFAULTS = {
    'appid': '',
    'appsecret': '',
    # 已预生成随机值:push_token 原样填到微信"消息推送"配置;auth_key 小程序端同步携带
    'push_token': 'fc3496790b79e16a67beaf59caa438f3',
    'auth_key': 'c1a62b1dedfc6ac2c076010f220b9ed8',
    'media_base_url': '',
}


def load_mp_sec_config():
    """读取配置;文件不存在时落一份模板(带预生成key),方便直接填写。"""
    cfg = dict(_CONFIG_DEFAULTS)
    try:
        if os.path.exists(MP_SEC_CONFIG_FILE):
            with open(MP_SEC_CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg.update(json.load(f) or {})
        else:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(MP_SEC_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        error_logger.error(f'读取小程序内容安全配置失败: {e}')
    return cfg


# --------------------------------------------------------------------------
# HTTP 薄封装(便于单测 mock)
# --------------------------------------------------------------------------
def _wx_post_json(url, params, payload, timeout=10):
    resp = requests.post(url, params=params, json=payload, timeout=timeout)
    return resp.json()


def _wx_get_json(url, params, timeout=10):
    resp = requests.get(url, params=params, timeout=timeout)
    return resp.json()


# --------------------------------------------------------------------------
# access_token 管理:stable_token + 内存/文件双层缓存 + 40001强刷
# --------------------------------------------------------------------------
def _load_token_file():
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


def _save_token_file(access_token, expires_at):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            json.dump({'access_token': access_token, 'expires_at': expires_at}, f)
    except Exception as e:
        error_logger.warning(f'access_token 落盘失败(不影响使用): {e}')


def get_access_token(force=False):
    """获取小程序接口调用凭证,缓存有效期2小时(提前120s刷新)。

    stable_token 不会像旧 /cgi-bin/token 那样互相顶号,多实例/重启更稳。
    """
    cfg = load_mp_sec_config()
    if not cfg.get('appid') or not cfg.get('appsecret'):
        raise MpSecError('小程序 appid/appsecret 未配置(backend/config/mp_sec_config.json)', 50001)

    now = time.time()
    if not force:
        if _TOKEN_CACHE['token'] and _TOKEN_CACHE['expires_at'] > now + 120:
            return _TOKEN_CACHE['token']
        cached = _load_token_file()
        if cached.get('access_token') and cached.get('expires_at', 0) > now + 120:
            with _token_lock:
                _TOKEN_CACHE['token'] = cached['access_token']
                _TOKEN_CACHE['expires_at'] = cached['expires_at']
            return cached['access_token']

    with _token_lock:
        # 双重检查:等锁期间别的线程可能已刷新
        if not force and _TOKEN_CACHE['token'] and _TOKEN_CACHE['expires_at'] > now + 120:
            return _TOKEN_CACHE['token']
        resp = _wx_post_json(f'{WX_API_BASE}/cgi-bin/stable_token', None, {
            'grant_type': 'client_credential',
            'appid': cfg['appid'],
            'secret': cfg['appsecret'],
            'force_refresh': bool(force),
        })
        token = resp.get('access_token')
        if not token:
            raise MpSecError(
                f"获取access_token失败: {resp.get('errmsg', 'unknown')}({resp.get('errcode', '-')})",
                resp.get('errcode') or 50002)
        expires_at = now + int(resp.get('expires_in', 7200))
        _TOKEN_CACHE['token'] = token
        _TOKEN_CACHE['expires_at'] = expires_at
        _save_token_file(token, expires_at)
        logger.info('小程序access_token已刷新')
        return token


def _call_wx_api(path, payload):
    """调用微信业务API;40001/42001(凭证失效)时强刷token重试一次。"""
    token = get_access_token()
    resp = _wx_post_json(f'{WX_API_BASE}{path}', {'access_token': token}, payload)
    if resp.get('errcode') in (40001, 42001):
        logger.warning(f'微信凭证失效({resp.get("errcode")}),强刷后重试: {path}')
        token = get_access_token(force=True)
        resp = _wx_post_json(f'{WX_API_BASE}{path}', {'access_token': token}, payload)
    return resp


def _wx_error_response(resp):
    """把微信侧错误包成统一失败响应体。"""
    return jsonify({
        'success': False,
        'error': 'wechat_api_error',
        'errcode': resp.get('errcode'),
        'errmsg': resp.get('errmsg', ''),
    }), 502


def _do_msg_sec_check(openid, content, scene):
    """调微信 msgSecCheck 2.0 检测文本,返回归一化后的响应 dict。

    老协议违规码 87014(部分场景仍会返回)归一成 v2 形态 result.suggest='risky',
    调用方只看 errcode 与 result.suggest,不必单独再处理 87014。
    网络/凭证异常直接 raise,由调用方决定降级策略。
    """
    resp = _call_wx_api('/wxa/msg_sec_check', {
        'version': 2, 'openid': openid, 'scene': scene, 'content': content})
    # 审计日志:只记判定与错误码,不记文本内容(隐私);pass 降 debug 降噪,
    # risky/errcode 异常保留 info 留证(排查「微信放行辱骂」靠它)
    suggest = (resp.get('result') or {}).get('suggest')
    log = logger.debug if resp.get('errcode') == 0 and suggest == 'pass' else logger.info
    log(f'msgSecCheck: openid={openid[:6]}… scene={scene} '
        f'errcode={resp.get("errcode")} '
        f'suggest={suggest} '
        f'label={(resp.get("result") or {}).get("label")} '
        f'trace_id={resp.get("trace_id")}')
    if resp.get('errcode') == 87014:
        resp = {'errcode': 0, 'result': {'suggest': 'risky', 'label': 21000}, 'detail': []}
    return resp


# --------------------------------------------------------------------------
# 异步结果存储:trace_id → 状态(checking → pass/risky/review/error)
# --------------------------------------------------------------------------
def _load_results():
    try:
        if os.path.exists(RESULTS_FILE):
            with open(RESULTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


def _save_results(results):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        # 只留最近500条,防止无限增长
        items = sorted(results.values(), key=lambda r: r.get('created_at', ''), reverse=True)[:500]
        with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
            json.dump({r['trace_id']: r for r in items}, f, ensure_ascii=False)
    except Exception as e:
        error_logger.error(f'内容安全结果落盘失败: {e}')


def _record_submission(trace_id, openid, media_url, media_type):
    with _results_lock:
        results = _load_results()
        results[trace_id] = {
            'trace_id': trace_id,
            'status': 'checking',
            'openid': openid,
            'media_url': media_url,
            'media_type': media_type,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        _save_results(results)


def _apply_callback_result(data):
    """落库一条 wxa_media_check 异步推送结果。"""
    trace_id = data.get('trace_id')
    if not trace_id:
        return False
    errcode = data.get('errcode')
    result = data.get('result') or {}
    suggest = result.get('suggest')
    if errcode == -1008:
        status = 'error'  # 微信侧下载失败:检查 media_url 是否公网可访问
    elif errcode != 0 or not suggest:
        status = 'error'
    else:
        status = suggest  # pass / risky / review
    label = result.get('label')
    with _results_lock:
        results = _load_results()
        rec = results.get(trace_id) or {
            'trace_id': trace_id,
            'status': status,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        rec.update({
            'status': status,
            'suggest': suggest,
            'label': label,
            'label_name': LABEL_NAMES.get(label, str(label)),
            'detail': data.get('detail') or [],
            'errcode': errcode,
            'received_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        })
        results[trace_id] = rec
        _save_results(results)
    logger.info(f'内容安全异步结果: {trace_id} -> {status}({label})')
    return True


# --------------------------------------------------------------------------
# 鉴权:auth_key(小程序→本代理);签名(微信→callback)
# --------------------------------------------------------------------------
def _check_auth_key():
    """auth_key 已配置时校验请求方。放行则返回None,拒绝则返回401响应。"""
    cfg = load_mp_sec_config()
    expected = (cfg.get('auth_key') or '').strip()
    if not expected:
        return None
    provided = (request.headers.get('X-Auth-Key') or '').strip()
    if not provided:
        body = request.get_json(silent=True) or {}
        provided = str(body.get('auth_key') or '').strip()
    if provided != expected:
        return jsonify({'success': False, 'error': 'invalid_auth_key',
                        'message': 'X-Auth-Key 校验失败'}), 401
    return None


def _check_push_signature(args):
    """微信消息推送签名校验:sha1(sort(token, timestamp, nonce)) == signature。

    push_token 未配置时跳过校验(仅建议开发期这样用)。
    """
    token = (load_mp_sec_config().get('push_token') or '').strip()
    if not token:
        return True
    signature = args.get('signature', '')
    timestamp = args.get('timestamp', '')
    nonce = args.get('nonce', '')
    expect = hashlib.sha1(''.join(sorted([token, timestamp, nonce])).encode('utf-8')).hexdigest()
    return expect == signature


# --------------------------------------------------------------------------
# 业务接口
# --------------------------------------------------------------------------
def _require_openid(data):
    openid = str(data.get('openid') or '').strip()
    if not openid:
        raise MpSecError('缺少 openid(先调 /api/mp/sec/login 用 code 换取)', 40003)
    return openid


@mp_sec_bp.route('/login', methods=['POST'])
def mp_login():
    """code2session 代理:小程序 wx.login 的 code 换 openid。

    注意:openid 对应的用户需在近2小时内访问过小程序,送检接口才能用该 openid。
    合规:session_key 禁止下发前端/参与通信(微信安全检测要求),仅返回 openid。
    """
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        cfg = load_mp_sec_config()
        if not cfg.get('appid'):
            return jsonify({'success': False, 'message': 'appid 未配置'}), 500
        data = request.get_json(silent=True) or {}
        code = str(data.get('code') or '').strip()
        if not code:
            return jsonify({'success': False, 'message': '缺少 code 参数'}), 400
        resp = _wx_get_json(f'{WX_API_BASE}/sns/jscode2session', {
            'appid': cfg['appid'], 'secret': cfg['appsecret'],
            'js_code': code, 'grant_type': 'authorization_code',
        })
        openid = resp.get('openid')
        if not openid:
            return _wx_error_response(resp)
        return jsonify({'success': True, 'openid': openid})
    except MpSecError as e:
        return jsonify({'success': False, 'message': e.message, 'errcode': e.code}), 500
    except Exception as e:
        error_logger.error(f'mp login 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


@mp_sec_bp.route('/msg-check', methods=['POST'])
def msg_check():
    """文本同步检测(msgSecCheck 2.0)。

    body: {openid, content, scene?}(scene 1资料 2评论 3论坛 4社交日志,默认1)
    返回: safe(仅 suggest==pass 为 true;老协议违规码 87014 已归一为 safe=false),
          suggest, label, label_name, detail
    """
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        data = request.get_json(silent=True) or {}
        openid = _require_openid(data)
        content = str(data.get('content') or '')
        if not content:
            return jsonify({'success': False, 'message': '缺少 content 参数'}), 400
        # scene 固定枚举 1~4,服务端先拦(微信侧只会回难懂的 40129)
        try:
            scene = int(data.get('scene') or 1)
        except (TypeError, ValueError):
            scene = 0
        if scene not in (1, 2, 3, 4):
            return jsonify({'success': False,
                            'message': 'scene 取值 1~4(1资料 2评论 3论坛 4社交日志)'}), 400
        # 本地敏感词硬底线:轻度辱骂微信可能判 pass,先拦且不耗微信配额
        if local_text_blocked(content):
            logger.info(f'msgSecCheck: 本地词库拦截 openid={openid[:6]}… scene={scene}')
            return jsonify({'success': True, 'safe': False, 'suggest': 'risky',
                            'label': 20003, 'label_name': '辱骂',
                            'detail': [], 'trace_id': None, 'local': True})
        resp = _do_msg_sec_check(openid, content, scene)
        if resp.get('errcode') != 0:
            return _wx_error_response(resp)
        result = resp.get('result') or {}
        suggest = result.get('suggest')
        label = result.get('label')
        return jsonify({
            'success': True,
            'safe': suggest == 'pass',
            'suggest': suggest,
            'label': label,
            'label_name': LABEL_NAMES.get(label, str(label)),
            'detail': resp.get('detail') or [],
            'trace_id': resp.get('trace_id'),
        })
    except MpSecError as e:
        return jsonify({'success': False, 'message': e.message, 'errcode': e.code}), 400
    except Exception as e:
        error_logger.error(f'msg-check 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


@mp_sec_bp.route('/upload', methods=['POST'])
def upload_media():
    """图片/音频上传:存到本服务器,返回微信检测服务器可下载的 media_url。

    form-data: file(≤10M,格式见白名单)。可选 auto_check=1 时上传后立即送检,
    直接返回 trace_id(省一次往返)。
    """
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        f = request.files.get('file')
        if not f:
            return jsonify({'success': False, 'message': '缺少 file 字段(form-data)'}), 400
        blob = f.read(MAX_UPLOAD_BYTES + 1)
        if len(blob) > MAX_UPLOAD_BYTES:
            return jsonify({'success': False, 'message': '文件超过10M上限'}), 400
        ext = (f.filename or '').rsplit('.', 1)[-1].lower()
        media_type = 2 if ext in IMAGE_EXTS else (1 if ext in AUDIO_EXTS else None)
        if media_type is None:
            return jsonify({'success': False,
                            'message': f'不支持的格式 .{ext}(图片:jpg/jpeg/png/bmp/gif;音频:mp3/aac/ac3/wma/flac/ogg/opus/wav)'}), 400

        day_dir = datetime.now().strftime('%Y%m%d')
        filename = f'{uuid.uuid4().hex}.{ext}'
        os.makedirs(os.path.join(MEDIA_DIR, day_dir), exist_ok=True)
        with open(os.path.join(MEDIA_DIR, day_dir, filename), 'wb') as out:
            out.write(blob)

        cfg = load_mp_sec_config()
        base = (cfg.get('media_base_url') or '').rstrip('/')
        media_url = f'{base}/api/mp/sec/media/{day_dir}/{filename}'
        resp_body = {'success': True, 'media_url': media_url, 'media_type': media_type}
        if not base:
            resp_body['warning'] = 'media_base_url 未配置,返回的URL不可公网访问,微信侧将无法下载检测'
        if str(request.values.get('auto_check') or '') in ('1', 'true'):
            openid = str(request.values.get('openid') or '').strip()
            if not openid:
                return jsonify({'success': False, 'message': 'auto_check=1 时必须同时传 openid'}), 400
            resp_body.update(_do_media_check(openid, media_url, media_type,
                                             int(request.values.get('scene') or 2)))
        return jsonify(resp_body)
    except Exception as e:
        error_logger.error(f'upload 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


def _do_media_check(openid, media_url, media_type, scene):
    """调 mediaCheckAsync 2.0 送检并登记 trace_id。返回字典(并入响应体)。"""
    resp = _call_wx_api('/wxa/media_check_async', {
        'media_url': media_url, 'media_type': media_type,
        'version': 2, 'scene': scene, 'openid': openid,
    })
    if resp.get('errcode') != 0:
        return {'success': False, 'errcode': resp.get('errcode'),
                'errmsg': resp.get('errmsg', '')}
    trace_id = resp.get('trace_id')
    _record_submission(trace_id, openid, media_url, media_type)
    return {'success': True, 'trace_id': trace_id, 'status': 'checking'}


@mp_sec_bp.route('/media-check', methods=['POST'])
def media_check():
    """图片/音频异步送检(mediaCheckAsync 2.0)。

    body: {openid, media_url, media_type?(2图片/1音频,按URL后缀自动判断), scene?}
    返回 trace_id;结果由微信异步推到 /callback,用 /media-result 查询。
    """
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        data = request.get_json(silent=True) or {}
        openid = _require_openid(data)
        media_url = str(data.get('media_url') or '').strip()
        if not media_url:
            return jsonify({'success': False, 'message': '缺少 media_url 参数'}), 400
        media_type = data.get('media_type')
        if media_type not in (1, 2):
            ext = media_url.rsplit('.', 1)[-1].lower() if '.' in media_url else ''
            media_type = 1 if ext in AUDIO_EXTS else 2
        scene = int(data.get('scene') or 2)
        result = _do_media_check(openid, media_url, media_type, scene)
        status = 200 if result.get('success') else 502
        return jsonify(result), status
    except MpSecError as e:
        return jsonify({'success': False, 'message': e.message, 'errcode': e.code}), 400
    except Exception as e:
        error_logger.error(f'media-check 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


@mp_sec_bp.route('/media-result', methods=['GET'])
def media_result():
    """按 trace_id 查异步检测结果;?wait=秒 内长轮询(上限30s)。

    status: checking(检测中) / pass / risky / review / error / not_found
    """
    denied = _check_auth_key()
    if denied:
        return denied
    try:
        trace_id = str(request.args.get('trace_id') or '').strip()
        if not trace_id:
            return jsonify({'success': False, 'message': '缺少 trace_id 参数'}), 400
        try:
            wait = min(max(int(request.args.get('wait') or 0), 0), 30)
        except ValueError:
            wait = 0
        deadline = time.time() + wait
        while True:
            with _results_lock:
                rec = _load_results().get(trace_id)
            if rec and rec.get('status') != 'checking':
                return jsonify({'success': True, **rec})
            if time.time() >= deadline:
                return jsonify({'success': True, 'status': (rec or {}).get('status', 'not_found'),
                                'trace_id': trace_id,
                                'message': '检测中,请稍后重试' if rec else 'trace_id 不存在'})
            time.sleep(0.5)
    except Exception as e:
        error_logger.error(f'media-result 异常: {e}')
        return jsonify({'success': False, 'message': f'服务异常: {e}'}), 500


@mp_sec_bp.route('/media/<day_dir>/<filename>', methods=['GET'])
def serve_media(day_dir, filename):
    """上传文件下载通道:微信检测服务器会直接GET该地址,不能要求任何鉴权。"""
    if '..' in day_dir or '..' in filename or '/' in day_dir or '\\' in filename:
        return jsonify({'success': False, 'message': '非法路径'}), 400
    try:
        return send_from_directory(os.path.join(MEDIA_DIR, day_dir), filename)
    except Exception as e:
        return jsonify({'success': False, 'message': f'文件不存在: {e}'}), 404


# --------------------------------------------------------------------------
# 微信消息推送服务器:URL验证(GET) + 异步结果接收(POST,明文JSON)
# --------------------------------------------------------------------------
@mp_sec_bp.route('/callback', methods=['GET'])
def callback_verify():
    """配置消息推送服务器时微信发来的URL验证:签名通过则原样回显 echostr。"""
    args = request.args
    if not _check_push_signature(args):
        return 'forbidden', 403
    echostr = args.get('echostr', '')
    return echostr, 200


@mp_sec_bp.route('/callback', methods=['POST'])
def callback_receive():
    """接收 wxa_media_check 异步结果推送(微信公众平台需配置为 JSON + 明文模式)。

    微信要求响应体为 success,否则会重试推送。
    """
    if not _check_push_signature(request.args):
        logger.warning('内容安全回调签名校验失败,已拒绝')
        return 'forbidden', 403
    raw = request.get_data(as_text=True) or ''
    trimmed = raw.strip()
    # 虚拟支付发货/退款推送为 XML 格式(与 JSON 模式共用同一消息推送URL),分流到 vpay 模块处理
    if trimmed.startswith('<'):
        from routes.mp_vpay_routes import handle_xpay_push_request
        return handle_xpay_push_request(trimmed)
    try:
        data = request.get_json(silent=True)
        if data is None:
            data = json.loads(trimmed) if trimmed.startswith('{') else {}
    except Exception:
        data = {}
    event = (data or {}).get('Event') or (data or {}).get('event') or ''
    if event == 'wxa_media_check' or data.get('trace_id'):
        _apply_callback_result(data or {})
    elif str(event).startswith('xpay_'):
        from routes.mp_vpay_routes import handle_xpay_push
        return handle_xpay_push(data or {}, was_xml=False)
    else:
        logger.debug(f'收到未处理的消息推送事件: {event or "(无Event)"}')
    return 'success', 200
