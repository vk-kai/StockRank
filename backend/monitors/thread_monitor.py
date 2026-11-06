import time
from core.logger import get_logger

error_logger = get_logger('error')
system_logger = get_logger('monitor')

_thread_status = {}
_dead_logged = {}
DEFAULT_TIMEOUT = 120
BUSY_TIMEOUT = 600

def register_thread(name, heartbeat_timeout=None):
    """注册线程。heartbeat_timeout: 该线程的自定义心跳超时(秒)。
    长睡眠线程(窗口外/周期间长 sleep 且睡眠中不发心跳)必须传更大值,
    否则会被 DEFAULT_TIMEOUT(120s) 误判为 stopped。None → 用默认值。"""
    _thread_status[name] = {
        'alive': True,
        'last_heartbeat': time.time(),
        'start_time': time.time(),
        'busy': False,
        'busy_since': None,
        'timeout': heartbeat_timeout,
    }
    _dead_logged[name] = False
    system_logger.info(f"[线程监控] 线程 {name} 已注册"
                       + (f"(心跳超时 {heartbeat_timeout}s)" if heartbeat_timeout else ""))

def heartbeat(name):
    if name in _thread_status:
        _thread_status[name]['last_heartbeat'] = time.time()
        _thread_status[name]['alive'] = True
        _dead_logged[name] = False
    else:
        system_logger.warning(f"[线程监控] 收到未注册线程的心跳: {name}")

def heartbeat_if_registered(name):
    """已注册才发心跳:供 poll_once 这类"后台线程与测试/手动触发共用"的函数
    在长循环内逐项报平安;未注册(测试直调)时静默跳过,不刷未注册告警。"""
    if name in _thread_status:
        heartbeat(name)

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

        # 忙碌用长超时；其次用线程注册时的自定义超时；都没有才用默认值
        timeout = BUSY_TIMEOUT if is_busy else (status.get('timeout') or DEFAULT_TIMEOUT)
        is_alive = status['alive'] and elapsed < timeout
        
        if not is_alive and not _dead_logged.get(name, False):
            if is_busy:
                busy_duration = now - status.get('busy_since', now) if status.get('busy_since') else 0
                # 同一卡死周期只告警一次:忙碌超时的线程每次健康轮询都会走到这里,
                # 不去重会每 30 秒刷一条 warning。busy 线程监控循环会跳过不重启,
                # 卡死超过 30 分钟升级 error 提示人工介入。
                _dead_logged[name] = True
                if busy_duration > 1800:
                    system_logger.error(f"[线程监控] 线程 {name} 忙碌已 {round(busy_duration / 60)} 分钟，疑似卡死(busy 状态不自动重启,需人工检查)")
                else:
                    system_logger.warning(f"[线程监控] 线程 {name} 处于忙碌状态({round(busy_duration, 1)}秒)，延长超时检测")
            else:
                system_logger.error(f"[线程监控] 线程 {name} 心跳超时: 已 {round(elapsed, 1)} 秒无响应")
                _dead_logged[name] = True
        
        result[name] = {
            'alive': is_alive,
            'last_heartbeat': status['last_heartbeat'],
            'status': 'running' if is_alive else 'stopped',
            'elapsed': round(elapsed, 1),
            'timeout': timeout,
            'uptime': round(now - status.get('start_time', now), 1),
            'busy': is_busy
        }
    return result
