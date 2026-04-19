import os
import logging
from logging.handlers import RotatingFileHandler
from config import LOG_DIR, is_dev_mode

_loggers_initialized = False

def ensure_directories():
    os.makedirs(LOG_DIR, exist_ok=True)

def setup_logging():
    global _loggers_initialized
    
    ensure_directories()
    
    error_logger = logging.getLogger('error_logger')
    data_logger = logging.getLogger('data_logger')
    system_logger = logging.getLogger('system_logger')
    
    if _loggers_initialized:
        return error_logger, data_logger, system_logger
    
    log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')
    
    if is_dev_mode():
        error_logger.setLevel(logging.DEBUG)
        data_logger.setLevel(logging.DEBUG)
        system_logger.setLevel(logging.DEBUG)
    else:
        error_logger.setLevel(logging.ERROR)
        data_logger.setLevel(logging.INFO)
        system_logger.setLevel(logging.INFO)
    
    error_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, 'error.log'),
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setFormatter(log_formatter)
    error_logger.addHandler(error_handler)
    
    data_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, 'data.log'),
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    data_handler.setFormatter(log_formatter)
    data_logger.addHandler(data_handler)
    
    system_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, 'system.log'),
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    system_handler.setFormatter(log_formatter)
    system_logger.addHandler(system_handler)
    
    _loggers_initialized = True
    
    return error_logger, data_logger, system_logger
