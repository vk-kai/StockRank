from flask import Blueprint, jsonify, request
import os
import re
import traceback
import json

from config import LOG_DIR, DATA_DIR
from data_processor import error_logger
from logger import get_log_modules, get_logger

log_bp = Blueprint('log', __name__, url_prefix='/api/log')
system_logger = get_logger('system')

LOG_FILES = {
    'system': 'system.log',
    'data': 'data.log',
    'nginx': 'nginx/error.log',
    'security': None
}

LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

LOG_MODULES_INFO = {
    'data': {'desc': '数据采集', 'color': '#67c23a'},
    'news': {'desc': '新闻采集', 'color': '#e6a23c'},
    'news_important': {'desc': '消息推送', 'color': '#ff9800'},
    'ai': {'desc': 'AI分析', 'color': '#909399'},
    'system': {'desc': '系统运行', 'color': '#409eff'},
    'monitor': {'desc': '线程监控', 'color': '#b37feb'},
    'error': {'desc': '错误日志', 'color': '#f56c6c'},
    'nginx': {'desc': 'Nginx日志', 'color': '#ff85c0'},
    'security': {'desc': '安全日志', 'color': '#e74c3c'}
}

LOG_PATTERN = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) \| (DEBUG|INFO|WARNING|ERROR|CRITICAL) \| ([\w_]+) \| ([\u4e00-\u9fa5\w—\-]+) \| ([\w\.]+):(\d+) \| (.*)$'
)

OLD_LOG_PATTERN = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) \| (DEBUG|INFO|WARNING|ERROR|CRITICAL) \| ([\u4e00-\u9fa5\w—\-]+) \| ([\w\.]+):(\d+) \| (.*)$'
)

NGINX_LOG_PATTERN = re.compile(
    r'^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}) \[(\w+)\] (\d+)#(\d+): (.*)$'
)

NGINX_LEVEL_MAP = {
    'debug': 'DEBUG',
    'info': 'INFO',
    'notice': 'INFO',
    'warn': 'WARNING',
    'error': 'ERROR',
    'crit': 'CRITICAL',
    'alert': 'CRITICAL',
    'emerg': 'CRITICAL'
}

NGINX_FILTER_PATTERNS = [
    'an upstream response is buffered to a temporary file',
]

@log_bp.route('/list', methods=['GET'])
def get_log_list():
    try:
        logs = []
        for log_type, filename in LOG_FILES.items():
            module_info = LOG_MODULES_INFO.get(log_type, {'desc': log_type, 'color': '#909399'})
            
            if filename is None:
                logs.append({
                    'type': log_type,
                    'filename': None,
                    'size': 0,
                    'exists': True,
                    'desc': module_info['desc'],
                    'color': module_info['color']
                })
            else:
                file_path = os.path.join(LOG_DIR, filename)
                if os.path.exists(file_path):
                    size = os.path.getsize(file_path)
                    logs.append({
                        'type': log_type,
                        'filename': filename,
                        'size': size,
                        'exists': True,
                        'desc': module_info['desc'],
                        'color': module_info['color']
                    })
                else:
                    logs.append({
                        'type': log_type,
                        'filename': filename,
                        'size': 0,
                        'exists': False,
                        'desc': module_info['desc'],
                        'color': module_info['color']
                    })
        return jsonify({'success': True, 'data': logs})
    except Exception as e:
        error_logger.error(f"获取日志列表失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/log/list]: {str(e)}")
        return jsonify({'success': False, 'message': '获取日志列表失败'}), 500

def parse_nginx_line(line):
    for pattern in NGINX_FILTER_PATTERNS:
        if pattern in line.lower():
            return None
    
    match = NGINX_LOG_PATTERN.match(line)
    if match:
        timestamp, level, pid, tid, message = match.groups()
        mapped_level = NGINX_LEVEL_MAP.get(level.lower(), level.upper())
        return {
            'timestamp': timestamp,
            'level': mapped_level,
            'module': 'nginx',
            'module_display': 'Nginx日志',
            'source': f'nginx[{pid}]',
            'lineno': int(tid),
            'message': message,
            'raw': line
        }
    return None

def parse_python_log_line(line):
    match = LOG_PATTERN.match(line)
    if match:
        timestamp, level, module_key, module_display, source, lineno, message = match.groups()
        return {
            'timestamp': timestamp,
            'level': level,
            'module': module_key,
            'module_display': module_display,
            'source': source,
            'lineno': int(lineno),
            'message': message,
            'raw': line
        }
    
    match = OLD_LOG_PATTERN.match(line)
    if match:
        timestamp, level, module_display, source, lineno, message = match.groups()
        return {
            'timestamp': timestamp,
            'level': level,
            'module': module_display,
            'module_display': module_display,
            'source': source,
            'lineno': int(lineno),
            'message': message,
            'raw': line
        }
    return None

def match_module(log_module, filter_module):
    if not filter_module:
        return True
    if log_module == filter_module:
        return True
    
    if filter_module == 'news':
        if log_module in ['news', 'news_collect', 'news_add']:
            return True
        return False
    
    if log_module.startswith(filter_module + '_'):
        return True
    
    return False

