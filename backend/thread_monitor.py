import time
from logger import setup_logging

error_logger, system_logger, _ = setup_logging()

_thread_status = {}

def register_thread(name):
    _thread_status[name] = {
        'alive': True,
        'last_heartbeat': time.time(),
        'start_time': time.time()
    }
    system_logger.info(f"[线程监控] 线程 {name} 已注册")

def heartbeat(name):
    if name in _thread_status:
        _thread_status[name]['last_heartbeat'] = time.time()
        _thread_status[name]['alive'] = True
    else:
        system_logger.warning(f"[线程监控] 收到未注册线程的心跳: {name}")

def mark_dead(name):
    if name in _thread_status:
        _thread_status[name]['alive'] = False
        system_logger.warning(f"[线程监控] 线程 {name} 被标记为死亡")

def get_all_status():
    now = time.time()
    result = {}
    for name, status in _thread_status.items():
        elapsed = now - status['last_heartbeat']
        is_alive = status['alive'] and elapsed < 120
        
        if not is_alive and status['alive']:
            system_logger.error(f"[线程监控] 线程 {name} 心跳超时: 已 {round(elapsed, 1)} 秒无响应")
        
        result[name] = {
            'alive': is_alive,
            'last_heartbeat': status['last_heartbeat'],
            'status': 'running' if is_alive else 'stopped',
            'elapsed': round(elapsed, 1),
            'uptime': round(now - status.get('start_time', now), 1)
        }
    return result
