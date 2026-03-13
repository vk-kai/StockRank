import os
import logging
from logging.handlers import RotatingFileHandler
from config import LOG_DIR

# 确保目录存在
def ensure_directories():
    os.makedirs(LOG_DIR, exist_ok=True)

# 配置日志
def setup_logging():
    # 确保目录存在
    ensure_directories()
    
    # 异常日志
    error_logger = logging.getLogger('error_logger')
    error_logger.setLevel(logging.ERROR)
    error_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, 'error.log'),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'  # 修复编码问题
    )
    error_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')
    error_handler.setFormatter(error_formatter)
    error_logger.addHandler(error_handler)
    
    # 数据爬取日志
    data_logger = logging.getLogger('data_logger')
    data_logger.setLevel(logging.INFO)
    data_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, 'data.log'),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'  # 修复编码问题
    )
    data_formatter = logging.Formatter('%(asctime)s - %(filename)s:%(lineno)d - %(message)s')
    data_handler.setFormatter(data_formatter)
    data_logger.addHandler(data_handler)
    
    # 系统操作日志
    system_logger = logging.getLogger('system_logger')
    system_logger.setLevel(logging.INFO)
    system_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, 'system.log'),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'  # 修复编码问题
    )
    system_formatter = logging.Formatter('%(asctime)s - %(filename)s:%(lineno)d - %(message)s')
    system_handler.setFormatter(system_formatter)
    system_logger.addHandler(system_handler)
    
    return error_logger, data_logger, system_logger
