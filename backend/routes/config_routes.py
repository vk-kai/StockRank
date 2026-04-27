from flask import Blueprint, jsonify, request
import json
import os
import requests
import time
import hmac
import hashlib
import base64

from config import (
    AI_CONFIG_FILE, FEISHU_CONFIG_FILE, 
    STOCK_MONITOR_CONFIG_FILE, AI_PROMPT_FILE
)
from data_processor import error_logger
from .auth_routes import verify_password

config_bp = Blueprint('config', __name__, url_prefix='/api/config')

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
        
        for key in ['enabled', 'api_url', 'model', 'temperature', 'max_tokens', 'timeout']:
            if key in data:
                config[key] = data[key]
        
        if 'api_key' in data and data['api_key'] != '******':
            config['api_key'] = data['api_key']
        
        with open(AI_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        return jsonify({'success': True, 'message': 'AI配置更新成功'})
    except Exception as e:
        error_logger.error(f"更新AI配置失败: {e}")
        return jsonify({'success': False, 'message': '更新AI配置失败'}), 500

@config_bp.route('/ai/test', methods=['POST'])
def test_ai_connection():
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
        
        if not api_url or not api_key:
            return jsonify({'success': False, 'message': 'API地址和密钥不能为空'}), 400
        
        if not api_url.endswith('/chat/completions'):
            api_url = api_url.rstrip('/') + '/chat/completions'
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        test_payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 10
        }
        
        response = requests.post(api_url, headers=headers, json=test_payload, timeout=30)
        
        try:
            response_data = response.json()
        except:
            response_data = response.text
        
        return jsonify({
            'success': response.status_code == 200,
            'status_code': response.status_code,
            'api_url': api_url,
            'data': response_data
        })
            
    except requests.exceptions.Timeout:
        return jsonify({'success': False, 'status_code': None, 'api_url': api_url, 'error': '连接超时'}), 400
    except requests.exceptions.ConnectionError as e:
        return jsonify({'success': False, 'status_code': None, 'api_url': api_url, 'error': f'连接失败: {str(e)}'}), 400
    except Exception as e:
        error_logger.error(f"测试AI连接失败: {e}")
        return jsonify({'success': False, 'status_code': None, 'api_url': api_url, 'error': str(e)}), 500
    return jsonify({'success': True, 'status_code': response.status_code, 'api_url': api_url, 'data': response_data}), 200
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
        return jsonify({'success': False, 'message': '更新AI提示词失败'}), 500
