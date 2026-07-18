from flask import Blueprint, jsonify, request, current_app, session
import json
import os
import requests
import time
import hmac
import hashlib
import base64
import traceback

from config import (
    AI_CONFIG_FILE, FEISHU_CONFIG_FILE, WECHAT_CONFIG_FILE,
    STOCK_MONITOR_CONFIG_FILE, AI_PROMPT_FILE, AI_DAILY_PROMPT_FILE,
    STOCK_SCORE_PROMPT_FILE, DATASOURCE_CONFIG_FILE, DEFAULT_DATASOURCES,
    get_random_user_agent, get_eastmoney_headers
)
from data_processor import error_logger
from logger import get_logger
from .auth_routes import verify_password
from otp_service import (
    load_otp_config, save_otp_config, is_otp_enabled,
    generate_secret, build_provisioning_uri, build_qr_data_url, verify_code,
)
from session_secret import rotate_session_secret
from daily_password import BEIJING_TZ
from datetime import datetime

config_bp = Blueprint('config', __name__, url_prefix='/api/config')
system_logger = get_logger('system')

def mask_sensitive_data(data, sensitive_keys):
    for key in sensitive_keys:
        if key in data:
            data[key] = '******'
    return data

# ==================== AI配置 ====================
@config_bp.route('/ai', methods=['GET'])
def get_ai_config():
    try:
        if os.path.exists(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                config = mask_sensitive_data(config, ['api_key'])
                return jsonify({'success': True, 'data': config})
        return jsonify({'success': True, 'data': {}})
    except Exception as e:
        error_logger.error(f"获取AI配置失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/ai GET]: {str(e)}")
        return jsonify({'success': False, 'message': '获取AI配置失败'}), 500

@config_bp.route('/ai', methods=['POST'])
def update_ai_config():
    try:
        data = request.json
        
        if not verify_password(data.get('password', '')):
            return jsonify({'success': False, 'message': '密码错误'}), 401
        
        if os.path.exists(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            config = {}
        
        for key in ['enabled', 'api_url', 'full_url', 'model', 'temperature', 'max_tokens', 'timeout']:
            if key in data:
                config[key] = data[key]
        
        if 'api_key' in data and data['api_key'] != '******':
            config['api_key'] = data['api_key']
        
        with open(AI_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        return jsonify({'success': True, 'message': 'AI配置更新成功'})
    except Exception as e:
        error_logger.error(f"更新AI配置失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/ai POST]: {str(e)}")
        return jsonify({'success': False, 'message': '更新AI配置失败'}), 500

@config_bp.route('/ai/test', methods=['POST'])
def test_ai_connection():
    test_result = {
        'success': False,
        'steps': [],
        'api_url': '',
        'final_url': ''
    }
    
    try:
        data = request.json or {}
        
        if os.path.exists(AI_CONFIG_FILE):
            with open(AI_CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
        else:
            saved_config = {}
        
        api_url = data.get('api_url') or saved_config.get('api_url')
        api_key = data.get('api_key')
        if not api_key or api_key == '******':
            api_key = saved_config.get('api_key')
        model = data.get('model') or saved_config.get('model', 'gpt-3.5-turbo')
        full_url = data.get('full_url') if data.get('full_url') is not None else saved_config.get('full_url', False)
        
        if not api_url or not api_key:
            return jsonify({'success': False, 'message': 'API地址和密钥不能为空'}), 400
        
        test_result['api_url'] = api_url
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        base_url = api_url.rstrip('/')
        if '/chat/completions' in base_url:
            base_url = base_url.rsplit('/chat/completions', 1)[0]
        if '/completions' in base_url:
            base_url = base_url.rsplit('/completions', 1)[0]
        
        models_url = base_url + '/models'
        
        step1 = {'name': '连通性测试', 'url': models_url, 'success': False}
        try:
            models_response = requests.get(models_url, headers=headers, timeout=10)
            step1['status_code'] = models_response.status_code
            if models_response.status_code == 200:
                step1['success'] = True
                step1['message'] = 'API连通正常'
                try:
                    models_data = models_response.json()
                    if 'data' in models_data:
                        available_models = [m.get('id', '') for m in models_data.get('data', [])[:5]]
                        if available_models:
                            step1['message'] = f'可用模型: {", ".join(available_models)}...'
                except:
                    pass
            elif models_response.status_code == 401:
                step1['message'] = 'API密钥无效或未授权'
            elif models_response.status_code == 404:
                step1['success'] = True
                step1['message'] = 'API端点可达（/models不可用，但可能支持对话接口）'
            else:
                step1['message'] = f'HTTP {models_response.status_code}'
        except requests.exceptions.Timeout:
            step1['message'] = '连接超时（10秒）'
        except requests.exceptions.ConnectionError as e:
            step1['message'] = f'网络连接失败: {str(e)[:100]}'
        except Exception as e:
            step1['message'] = f'请求异常: {str(e)[:100]}'
        
        test_result['steps'].append(step1)
        
        chat_url = api_url
        if not full_url and not api_url.endswith('/chat/completions'):
            chat_url = api_url.rstrip('/') + '/chat/completions'
        
        test_result['final_url'] = chat_url
        
        step2 = {'name': '对话测试', 'url': chat_url, 'success': False}
        
        if not step1['success'] and '网络连接失败' in step1.get('message', ''):
            step2['message'] = '跳过（网络不可达）'
            test_result['steps'].append(step2)
            test_result['message'] = f"网络连接失败，请检查API地址是否正确"
            return jsonify(test_result), 400
        
        test_payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Hi"}],
            "max_tokens": 5
        }
        
        try:
            chat_response = requests.post(chat_url, headers=headers, json=test_payload, timeout=30)
            step2['status_code'] = chat_response.status_code
            
            if chat_response.status_code == 200:
                step2['success'] = True
                step2['message'] = f'对话测试成功，模型: {model}'
                test_result['success'] = True
                test_result['message'] = 'AI连接测试成功'
            else:
                try:
                    error_data = chat_response.json()
                    error_msg = error_data.get('error', {})
                    if isinstance(error_msg, dict):
                        step2['message'] = error_msg.get('message', f'HTTP {chat_response.status_code}')
                    else:
                        step2['message'] = str(error_msg)[:200]
                except:
                    step2['message'] = chat_response.text[:200] if chat_response.text else f'HTTP {chat_response.status_code}'
                
                if chat_response.status_code == 401:
                    step2['message'] = 'API密钥无效'
                elif chat_response.status_code == 404:
                    step2['message'] = '接口地址不存在，请检查URL或开启"完整URL模式"'
                elif chat_response.status_code == 400:
                    step2['message'] = f'请求参数错误: {step2["message"][:100]}'
                
                test_result['message'] = step2['message']
                
        except requests.exceptions.Timeout:
            step2['message'] = '对话请求超时（30秒）'
            test_result['message'] = '对话请求超时，API响应过慢'
        except requests.exceptions.ConnectionError as e:
            step2['message'] = f'连接失败: {str(e)[:100]}'
            test_result['message'] = '对话接口连接失败'
        except Exception as e:
            step2['message'] = f'请求异常: {str(e)[:100]}'
            test_result['message'] = step2['message']
        
        test_result['steps'].append(step2)
        
        return jsonify(test_result)
            
    except Exception as e:
        error_logger.error(f"测试AI连接失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/ai/test]: {str(e)}")
        test_result['message'] = f'测试异常: {str(e)}'
        return jsonify(test_result), 500
# ==================== 飞书配置 ====================
@config_bp.route('/feishu', methods=['GET'])
def get_feishu_config():
    try:
        if os.path.exists(FEISHU_CONFIG_FILE):
            with open(FEISHU_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                config = mask_sensitive_data(config, ['webhook_url', 'secret'])
                return jsonify({'success': True, 'data': config})
        return jsonify({'success': True, 'data': {}})
    except Exception as e:
        error_logger.error(f"获取飞书配置失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/feishu GET]: {str(e)}")
        return jsonify({'success': False, 'message': '获取飞书配置失败'}), 500

@config_bp.route('/feishu', methods=['POST'])
def update_feishu_config():
    try:
        data = request.json
        
        if not verify_password(data.get('password', '')):
            return jsonify({'success': False, 'message': '密码错误'}), 401
        
        if os.path.exists(FEISHU_CONFIG_FILE):
            with open(FEISHU_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            config = {}
        
        for key in ['enabled', 'msg_type', 'base_url', 'news_push_mode']:
            if key in data:
                config[key] = data[key]
        
        if 'webhook_url' in data and data['webhook_url'] != '******':
            config['webhook_url'] = data['webhook_url']
        
        if 'secret' in data and data['secret'] != '******':
            config['secret'] = data['secret']
        
        with open(FEISHU_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        return jsonify({'success': True, 'message': '飞书配置更新成功'})
    except Exception as e:
        error_logger.error(f"更新飞书配置失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/feishu POST]: {str(e)}")
        return jsonify({'success': False, 'message': '更新飞书配置失败'}), 500

@config_bp.route('/feishu/test', methods=['POST'])
def test_feishu_push():
    try:
        data = request.json or {}
        
        if os.path.exists(FEISHU_CONFIG_FILE):
            with open(FEISHU_CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
        else:
            saved_config = {}
        
        webhook_url = data.get('webhook_url')
        if not webhook_url or webhook_url == '******':
            webhook_url = saved_config.get('webhook_url')
        
        secret = data.get('secret')
        if not secret or secret == '******':
            secret = saved_config.get('secret', '')
        
        if not webhook_url:
            return jsonify({'success': False, 'status_code': None, 'error': 'Webhook地址不能为空'}), 400
        
        timestamp = str(int(time.time()))
        
        msg_type = saved_config.get('msg_type', 'text')
        
        if msg_type == 'text':
            message = {
                "title": "🔔 飞书机器人测试消息",
                "content": "这是一条测试消息，用于验证飞书推送功能是否正常工作。",
                "url": ""
            }
        else:
            message = {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": "🔔 飞书机器人测试消息"
                        },
                        "template": "blue"
                    },
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "tag": "plain_text",
                                "content": "这是一条测试消息，用于验证飞书推送功能是否正常工作。"
                            }
                        }
                    ]
                }
            }
        
        if secret:
            string_to_sign = f"{timestamp}\n{secret}"
            hmac_code = hmac.new(
                string_to_sign.encode("utf-8"),
                digestmod=hashlib.sha256
            ).digest()
            sign = base64.b64encode(hmac_code).decode('utf-8')
            message["timestamp"] = timestamp
            message["sign"] = sign
        
        response = requests.post(webhook_url, json=message, timeout=10)
        
        try:
            response_data = response.json()
        except:
            response_data = response.text
        
        return jsonify({
            'success': response.status_code == 200 and response_data.get('code') == 0,
            'status_code': response.status_code,
            'data': response_data
        })
            
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'status_code': None, 'error': '连接超时'}), 400
    except requests.exceptions.ConnectionError as e:
        return jsonify({'success': False, 'status_code': None, 'error': f'连接失败: {str(e)}'}), 400
    except Exception as e:
        error_logger.error(f"测试飞书推送失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/feishu/test]: {str(e)}")
        return jsonify({'success': False, 'status_code': None, 'error': str(e)}), 500