@log_bp.route('/content/<log_type>', methods=['GET'])
def get_log_content(log_type):
    try:
        if log_type not in LOG_FILES:
            return jsonify({'success': False, 'message': '无效的日志类型'}), 400
        
        if log_type == 'security':
            return get_security_log_content()
        
        filename = LOG_FILES[log_type]
        file_path = os.path.join(LOG_DIR, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'success': True, 'data': {'lines': [], 'total': 0, 'page': 1, 'page_size': 100, 'total_pages': 0}})
        
        level_filter = request.args.get('level', '').upper()
        module_filter = request.args.get('module', '').strip()
        search_keyword = request.args.get('search', '').strip()
        
        page = max(1, int(request.args.get('page', 1)))
        page_size = min(max(1, int(request.args.get('page_size', 100))), 500)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        parsed_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            if log_type == 'nginx':
                parsed = parse_nginx_line(line)
                if parsed is None:
                    continue
            else:
                parsed = parse_python_log_line(line)
            
            if parsed:
                if level_filter and parsed['level'] != level_filter:
                    continue
                
                if module_filter and not match_module(parsed.get('module', ''), module_filter):
                    continue
                
                if search_keyword and search_keyword.lower() not in line.lower():
                    continue
                
                parsed_lines.append(parsed)
            else:
                if level_filter or module_filter:
                    continue
                if search_keyword and search_keyword.lower() not in line.lower():
                    continue
                parsed_lines.append({
                    'timestamp': '',
                    'level': '',
                    'module': '',
                    'module_display': '',
                    'source': '',
                    'lineno': 0,
                    'message': line,
                    'raw': line
                })
        
        total = len(parsed_lines)
        total_pages = max(1, (total + page_size - 1) // page_size)
        
        parsed_lines.reverse()
        
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_lines = parsed_lines[start_idx:end_idx]
        
        return jsonify({
            'success': True,
            'data': {
                'lines': page_lines,
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': total_pages,
                'filtered': level_filter != '' or module_filter != '' or search_keyword != ''
            }
        })
    except Exception as e:
        error_logger.error(f"读取日志内容失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/log/content]: {str(e)}")
        return jsonify({'success': False, 'message': '读取日志内容失败'}), 500

def get_security_log_content():
    try:
        security_log_file = os.path.join(LOG_DIR, 'security_events.json')
        
        if not os.path.exists(security_log_file):
            return jsonify({
                'success': True,
                'data': {
                    'lines': [],
                    'total': 0,
                    'page': 1,
                    'page_size': 100,
                    'total_pages': 0
                }
            })
        
        with open(security_log_file, 'r', encoding='utf-8') as f:
            events = json.load(f)
        
        level_filter = request.args.get('level', '').upper()
        search_keyword = request.args.get('search', '').strip()
        
        page = max(1, int(request.args.get('page', 1)))
        page_size = min(max(1, int(request.args.get('page_size', 100))), 500)
        
        parsed_lines = []
        for event in events:
            event_type = event.get('type', '')
            ip = event.get('ip', '')
            attack_type = event.get('attack_type', '')
            attack_name = event.get('attack_name', '')
            api_path = event.get('api_path', '')
            method = event.get('method', '')
            keyword = event.get('keyword', '')
            field = event.get('field', '')
            timestamp = event.get('timestamp', '')
            
            level = 'WARNING'
            if event_type == 'attack_attempt':
                level = 'WARNING'
            elif event_type == 'ip_banned':
                level = 'ERROR'
            elif event_type == 'ip_unbanned':
                level = 'INFO'
            
            if level_filter and level != level_filter:
                continue
            
            if not attack_name:
                attack_names = {
                    'sql_injection': 'SQL注入',
                    'xss': 'XSS攻击',
                    'command_injection': '命令注入',
                    'path_traversal': '路径遍历',
                    'ldap_injection': 'LDAP注入',
                    'xxe': 'XXE攻击',
                    'ssrf': 'SSRF攻击'
                }
                attack_name = attack_names.get(attack_type, attack_type or '未知')
            
            message = f"[{event_type}]"
            if attack_name:
                message += f" {attack_name}"
            
            if search_keyword:
                search_text = f"{message} {ip} {api_path} {keyword} {attack_name}".lower()
                if search_keyword.lower() not in search_text:
                    continue
            
            parsed_lines.append({
                'timestamp': timestamp,
                'level': level,
                'module': 'security',
                'module_display': '安全日志',
                'source': ip,
                'lineno': 0,
                'message': message,
                'raw': json.dumps(event, ensure_ascii=False),
                'security_info': {
                    'ip': ip,
                    'attack_type': attack_type,
                    'attack_name': attack_name,
                    'api_path': api_path,
                    'method': method,
                    'keyword': keyword,
                    'field': field,
                    'event_type': event_type
                }
            })
        
        total = len(parsed_lines)
        total_pages = max(1, (total + page_size - 1) // page_size)
        
        parsed_lines.reverse()
        
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_lines = parsed_lines[start_idx:end_idx]
        
        return jsonify({
            'success': True,
            'data': {
                'lines': page_lines,
                'total': total,
                'page': page,
                'page_size': page_size,
                'total_pages': total_pages,
                'filtered': level_filter != '' or search_keyword != ''
            }
        })
    except Exception as e:
        error_logger.error(f"读取安全日志失败: {e}")
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/log/content/security]: {str(e)}")
        return jsonify({'success': False, 'message': '读取安全日志失败'}), 500

@log_bp.route('/levels', methods=['GET'])
def get_log_levels():
    return jsonify({'success': True, 'data': LOG_LEVELS})

@log_bp.route('/modules', methods=['GET'])
def get_log_modules_list():
    return jsonify({'success': True, 'data': LOG_MODULES_INFO})
