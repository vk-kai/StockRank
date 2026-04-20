import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from config import LOG_DIR, is_dev_mode

_loggers_initialized = False
_loggers = {}

LOG_MODULES = {
    'error': {'file': 'error.log', 'level': logging.ERROR, 'desc': '错误日志'},
    'system': {'file': 'system.log', 'level': logging.INFO, 'desc': '系统日志'},
    'data': {'file': 'data.log', 'level': logging.INFO, 'desc': '数据采集'},
    'news': {'file': 'news.log', 'level': logging.INFO, 'desc': '新闻采集'},
    'ai': {'file': 'ai.log', 'level': logging.INFO, 'desc': 'AI分析'},
    'monitor': {'file': 'monitor.log', 'level': logging.INFO, 'desc': '线程监控'},
}

def ensure_directories():
    os.makedirs(LOG_DIR, exist_ok=True)

def cleanup_old_logs(hours=48):
    ensure_directories()
    now = datetime.now()
    cutoff = now - timedelta(hours=hours)
    
    cleaned_files = []
    
    for module_name, config in LOG_MODULES.items():
        log_file = os.path.join(LOG_DIR, config['file'])
        if os.path.exists(log_file):
            try:
                file_mtime = datetime.fromtimestamp(os.path.getmtime(log_file))
                if file_mtime < cutoff:
                    os.remove(log_file)
                    cleaned_files.append(config['file'])
            except Exception as e:
                pass
    
    for backup_file in os.listdir(LOG_DIR):
        if backup_file.endswith('.log.') or 'backup' in backup_file.lower():
            backup_path = os.path.join(LOG_DIR, backup_file)
            try:
                file_mtime = datetime.fromtimestamp(os.path.getmtime(backup_path))
                if file_mtime < cutoff:
                    os.remove(backup_path)
                    cleaned_files.append(backup_file)
            except Exception as e:
                pass
    
    return cleaned_files

def get_logger(module_name):
    global _loggers
    
    if module_name in _loggers:
        return _loggers[module_name]
    
    if module_name not in LOG_MODULES:
        module_name = 'system'
    
    config = LOG_MODULES[module_name]
    logger = logging.getLogger(f'{module_name}_logger')
    
    if not logger.handlers:
        ensure_directories()
        
        log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s')
        
        if is_dev_mode():
            logger.setLevel(logging.DEBUG)
        else:
            logger.setLevel(config['level'])
        
        handler = RotatingFileHandler(
            os.path.join(LOG_DIR, config['file']),
            maxBytes=10*1024*1024,
            backupCount=5,
            encoding='utf-8'
        )
        handler.setFormatter(log_formatter)
        logger.addHandler(handler)
    
    _loggers[module_name] = logger
    return logger

def setup_logging():
    global _loggers_initialized
    
    ensure_directories()
    
    error_logger = get_logger('error')
    data_logger = get_logger('data')
    system_logger = get_logger('system')
    
    if _loggers_initialized:
        return error_logger, data_logger, system_logger
    
    _loggers_initialized = True
    
    return error_logger, data_logger, system_logger

def get_log_modules():
    return {name: {'file': config['file'], 'desc': config['desc']} for name, config in LOG_MODULES.items()}

def read_recent_logs(module_name, lines=100):
    if module_name not in LOG_MODULES:
        return []
    
    log_file = os.path.join(LOG_DIR, LOG_MODULES[module_name]['file'])
    
    if not os.path.exists(log_file):
        return []
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            return all_lines[-lines:] if len(all_lines) > lines else all_lines
    except Exception as e:
        return []
