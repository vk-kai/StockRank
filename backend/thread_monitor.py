import time

_thread_status = {}

def register_thread(name):
    _thread_status[name] = {
        'alive': True,
        'last_heartbeat': time.time()
    }

def heartbeat(name):
    if name in _thread_status:
        _thread_status[name]['last_heartbeat'] = time.time()
        _thread_status[name]['alive'] = True

def mark_dead(name):
    if name in _thread_status:
        _thread_status[name]['alive'] = False

def get_all_status():
    now = time.time()
    result = {}
    for name, status in _thread_status.items():
        elapsed = now - status['last_heartbeat']
        is_alive = status['alive'] and elapsed < 120
        result[name] = {
            'alive': is_alive,
            'last_heartbeat': status['last_heartbeat'],
            'status': 'running' if is_alive else 'stopped',
            'elapsed': round(elapsed, 1)
        }
    return result
