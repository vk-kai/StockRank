import time
from logger import setup_logging

error_logger, system_logger, _ = setup_logging()

_thread_status = {}
_dead_logged = {}
DEFAULT_TIMEOUT = 120
BUSY_TIMEOUT = 600

def register_thread(name):
    _thread_status[name] = {
        'alive': True,
        'last_heartbeat': time.time(),
        'start_time': time.time(),
        'busy': False,
        'busy_since': None
    }
    _dead_logged[name] = False
    system_logger.info(f"[线程监控] 线程 {name} 已注册")

def heartbeat(name):
    if name in _thread_status:
        _thread_status[name]['last_heartbeat'] = time.time()
        _thread_status[name]['alive'] = True
        _dead_logged[name] = False
    else:
        system_logger.warning(f"[线程监控] 收到未注册线程的心跳: {name}")

def set_busy(name, busy=True):
    if name in _thread_status:
        _thread_status[name]['busy'] = busy
        if busy:
            _thread_status[name]['busy_since'] = time.time()
            _thread_status[name]['last_heartbeat'] = time.time()
        else:
            _thread_status[name]['busy_since'] = None
        _dead_logged[name] = False

def mark_dead(name):
    if name in _thread_status:
        _thread_status[name]['alive'] = False
        system_logger.warning(f"[线程监控] 线程 {name} 被标记为死亡")

def get_all_status():
    now = time.time()
    result = {}
    for name, status in _thread_status.items():
        elapsed = now - status['last_heartbeat']
        is_busy = status.get('busy', False)
        
        timeout = BUSY_TIMEOUT if is_busy else DEFAULT_TIMEOUT
        is_alive = status['alive'] and elapsed < timeout
        
        if not is_alive and not _dead_logged.get(name, False):
            if is_busy:
                busy_duration = now - status.get('busy_since', now) if status.get('busy_since') else 0
                system_logger.warning(f"[线程监控] 线程 {name} 处于忙碌状态({round(busy_duration, 1)}秒)，延长超时检测")
            else:
                system_logger.error(f"[线程监控] 线程 {name} 心跳超时: 已 {round(elapsed, 1)} 秒无响应")
                _dead_logged[name] = True
        
        result[name] = {
            'alive': is_alive,
            'last_heartbeat': status['last_heartbeat'],
            'status': 'running' if is_alive else 'stopped',
            'elapsed': round(elapsed, 1),
            'uptime': round(now - status.get('start_time', now), 1),
            'busy': is_busy
        }
    return result
