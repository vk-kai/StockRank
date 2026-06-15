from flask import Blueprint, jsonify, request
import json
import os
import requests
import time
import hmac
import hashlib
import base64
import traceback

from config import (
    AI_CONFIG_FILE, FEISHU_CONFIG_FILE, 
    STOCK_MONITOR_CONFIG_FILE, AI_PROMPT_FILE, AI_DAILY_PROMPT_FILE
)
from data_processor import error_logger
from logger import get_logger
from .auth_routes import verify_password

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
        
        for key in ['enabled', 'msg_type', 'base_url']:
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

# ==================== 股票监控配置 ====================
@config_bp.route('/stock-monitor', methods=['GET'])
def get_stock_monitor_config():
    try:
        if os.path.exists(STOCK_MONITOR_CONFIG_FILE):
            with open(STOCK_MONITOR_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                return jsonify({'success': True, 'data': config})
        return jsonify({'success': True, 'data': {}})
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
