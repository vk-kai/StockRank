import os
import logging
from logging.handlers import RotatingFileHandler
from config import LOG_DIR

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
    
    error_logger.setLevel(logging.ERROR)
    error_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, 'error.log'),
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    error_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')
    error_handler.setFormatter(error_formatter)
    error_logger.addHandler(error_handler)
    
    data_logger.setLevel(logging.INFO)
    data_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, 'data.log'),
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    data_formatter = logging.Formatter('%(asctime)s - %(filename)s:%(lineno)d - %(message)s')
    data_handler.setFormatter(data_formatter)
    data_logger.addHandler(data_handler)
    
    system_logger.setLevel(logging.INFO)
    system_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, 'system.log'),
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    system_formatter = logging.Formatter('%(asctime)s - %(filename)s:%(lineno)d - %(message)s')
    system_handler.setFormatter(system_formatter)
    system_logger.addHandler(system_handler)
    
    _loggers_initialized = True
    
    return error_logger, data_logger, system_logger