# ==================== 企业微信配置 ====================
@config_bp.route('/wechat', methods=['GET'])
def get_wechat_config():
    try:
        if os.path.exists(WECHAT_CONFIG_FILE):
            with open(WECHAT_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                config = mask_sensitive_data(config, ['webhook_url'])
                return jsonify({'success': True, 'data': config})
        return jsonify({'success': True, 'data': {}})
    except Exception as e:
        error_logger.error(f"获取企业微信配置失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/wechat GET]: {str(e)}")
        return jsonify({'success': False, 'message': '获取企业微信配置失败'}), 500

@config_bp.route('/wechat', methods=['POST'])
def update_wechat_config():
    try:
        data = request.json

        if not verify_password(data.get('password', '')):
            return jsonify({'success': False, 'message': '密码错误'}), 401

        if os.path.exists(WECHAT_CONFIG_FILE):
            with open(WECHAT_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
        else:
            config = {}

        for key in ['enabled', 'msg_type', 'base_url', 'news_push_mode']:
            if key in data:
                config[key] = data[key]

        if 'webhook_url' in data and data['webhook_url'] != '******':
            config['webhook_url'] = data['webhook_url']

        with open(WECHAT_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        return jsonify({'success': True, 'message': '企业微信配置更新成功'})
    except Exception as e:
        error_logger.error(f"更新企业微信配置失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/wechat POST]: {str(e)}")
        return jsonify({'success': False, 'message': '更新企业微信配置失败'}), 500

@config_bp.route('/wechat/test', methods=['POST'])
def test_wechat_push():
    try:
        data = request.json or {}

        if os.path.exists(WECHAT_CONFIG_FILE):
            with open(WECHAT_CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
        else:
            saved_config = {}

        webhook_url = data.get('webhook_url')
        if not webhook_url or webhook_url == '******':
            webhook_url = saved_config.get('webhook_url')

        msg_type = data.get('msg_type') or saved_config.get('msg_type', 'markdown')

        if not webhook_url:
            return jsonify({'success': False, 'status_code': None, 'error': 'Webhook地址不能为空'}), 400

        if msg_type == 'text':
            message = {
                "msgtype": "text",
                "text": {
                    "content": "🔔 企业微信机器人测试消息\n\n这是一条测试消息，用于验证企业微信推送功能是否正常工作。"
                }
            }
        else:
            message = {
                "msgtype": "markdown",
                "markdown": {
                    "content": "**🔔 企业微信机器人测试消息**\n\n这是一条测试消息，用于验证企业微信推送功能是否正常工作。"
                }
            }

        response = requests.post(webhook_url, json=message, timeout=10)

        try:
            response_data = response.json()
        except:
            response_data = response.text

        return jsonify({
            'success': response.status_code == 200 and response_data.get('errcode') == 0,
            'status_code': response.status_code,
            'data': response_data
        })

    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'status_code': None, 'error': '连接超时'}), 400
    except requests.exceptions.ConnectionError as e:
        return jsonify({'success': False, 'status_code': None, 'error': f'连接失败: {str(e)}'}), 400
    except Exception as e:
        error_logger.error(f"测试企业微信推送失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/wechat/test]: {str(e)}")
        return jsonify({'success': False, 'status_code': None, 'error': str(e)}), 500

# ==================== 股票监控配置 ====================
@config_bp.route('/stock-search', methods=['GET'])
def stock_search():
    """添加个股时的实时搜索:返回新浪 suggest 候选(只 A 股,去重)。
    前端只能从结果里选择,不能自填名字/代码;关键词不受此限制。"""
    try:
        kw = (request.args.get('kw') or request.args.get('q') or '').strip()
        if not kw:
            return jsonify({'success': True, 'data': []})
        from stock_resolver import search_candidates
        data = search_candidates(kw, limit=10)
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        error_logger.error(f"股票搜索失败: {e}")
        system_logger.error(f"API错误 [/api/config/stock-search]: {str(e)}")
        return jsonify({'success': False, 'message': '股票搜索失败'}), 500

@config_bp.route('/stock-monitor', methods=['GET'])
def get_stock_monitor_config():
    try:
        from stock_price_monitor import load_config as load_stock_monitor_config
        return jsonify({'success': True, 'data': load_stock_monitor_config()})
    except Exception as e:
        error_logger.error(f"获取股票监控配置失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/stock-monitor GET]: {str(e)}")
        return jsonify({'success': False, 'message': '获取股票监控配置失败'}), 500

@config_bp.route('/stock-monitor', methods=['POST'])
def update_stock_monitor_config():
    try:
        data = request.json
        
        if not verify_password(data.get('password', '')):
            return jsonify({'success': False, 'message': '密码错误'}), 401
        
        config_data = {k: v for k, v in data.items() if k != 'password'}
        with open(STOCK_MONITOR_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)

        # 清除 stock_monitor.py 的配置缓存，让后台监控线程下次循环读到新配置
        try:
            from stock_monitor import _cached_config, _cache_time
            import stock_monitor as _sm
            _sm._cached_config = None
            _sm._cache_time = 0
        except Exception:
            pass

        # 如果 watchlist 非空且 enabled，打日志确认
        try:
            from logger import get_logger
            _sys_logger = get_logger('system')
            wl = config_data.get('watchlist', [])
            enabled = config_data.get('enabled', False)
            _sys_logger.info(f'股票监控配置已更新: enabled={enabled}, watchlist={len(wl)}项')
            if enabled and wl:
                codes = [w.get('resolved_code', w.get('value', '?')) for w in wl if w.get('enabled')]
                _sys_logger.info(f'监控目标: {codes}')
        except Exception:
            pass

        return jsonify({'success': True, 'message': '股票监控配置更新成功'})
    except Exception as e:
        error_logger.error(f"更新股票监控配置失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/stock-monitor POST]: {str(e)}")
        return jsonify({'success': False, 'message': '更新股票监控配置失败'}), 500

# ==================== AI提示词配置 ====================
@config_bp.route('/prompt', methods=['GET'])
def get_ai_prompt():
    try:
        if os.path.exists(AI_PROMPT_FILE):
            with open(AI_PROMPT_FILE, 'r', encoding='utf-8') as f:
                prompt = f.read()
                return jsonify({'success': True, 'data': prompt})
        return jsonify({'success': True, 'data': ''})
    except Exception as e:
        error_logger.error(f"获取AI提示词失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/prompt GET]: {str(e)}")
        return jsonify({'success': False, 'message': '获取AI提示词失败'}), 500

@config_bp.route('/prompt', methods=['POST'])
def update_ai_prompt():
    try:
        data = request.json
        
        if not verify_password(data.get('password', '')):
            return jsonify({'success': False, 'message': '密码错误'}), 401
        
        prompt = data.get('prompt', '')
        with open(AI_PROMPT_FILE, 'w', encoding='utf-8') as f:
            f.write(prompt)
        return jsonify({'success': True, 'message': 'AI提示词更新成功'})
    except Exception as e:
        error_logger.error(f"更新AI提示词失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/prompt POST]: {str(e)}")
        return jsonify({'success': False, 'message': '更新AI提示词失败'}), 500

# ==================== 首页AI分析提示词配置 ====================
@config_bp.route('/daily-prompt', methods=['GET'])
def get_ai_daily_prompt():
    try:
        if os.path.exists(AI_DAILY_PROMPT_FILE):
            with open(AI_DAILY_PROMPT_FILE, 'r', encoding='utf-8') as f:
                prompt = f.read()
                return jsonify({'success': True, 'data': prompt})
        return jsonify({'success': True, 'data': ''})
    except Exception as e:
        error_logger.error(f"获取首页AI分析提示词失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/daily-prompt GET]: {str(e)}")
        return jsonify({'success': False, 'message': '获取首页AI分析提示词失败'}), 500

@config_bp.route('/daily-prompt', methods=['POST'])
def update_ai_daily_prompt():
    try:
        data = request.json

        if not verify_password(data.get('password', '')):
            return jsonify({'success': False, 'message': '密码错误'}), 401

        prompt = data.get('prompt', '')
        with open(AI_DAILY_PROMPT_FILE, 'w', encoding='utf-8') as f:
            f.write(prompt)
        return jsonify({'success': True, 'message': '首页AI分析提示词更新成功'})
    except Exception as e:
        error_logger.error(f"更新首页AI分析提示词失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/daily-prompt POST]: {str(e)}")
        return jsonify({'success': False, 'message': '更新首页AI分析提示词失败'}), 500

# ==================== 股票打分提示词配置（大盘云图 AI 批量打分）====================
@config_bp.route('/stock-score-prompt', methods=['GET'])
def get_stock_score_prompt():
    try:
        if os.path.exists(STOCK_SCORE_PROMPT_FILE):
            with open(STOCK_SCORE_PROMPT_FILE, 'r', encoding='utf-8') as f:
                return jsonify({'success': True, 'data': f.read()})
        return jsonify({'success': True, 'data': ''})
    except Exception as e:
        error_logger.error(f"获取股票打分提示词失败: {e}")
        return jsonify({'success': False, 'message': '获取股票打分提示词失败'}), 500

@config_bp.route('/stock-score-prompt', methods=['POST'])
def update_stock_score_prompt():
    try:
        data = request.json

        if not verify_password(data.get('password', '')):
            return jsonify({'success': False, 'message': '密码错误'}), 401

        prompt = data.get('prompt', '')
        with open(STOCK_SCORE_PROMPT_FILE, 'w', encoding='utf-8') as f:
            f.write(prompt)
        return jsonify({'success': True, 'message': '股票打分提示词更新成功'})
    except Exception as e:
        error_logger.error(f"更新股票打分提示词失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/config/stock-score-prompt POST]: {str(e)}")
        return jsonify({'success': False, 'message': '更新股票打分提示词失败'}), 500

# ==================== 数据源配置 ====================
def _load_datasource_config():
    """加载数据源配置：用户自定义URL覆盖默认值"""
    custom = {}
    if os.path.exists(DATASOURCE_CONFIG_FILE):
        try:
            with open(DATASOURCE_CONFIG_FILE, 'r', encoding='utf-8') as f:
                custom = json.load(f)
        except Exception:
            pass
    # 合并：默认 + 用户覆盖
    sources = []
    for ds in DEFAULT_DATASOURCES:
        item = dict(ds)
        if item['key'] in custom:
            item['url'] = custom[item['key']]
        sources.append(item)
    return sources

@config_bp.route('/datasource', methods=['GET'])
def get_datasource_config():
    try:
        sources = _load_datasource_config()
        return jsonify({'success': True, 'data': sources})
    except Exception as e:
        error_logger.error(f"获取数据源配置失败: {e}")
        return jsonify({'success': False, 'message': '获取数据源配置失败'}), 500

@config_bp.route('/datasource', methods=['POST'])
def update_datasource_config():
    try:
        data = request.json
        if not verify_password(data.get('password', '')):
            return jsonify({'success': False, 'message': '密码错误'}), 401
        # data.sources: {key: url} 只保存用户自定义的URL
        overrides = data.get('sources', {})
        with open(DATASOURCE_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(overrides, f, ensure_ascii=False, indent=2)
        return jsonify({'success': True, 'message': '数据源配置更新成功'})
    except Exception as e:
        error_logger.error(f"更新数据源配置失败: {e}")
        return jsonify({'success': False, 'message': '更新数据源配置失败'}), 500

@config_bp.route('/datasource/test', methods=['POST'])
def test_datasource():
    """一键测试所有数据源可用性。返回 {key: {ok, status_code, latency_ms, error}}"""
    try:
        sources = _load_datasource_config()
        results = {}
        for ds in sources:
            key = ds['key']
            test_url = ds.get('test_url', '')
            if not test_url:
                # akshare等非HTTP接口，标记为跳过
                results[key] = {'ok': None, 'status_code': None, 'latency_ms': None, 'error': '非HTTP接口，跳过测试'}
                continue
            # 根据数据源类型选请求头（与业务请求完全一致）
            provider = ds.get('provider', '')
            if '东方财富' in provider:
                headers = get_eastmoney_headers()
            elif '同花顺' in provider:
                # 使用与业务请求相同的cookie生成逻辑
                try:
                    from data_processor import attach_fresh_ths_cookie, generate_random_headers, normalize_ths_sector_headers
                    host = 'data.10jqka.com.cn'
                    if 'q.10jqka' in test_url:
                        host = 'q.10jqka.com.cn'
                    elif 'dq.10jqka' in test_url:
                        host = 'dq.10jqka.com.cn'
                    elif 'news.10jqka' in test_url:
                        host = 'news.10jqka.com.cn'
                    if 'hyzjl' in test_url or 'field' in test_url:
                        headers = attach_fresh_ths_cookie(normalize_ths_sector_headers())
                    else:
                        headers = attach_fresh_ths_cookie(generate_random_headers(host=host))
                except Exception:
                    headers = {
                        'User-Agent': get_random_user_agent(),
                        'Referer': 'https://data.10jqka.com.cn/',
                        'Accept': '*/*',
                    }
            elif '新浪' in provider:
                headers = {
                    'User-Agent': get_random_user_agent(),
                    'Referer': 'https://finance.sina.com.cn/',
                }
            elif '腾讯' in provider:
                headers = {
                    'User-Agent': get_random_user_agent(),
                    'Referer': 'https://gu.qq.com/',
                }
            elif '金融界' in provider:
                headers = {
                    'User-Agent': get_random_user_agent(),
                    'Referer': 'https://www.jrj.com.cn/',
                }
            else:
                headers = {'User-Agent': get_random_user_agent()}

            import time as _t
            start = _t.time()
            try:
                if '东方财富' in provider:
                    # 使用em_request支持代理自动切换
                    from config import em_request
                    resp = em_request(test_url, headers=headers, timeout=10)
                    latency = int((_t.time() - start) * 1000)
                    if resp is None:
                        results[key] = {'ok': False, 'status_code': None, 'latency_ms': latency, 'error': '直连+代理均不可达'}
                    else:
                        ok = resp.status_code == 200 and len(resp.content) > 10
                        results[key] = {'ok': ok, 'status_code': resp.status_code, 'latency_ms': latency, 'error': None if ok else f'HTTP {resp.status_code}' if resp.status_code != 200 else '响应内容为空'}
                else:
                    resp = requests.get(test_url, headers=headers, timeout=8, allow_redirects=True)
                    latency = int((_t.time() - start) * 1000)
                    ok = resp.status_code == 200
                    results[key] = {'ok': ok, 'status_code': resp.status_code, 'latency_ms': latency, 'error': None if ok else f'HTTP {resp.status_code}'}
            except requests.exceptions.Timeout:
                latency = int((_t.time() - start) * 1000)
                results[key] = {'ok': False, 'status_code': None, 'latency_ms': latency, 'error': '超时'}
            except Exception as e:
                latency = int((_t.time() - start) * 1000)
                results[key] = {'ok': False, 'status_code': None, 'latency_ms': latency, 'error': str(e)[:80]}
        return jsonify({'success': True, 'data': results})
    except Exception as e:
        error_logger.error(f"测试数据源失败: {e}")
        return jsonify({'success': False, 'message': f'测试数据源失败: {e}'}), 500

# ==================== 测试推送 ====================
@config_bp.route('/push/test', methods=['POST'])
def test_push_notification():
    """测试推送：同时发送飞书+微信，使用真实格式"""
    from notification_pusher import is_push_enabled, send_feishu_message, send_wechat_message
    feishu_ok = False
    wechat_ok = False
    
    # 测试资金异动格式
    anomaly_title = '🔴 半导体回调吸筹 净流入+99.14亿'
    anomaly_content = '> 时间：**2026-07-15 09:30**\n> 净流入：<font color="warning">+99.14 亿</font>\n> 涨跌幅：**+0.74%**\n> 龙头：**有研硅** +2.15%\n\n**触发条件**\n• 回调吸筹（历史上榜样本 12 次）\n• 突变（相比 09:25 变化 +5.21亿）'
    
    # 测试价格异动格式
    price_title = '🟢 长电科技累计大跌 -5.31%'
    price_content = '> 时间:**2026-07-15 09:35:00**\n> 现价:**97.25**  涨跌幅:**-5.31%**\n**累计大跌 -5.31%**'

    # 发送飞书
    if is_push_enabled('feishu'):
        try:
            send_feishu_message(anomaly_title, anomaly_content)
            send_feishu_message(price_title, price_content)
            feishu_ok = True
        except Exception as e:
            error_logger.warning(f"测试飞书推送失败: {e}")

    # 发送微信
    if is_push_enabled('wechat'):
        try:
            send_wechat_message(anomaly_title, anomaly_content)
            send_wechat_message(price_title, price_content)
            wechat_ok = True
        except Exception as e:
            error_logger.warning(f"测试微信推送失败: {e}")

    return jsonify({
        'success': True,
        'feishu': feishu_ok,
        'wechat': wechat_ok
    })


# ==================== OTP 动态口令（TOTP）二次验证 ====================
def _now_beijing_str():
    """当前北京时间字符串，用于 enrolled_at 展示。"""
    try:
        return datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return ''


@config_bp.route('/otp/status', methods=['GET'])
def otp_status():
    """查询 OTP 开启状态（已登录即可访问）。"""
    cfg = load_otp_config()
    return jsonify({
        'success': True,
        'data': {
            'enabled': bool(cfg.get('enabled')),
            'enrolled_at': cfg.get('enrolled_at', ''),
        }
    })


@config_bp.route('/otp/setup', methods=['GET'])
def otp_setup():
    """生成一个待绑定的密钥 + 二维码。

    返回的 secret 此刻并未落库；只有 /otp/enable 验证通过后才写入 otp_config.json。
    前端需把返回的 secret 一并回传给 /otp/enable。
    """
    try:
        secret = generate_secret()
        uri = build_provisioning_uri(secret)
        qr = build_qr_data_url(uri)
        return jsonify({
            'success': True,
            'data': {
                'secret': secret,
                'otpauth_uri': uri,
                'qr_data_url': qr,
            }
        })
    except Exception as e:
        error_logger.error(f"OTP setup 失败: {e}")
        return jsonify({'success': False, 'message': str(e) or '生成二维码失败'}), 500


@config_bp.route('/otp/enable', methods=['POST'])
def otp_enable():
    """开启 OTP：校验日密码 + 校验用户当场输入的动态口令（确认手机已正确添加）。

    成功后：
      1) 把 secret 落库，enabled=true；
      2) 旋转会话签名密钥 → 所有旧登录态立即失效，强制重新登录（含当前管理员）。
    """
    try:
        data = request.json or {}

        if not verify_password(data.get('password', '')):
            return jsonify({'success': False, 'message': '密码错误'}), 401

        secret = str(data.get('secret') or '').strip()
        otp_code = str(data.get('otp_code') or '').strip()

        if not secret:
            return jsonify({'success': False, 'message': '请先获取二维码'}), 400
        if not verify_code(secret, otp_code):
            return jsonify({'success': False, 'message': '动态口令错误，请确认手机已正确添加并输入最新 6 位数字'}), 400

        save_otp_config({
            'enabled': True,
            'secret': secret,
            'enrolled_at': _now_beijing_str(),
        })

        # 强制重登录：旋转持久化会话密钥 → 所有旧会话 Cookie 验签失败；
        # 同时清空当前请求会话，避免 Flask 用新密钥重新签发一个仍登录的 Cookie。
        try:
            rotate_session_secret(current_app)
            session.clear()
        except Exception as e:
            error_logger.error(f"旋转会话密钥失败（OTP 已开启但未踢出旧会话）: {e}")

        return jsonify({
            'success': True,
            'message': 'OTP 动态口令已开启，所有设备需要重新登录（账号密码不变，登录时多输入一次动态口令）'
        })
    except Exception as e:
        error_logger.error(f"开启 OTP 失败: {e}")
        error_logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': '开启 OTP 失败'}), 500


@config_bp.route('/otp/disable', methods=['POST'])
def otp_disable():
    """关闭 OTP：需日密码 + 当前动态口令（防止他人误关）。"""
    try:
        data = request.json or {}

        if not verify_password(data.get('password', '')):
            return jsonify({'success': False, 'message': '密码错误'}), 401

        cfg = load_otp_config()
        if not cfg.get('enabled'):
            return jsonify({'success': True, 'message': 'OTP 未开启'})

        if not verify_code(cfg.get('secret', ''), str(data.get('otp_code') or '').strip()):
            return jsonify({'success': False, 'message': '动态口令错误'}), 400

        save_otp_config({'enabled': False, 'secret': '', 'enrolled_at': ''})
        return jsonify({'success': True, 'message': 'OTP 动态口令已关闭'})
    except Exception as e:
        error_logger.error(f"关闭 OTP 失败: {e}")
        error_logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': '关闭 OTP 失败'}), 500

