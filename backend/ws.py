# -*- coding: utf-8 -*-
"""全局唯一的 SocketIO 实例与实时推送入口。

为什么单独成模块：
  start.sh 以 `python app.py` 启动时，app.py 作为 `__main__` 运行，
  真正在服务的 SocketIO 实例存在于 `__main__` 命名空间。
  而后台线程里 `from app import push_event` 会把 app.py **再导入一次**
  （模块名 `app`，与 `__main__` 是两个独立模块），从而 new 出第二个
  从未 init_app / 从未 serve、也没有任何客户端连接的「影子」SocketIO ——
  所有 news / anomaly / price_alert / data_update 推送都发到这个影子实例上，
  静默丢失，前端永远收不到（微信、测试通知不受影响，因为它们不走这里）。

  把 socketio / push_event 放到独立模块 ws.py 后，无论谁来
  `from ws import push_event`，拿到的都是 sys.modules['ws'] 里同一个实例，
  即 app.py init_app 并 serve 的那个，推送才能真正送达前端。
"""
import time
import threading
import uuid
from datetime import datetime

from flask_socketio import SocketIO

try:
    from core.logger import get_logger
    _log = get_logger('push')        # 推送成功/失败均归到"实时推送"分类，按日志级别区分
    _err_log = get_logger('error')   # 推送失败额外记一条到"错误日志"，便于盘中集中排查
except Exception:  # 极端情况下日志不可用也不能影响推送
    _log = None
    _err_log = None

# 全局唯一实例：app.py 负责在 create_app() 里 init_app、在 __main__ 里 run。
socketio = SocketIO(cors_allowed_origins="*", async_mode='threading', ping_timeout=60, ping_interval=25)


def push_event(event_type, data):
    """向所有已连接的前端客户端推送实时事件。

    event_type: 'news' / 'anomaly' / 'price_alert' / 'data_update'
                / 'push_ping'（静默心跳）/ 'push_test'（手动测试，前端弹通知）
    """
    try:
        clients = get_connected_clients()
        socketio.emit('push', {'type': event_type, 'data': data})
        if event_type in ('news', 'anomaly', 'price_alert'):
            if _log:
                _log.info(f"SocketIO推送成功: type={event_type}, clients={clients}")
    except Exception as e:
        if _log:
            _log.error(f"SocketIO推送失败: type={event_type}, error={e}")
        if _err_log:
            _err_log.error(f"SocketIO推送失败: type={event_type}, error={e}")


# ============================================================================
# 推送服务健康度（供「服务监控-消息推送服务」卡片用）
# ============================================================================
# 思路：定时(静默)心跳——后端发 push_ping(带 nonce)，前端收到后回 push_pong
#       且不弹任何通知；后端据此判断链路是否通畅。手动「测试」按钮则发 push_test，
#       前端真的弹一条桌面通知，用于人眼即时验证。

_clients_lock = threading.Lock()
_connected_clients = 0  # 当前已连接的前端客户端数（由 app.py 的 connect/disconnect 维护）

_pending_lock = threading.Lock()
_pinged = {}   # nonce -> 发 ping 的时间戳（仅记最近一次未确认的）
_ponged = set()  # 已收到 pong 的 nonce 集合


def register_client():
    """有前端连接时调用（app.py on_connect）。"""
    global _connected_clients
    with _clients_lock:
        _connected_clients += 1


def unregister_client():
    """有前端断开时调用（app.py on_disconnect）。"""
    global _connected_clients
    with _clients_lock:
        _connected_clients = max(0, _connected_clients - 1)


def get_connected_clients():
    with _clients_lock:
        return _connected_clients


def send_push_ping():
    """发一次静默心跳，返回 nonce。前端收到后应回 push_pong(nonce)。"""
    nonce = uuid.uuid4().hex[:8]
    with _pending_lock:
        _pinged[nonce] = time.time()
        _ponged.discard(nonce)
    push_event('push_ping', {'nonce': nonce})
    return nonce


def record_push_pong(nonce):
    """前端回 pong 时调用（app.py on 'push_pong'）。"""
    if not nonce:
        return
    with _pending_lock:
        _ponged.add(nonce)


def pong_received_for(nonce):
    """该 nonce 是否已收到 pong。"""
    with _pending_lock:
        return nonce in _ponged


def send_push_test():
    """手动测试：走真实 push 通道发一条测试消息，前端会弹桌面通知。"""
    push_event('push_test', {
        'title': '🔔 推送服务测试',
        'body': '看到这条桌面通知，说明 WebSocket 推送链路正常。',
        'time': datetime.now().strftime('%H:%M:%S'),
    })
