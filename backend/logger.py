import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from config import LOG_DIR, is_dev_mode

_loggers = {}

MODULE_DISPLAY_NAMES = {
    'data': '数据采集',
    'data_collect': '数据采集—数据获取',
    'news': '新闻采集',
    'news_collect': '新闻采集—数据获取',
    'news_add': '新闻采集—新增新闻',
    'news_important': '新闻采集—重要新闻',
    'ai': 'AI分析',
    'ai_analyze': 'AI分析—内容分析',
    'ai_push': 'AI分析—飞书推送',
    'monitor': '线程监控',
    'monitor_check': '线程监控—状态检测',
    'monitor_restart': '线程监控—线程重启',
    'system': '系统运行',
    'system_start': '系统运行—服务启动',
    'system_cleanup': '系统运行—数据清理',
    'error': '错误日志'
}

class ModuleFormatter(logging.Formatter):
    def format(self, record):
        module_name = getattr(record, 'module_name', 'system')
        module_display = MODULE_DISPLAY_NAMES.get(module_name, module_name)
        record.module_display = module_display
        record.module_key = module_name
        return super().format(record)

class ModuleLogger:
    def __init__(self, logger, module_name):
        self.logger = logger
        self.module_name = module_name
    
    def _log(self, level, msg, *args, **kwargs):
        extra = kwargs.get('extra', {})
        extra['module_name'] = self.module_name
        kwargs['extra'] = extra
        self.logger.log(level, msg, *args, **kwargs)
    
    def info(self, msg, *args, **kwargs):
        self._log(logging.INFO, msg, *args, **kwargs)
    
    def debug(self, msg, *args, **kwargs):
        self._log(logging.DEBUG, msg, *args, **kwargs)
    
    def warning(self, msg, *args, **kwargs):
        self._log(logging.WARNING, msg, *args, **kwargs)
    
    def error(self, msg, *args, **kwargs):
        self._log(logging.ERROR, msg, *args, **kwargs)
    
    def critical(self, msg, *args, **kwargs):
        self._log(logging.CRITICAL, msg, *args, **kwargs)

def ensure_directories():
    os.makedirs(LOG_DIR, exist_ok=True)

def cleanup_old_logs(hours=48):
    ensure_directories()
    now = datetime.now()
    cutoff = now - timedelta(hours=hours)
    
    cleaned_files = []
    
    for filename in os.listdir(LOG_DIR):
        if filename.endswith('.log') or filename.endswith('.log.'):
            file_path = os.path.join(LOG_DIR, filename)
            try:
                file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
                if file_mtime < cutoff:
                    os.remove(file_path)
                    cleaned_files.append(filename)
            except Exception as e:
                pass
    
    return cleaned_files

def get_logger(module_name='system'):
    global _loggers
    
    cache_key = f'module_{module_name}'
    if cache_key in _loggers:
        return _loggers[cache_key]
    
    ensure_directories()
    
    is_system = (
        module_name == 'system' or 
        module_name.startswith('system_') or 
        module_name == 'monitor' or 
        module_name.startswith('monitor_')
    )
    log_file = 'system.log' if is_system else 'data.log'
    logger_name = 'system_logger' if is_system else 'data_logger'
    
    base_logger = logging.getLogger(logger_name)
    
    if not base_logger.handlers:
        log_formatter = ModuleFormatter('%(asctime)s | %(levelname)s | %(module_key)s | %(module_display)s | %(module)s:%(lineno)d | %(message)s')
        
        if is_dev_mode():
            base_logger.setLevel(logging.DEBUG)
        else:
            base_logger.setLevel(logging.INFO)
        
        handler = RotatingFileHandler(
            os.path.join(LOG_DIR, log_file),
            maxBytes=10*1024*1024,
            backupCount=5,
            encoding='utf-8'
        )
        handler.setFormatter(log_formatter)
        base_logger.addHandler(handler)
    
    module_logger = ModuleLogger(base_logger, module_name)
    _loggers[cache_key] = module_logger
    return module_logger

def setup_logging():
    ensure_directories()
    
    error_logger = get_logger('error')
    data_logger = get_logger('data')
    system_logger = get_logger('system')
    
    return error_logger, data_logger, system_logger

def get_log_modules():
    main_modules = {
        'data': '数据采集',
        'news': '新闻采集',
        'ai': 'AI分析',
        'system': '系统运行',
        'monitor': '线程监控',
        'error': '错误日志'
    }
    return {name: {'desc': desc} for name, desc in main_modules.items()}

def read_recent_logs(lines=500):
    log_file = os.path.join(LOG_DIR, 'data.log')
    
    if not os.path.exists(log_file):
        return []
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            return all_lines[-lines:] if len(all_lines) > lines else all_lines
    except Exception as e:
        return []
