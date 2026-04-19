import time
import requests
from datetime import datetime
from logger import setup_logging
from config import load_monitor_config

error_logger, system_logger, _ = setup_logging()

_last_restart_time = {}
_last_config_reload = 0
CONFIG_RELOAD_INTERVAL = 300

def get_current_config():
    global _last_config_reload
    return load_monitor_config()

def check_health(api_base_url):
    try:
        health_check_url = f"{api_base_url}/health"
        response = requests.get(health_check_url, timeout=5)
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

def restart_thread(thread_name, restart_url, restart_cooldown):
    global _last_restart_time
    
    now = time.time()
    last_restart = _last_restart_time.get(thread_name, 0)
    
    if now - last_restart < restart_cooldown:
        system_logger.info(f"[监控] 重启冷却中，跳过 {thread_name}")
        return False
    
    _last_restart_time[thread_name] = now
    
    try:
        system_logger.info(f"[监控] 尝试重启线程: {thread_name}, URL: {restart_url}")
        response = requests.post(
            restart_url, 
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

def wait_for_backend(api_base_url, max_wait=60):
    health_check_url = f"{api_base_url}/health"
    system_logger.info(f"等待后端服务启动...")
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        try:
            response = requests.get(health_check_url, timeout=5)
            if response.status_code == 200:
                system_logger.info("后端服务已就绪")
                return True
        except:
            pass
        time.sleep(2)
    
    system_logger.warning(f"等待后端超时({max_wait}秒)，继续启动监控...")
    return False

def monitor_loop():
    config = get_current_config()
    api_base_url = config['api_base_url']
    check_interval = config['check_interval']
    alert_threshold = config['alert_threshold']
    restart_cooldown = config['restart_cooldown']
    
    restart_url = f"{api_base_url}/api/system/restart"
    
    wait_for_backend(api_base_url)
    system_logger.info(f"监控进程启动，监控地址: {api_base_url}")
    
    last_config_reload = time.time()
    
    while True:
        try:
            if time.time() - last_config_reload >= CONFIG_RELOAD_INTERVAL:
                new_config = get_current_config()
                if new_config != config:
                    config = new_config
                    api_base_url = config['api_base_url']
                    check_interval = config['check_interval']
                    alert_threshold = config['alert_threshold']
                    restart_cooldown = config['restart_cooldown']
                    restart_url = f"{api_base_url}/api/system/restart"
                    system_logger.info(f"[监控] 配置已重新加载")
                last_config_reload = time.time()
            
            health_data = check_health(api_base_url)
            
            if not health_data:
                system_logger.error("无法获取健康状态")
                time.sleep(check_interval)
                continue
            
            threads = health_data.get('threads', {})
            
            for thread_name, thread_info in threads.items():
                status = thread_info.get('status', 'unknown')
                elapsed = thread_info.get('elapsed', 0)
                alive = thread_info.get('alive', False)
                
                if not alive or status == 'stopped':
                    error_logger.critical(f"[监控] 线程 {thread_name} 已停止运行，状态: {status}, 尝试重启...")
                    restart_thread(thread_name, restart_url, restart_cooldown)
                elif elapsed > alert_threshold:
                    error_logger.critical(f"[监控] 线程 {thread_name} 心跳超时，已持续 {elapsed} 秒，尝试重启...")
                    restart_thread(thread_name, restart_url, restart_cooldown)
            
        except Exception as e:
            error_logger.error(f"监控循环异常: {e}")
        
        time.sleep(check_interval)

if __name__ == '__main__':
    config = get_current_config()
    print("StockRank 线程监控服务启动")
    print(f"监控地址: {config['api_base_url']}")
    print(f"检查间隔: {config['check_interval']}秒")
    print(f"告警阈值: {config['alert_threshold']}秒")
    print("按 Ctrl+C 停止\n")
    
    try:
        monitor_loop()
    except KeyboardInterrupt:
        print("\n监控服务已停止")
