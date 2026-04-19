import time
import requests
from datetime import datetime
from logger import setup_logging
from config import load_monitor_config

error_logger, system_logger, _ = setup_logging()

config = load_monitor_config()
API_BASE_URL = config['api_base_url']
CHECK_INTERVAL = config['check_interval']
ALERT_THRESHOLD = config['alert_threshold']
RESTART_COOLDOWN = config['restart_cooldown']

HEALTH_CHECK_URL = f"{API_BASE_URL}/health"
RESTART_URL = f"{API_BASE_URL}/api/system/restart"

_last_restart_time = {}

def check_health():
    try:
        response = requests.get(HEALTH_CHECK_URL, timeout=5)
        if response.status_code == 200:
            try:
                return response.json()
            except Exception as json_err:
                error_logger.error(f"健康检查返回非JSON: {response.text[:200]}")
                return None
        else:
            error_logger.error(f"健康检查失败: HTTP {response.status_code}, {response.text[:200]}")
            return None
    except Exception as e:
        error_logger.error(f"健康检查请求失败: {e}")
        return None

def restart_thread(thread_name):
    global _last_restart_time
    
    now = time.time()
    last_restart = _last_restart_time.get(thread_name, 0)
    
    if now - last_restart < RESTART_COOLDOWN:
        system_logger.info(f"[监控] 重启冷却中，跳过 {thread_name}")
        return False
    
    _last_restart_time[thread_name] = now
    
    try:
        system_logger.info(f"[监控] 尝试重启线程: {thread_name}, URL: {RESTART_URL}")
        response = requests.post(
            RESTART_URL, 
            json={"thread": thread_name}, 
            timeout=10,
            headers={'Content-Type': 'application/json'}
        )
        if response.status_code == 200:
            system_logger.info(f"[监控] 成功重启线程: {thread_name}")
            return True
        else:
            error_logger.error(f"[监控] 重启线程失败: {thread_name}, HTTP {response.status_code}, 响应: {response.text[:200]}")
            return False
    except Exception as e:
        error_logger.error(f"[监控] 重启线程请求失败: {thread_name}, 错误: {e}")
        return False

def wait_for_backend(max_wait=60):
    system_logger.info(f"等待后端服务启动...")
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        try:
            response = requests.get(HEALTH_CHECK_URL, timeout=5)
            if response.status_code == 200:
                system_logger.info("后端服务已就绪")
                return True
        except:
            pass
        time.sleep(2)
    
    system_logger.warning(f"等待后端超时({max_wait}秒)，继续启动监控...")
    return False

def monitor_loop():
    wait_for_backend()
    system_logger.info(f"监控进程启动，监控地址: {API_BASE_URL}")
    
    while True:
        try:
            health_data = check_health()
            
            if not health_data:
                system_logger.error("无法获取健康状态")
                time.sleep(CHECK_INTERVAL)
                continue
            
            threads = health_data.get('threads', {})
            
            for thread_name, thread_info in threads.items():
                status = thread_info.get('status', 'unknown')
                elapsed = thread_info.get('elapsed', 0)
                alive = thread_info.get('alive', False)
                
                if not alive or status == 'stopped':
                    error_logger.critical(f"[监控] 线程 {thread_name} 已停止运行，状态: {status}, 尝试重启...")
                    restart_thread(thread_name)
                elif elapsed > ALERT_THRESHOLD:
                    error_logger.critical(f"[监控] 线程 {thread_name} 心跳超时，已持续 {elapsed} 秒，尝试重启...")
                    restart_thread(thread_name)
            
        except Exception as e:
            error_logger.error(f"监控循环异常: {e}")
        
        time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    print("StockRank 线程监控服务启动")
    print(f"监控地址: {API_BASE_URL}")
    print(f"检查间隔: {CHECK_INTERVAL}秒")
    print(f"告警阈值: {ALERT_THRESHOLD}秒")
    print("按 Ctrl+C 停止\n")
    
    try:
        monitor_loop()
    except KeyboardInterrupt:
        print("\n监控服务已停止")
