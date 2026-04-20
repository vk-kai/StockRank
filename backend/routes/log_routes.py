from flask import Blueprint, jsonify, request
import os
import re

from config import LOG_DIR
from data_processor import error_logger
from logger import get_log_modules

log_bp = Blueprint('log', __name__, url_prefix='/api/log')

LOG_FILES = {
    'error': 'error.log',
    'system': 'system.log',
    'data': 'data.log',
    'news': 'news.log',
    'ai': 'ai.log',
    'monitor': 'monitor.log',
    'nginx': 'nginx/error.log'
}

LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

LOG_MODULES_INFO = {
    'error': {'desc': '错误日志', 'color': '#f56c6c'},
    'system': {'desc': '系统日志', 'color': '#409eff'},
    'data': {'desc': '数据采集', 'color': '#67c23a'},
    'news': {'desc': '新闻采集', 'color': '#e6a23c'},
    'ai': {'desc': 'AI分析', 'color': '#909399'},
    'monitor': {'desc': '线程监控', 'color': '#b37feb'},
    'nginx': {'desc': 'Nginx日志', 'color': '#ff85c0'}
}

LOG_PATTERN = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (DEBUG|INFO|WARNING|ERROR|CRITICAL) - ([\w\.]+):(\d+) - (.*)$'
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
            file_path = os.path.join(LOG_DIR, filename)
            module_info = LOG_MODULES_INFO.get(log_type, {'desc': log_type, 'color': '#909399'})
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
            'source': f'nginx[{pid}]',
            'lineno': int(tid),
            'message': message,
            'raw': line
        }
    return None

def parse_python_log_line(line):
    match = LOG_PATTERN.match(line)
    if match:
        timestamp, level, source, lineno, message = match.groups()
        return {
            'timestamp': timestamp,
            'level': level,
            'source': source,
            'lineno': int(lineno),
            'message': message,
            'raw': line
        }
    return None

@log_bp.route('/content/<log_type>', methods=['GET'])
def get_log_content(log_type):
    try:
        if log_type not in LOG_FILES:
            return jsonify({'success': False, 'message': '无效的日志类型'}), 400
        
        filename = LOG_FILES[log_type]
        file_path = os.path.join(LOG_DIR, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'success': True, 'data': {'lines': [], 'total': 0}})
        
        level_filter = request.args.get('level', '').upper()
        search_keyword = request.args.get('search', '').strip()
        lines_limit = min(int(request.args.get('lines', 200)), 10000)
        
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
                
                if search_keyword and search_keyword.lower() not in line.lower():
                    continue
                
                parsed_lines.append(parsed)
            else:
                if level_filter:
                    continue
                if search_keyword and search_keyword.lower() not in line.lower():
                    continue
                parsed_lines.append({
                    'timestamp': '',
                    'level': '',
                    'source': '',
                    'lineno': 0,
                    'message': line,
                    'raw': line
                })
        
        total = len(parsed_lines)
        recent_lines = parsed_lines[-lines_limit:] if len(parsed_lines) > lines_limit else parsed_lines
        recent_lines.reverse()
        
        return jsonify({
            'success': True,
            'data': {
                'lines': recent_lines,
                'total': total,
                'filtered': level_filter != '' or search_keyword != ''
            }
        })
    except Exception as e:
        error_logger.error(f"读取日志内容失败: {e}")
        return jsonify({'success': False, 'message': '读取日志内容失败'}), 500

@log_bp.route('/levels', methods=['GET'])
def get_log_levels():
    return jsonify({'success': True, 'data': LOG_LEVELS})
