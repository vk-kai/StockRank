from flask import Blueprint, jsonify, request
import os
import re

from config import LOG_DIR
from data_processor import error_logger

log_bp = Blueprint('log', __name__, url_prefix='/api/log')

LOG_FILES = {
    'error': 'error.log',
    'data': 'data.log',
    'system': 'system.log'
}

LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

LOG_PATTERN = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (DEBUG|INFO|WARNING|ERROR|CRITICAL) - ([\w\.]+):(\d+) - (.*)$'
)

@log_bp.route('/list', methods=['GET'])
def get_log_list():
    try:
        logs = []
        for log_type, filename in LOG_FILES.items():
            file_path = os.path.join(LOG_DIR, filename)
            if os.path.exists(file_path):
                size = os.path.getsize(file_path)
                logs.append({
                    'type': log_type,
                    'filename': filename,
                    'size': size,
                    'exists': True
                })
            else:
                logs.append({
                    'type': log_type,
                    'filename': filename,
                    'size': 0,
                    'exists': False
                })
        return jsonify({'success': True, 'data': logs})
    except Exception as e:
        error_logger.error(f"获取日志列表失败: {e}")
        return jsonify({'success': False, 'message': '获取日志列表失败'}), 500

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
            
            match = LOG_PATTERN.match(line)
            if match:
                timestamp, level, source, lineno, message = match.groups()
                
                if level_filter and level != level_filter:
                    continue
                
                if search_keyword and search_keyword.lower() not in line.lower():
                    continue
                
                parsed_lines.append({
                    'timestamp': timestamp,
                    'level': level,
                    'source': source,
                    'lineno': int(lineno),
                    'message': message,
                    'raw': line
                })
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
