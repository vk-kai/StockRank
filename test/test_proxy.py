import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import requests
import json
import random
from logger import get_logger

system_logger = get_logger('system')
error_logger = get_logger('error')

PROXY_API_URL = "https://proxy.scdn.io/api/get_proxy.php"
DATA_URL = "https://push2.eastmoney.com/api/qt/clist/get"

def validate_proxy(proxy_url, timeout=5):
    """验证代理是否可用"""
    # 先测试百度
    test_url = "https://www.baidu.com"
    try:
        response = requests.get(test_url, proxies={'http': proxy_url, 'https': proxy_url}, 
                               timeout=timeout, verify=False, allow_redirects=True)
        if response.status_code == 200:
            print(f"[OK] 代理 {proxy_url} 验证通过")
            return True
        else:
            print(f"[FAIL] 代理 {proxy_url} 返回状态码: {response.status_code}")
            return False
    except Exception as e:
        print(f"[FAIL] 代理 {proxy_url} 验证失败: {e}")
        return False

def get_random_user_agent():
    """随机生成浏览器User-Agent"""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Safari/605.1.15'
    ]
    return random.choice(user_agents)

def validate_proxy_for_target(proxy_url, timeout=8):
    """验证代理是否能访问目标网站"""
    headers = {
        'User-Agent': get_random_user_agent(),
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': 'https://quote.eastmoney.com/',
        'X-Requested-With': 'XMLHttpRequest',
        'Connection': 'keep-alive',
        'Cache-Control': 'max-age=0'
    }
    
    params = {
        'pn': 1,
        'pz': 1,
        'po': 1,
        'np': 1,
        'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
        'fltt': 2,
        'invt': 2,
        'fid': 'f62',
        'fs': 'm:90+s:4',
        'fields': 'f1,f2,f3,f12,f13,f14'
    }
    
    try:
        # 先发送一个预热请求
        warmup_response = requests.get('https://quote.eastmoney.com/', headers=headers, 
                                      proxies={'http': proxy_url, 'https': proxy_url}, 
                                      timeout=timeout, verify=False, allow_redirects=True)
        
        # 等待随机时间
        time.sleep(random.uniform(0.5, 1.5))
        
        # 再发送数据请求
        response = requests.get(DATA_URL, params=params, headers=headers, 
                               proxies={'http': proxy_url, 'https': proxy_url}, 
                               timeout=timeout, verify=False, allow_redirects=True)
        
        if response.status_code == 200:
            if 'application/json' in response.headers.get('Content-Type', ''):
                print(f"[OK] 代理 {proxy_url} 可以访问目标网站并返回JSON")
                return True
            else:
                print(f"[WARN] 代理 {proxy_url} 返回非JSON内容")
                return False
        else:
            print(f"[FAIL] 代理 {proxy_url} 返回状态码: {response.status_code}")
            return False
    except Exception as e:
        print(f"[FAIL] 代理 {proxy_url} 访问目标网站失败: {e}")
        return False

def load_proxy_pool():
    try:
        response = requests.get(PROXY_API_URL, params={
            'protocol': 'https',
            'count': 10,  # 增加获取代理数量
            'country_code': 'CN'
        }, timeout=15)
        data = response.json()
        print(f"API响应: {json.dumps(data, indent=2)}")
        
        if data.get('code') == 200 and data.get('data', {}).get('proxies'):
            proxies = data['data']['proxies']
            proxy_pool = []
            
            print(f"\n开始验证 {len(proxies)} 个代理...")
            # 先验证HTTP版本
            for proxy in proxies:
                http_proxy = f'http://{proxy}'
                if validate_proxy(http_proxy):
                    # 降低验证门槛，只要能访问百度就加入代理池
                    proxy_pool.append(http_proxy)
                    print(f"[INFO] 代理 {http_proxy} 加入代理池（仅通过百度验证）")
            
            print(f"\n验证完成，共 {len(proxy_pool)} 个可用代理")
            return proxy_pool
        else:
            print(f"API返回异常: {data}")
            return []
    except Exception as e:
        print(f"获取代理失败: {e}")
        return []

def test_without_proxy():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    params = {
        'pn': 1,
        'pz': 10,
        'po': 1,
        'np': 1,
        'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
        'fltt': 2,
        'invt': 2,
        'fid': 'f62',
        'fs': 'm:90+s:4',
        'fields': 'f1,f2,f3,f12,f13,f14,f62,f66,f69,f72,f75,f78,f81,f84,f87,f124,f184,f204,f205,f206'
    }
    
    print("\n测试1: 直接请求（可能受本地代理影响）...")
    try:
        response = requests.get(DATA_URL, params=params, headers=headers, timeout=15, verify=False)
        print(f"状态码: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and 'diff' in data['data']:
                print(f"成功获取数据，共 {len(data['data']['diff'])} 条记录")
                return True
    except Exception as e:
        print(f"失败: {e}")
    
    print("\n测试2: 使用Session + trust_env=False（绕过本地代理）...")
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(DATA_URL, params=params, headers=headers, timeout=15, verify=False)
        print(f"状态码: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and 'diff' in data['data']:
                print(f"成功获取数据，共 {len(data['data']['diff'])} 条记录")
                return True
    except Exception as e:
        print(f"失败: {e}")
    
    return False

def test_fetch_data(proxy_pool):
    headers = {
        'User-Agent': get_random_user_agent(),
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': 'https://quote.eastmoney.com/',
        'X-Requested-With': 'XMLHttpRequest',
        'Connection': 'keep-alive',
        'Cache-Control': 'max-age=0'
    }
    
    params = {
        'pn': 1,
        'pz': 10,
        'po': 1,
        'np': 1,
        'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
        'fltt': 2,
        'invt': 2,
        'fid': 'f62',
        'fs': 'm:90+s:4',
        'fields': 'f1,f2,f3,f12,f13,f14,f62,f66,f69,f72,f75,f78,f81,f84,f87,f124,f184,f204,f205,f206'
    }
    
    max_retries = 3
    for retry in range(max_retries):
        try:
            proxy = random.choice(proxy_pool)
            proxies = {
                'http': proxy,
                'https': proxy
            }
            
            print(f"\n尝试 {retry+1}/{max_retries} 使用代理: {proxy}")
            response = requests.get(DATA_URL, params=params, headers=headers, proxies=proxies, timeout=15, verify=False, allow_redirects=True)
            print(f"状态码: {response.status_code}")
            print(f"响应内容前200字符: {response.text[:200]}")
            
            # 检查响应内容类型
            if 'application/json' not in response.headers.get('Content-Type', ''):
                print(f"警告: 响应不是JSON格式，Content-Type: {response.headers.get('Content-Type')}")
                # 尝试解析HTML看看是否有错误信息
                if response.status_code == 200 and '<html' in response.text[:100].lower():
                    print("可能被目标网站拦截，返回了HTML页面")
                continue
            
            response.raise_for_status()
            data = response.json()
            
            if 'data' in data and 'diff' in data['data']:
                print(f"成功获取数据，共 {len(data['data']['diff'])} 条记录")
                for item in data['data']['diff'][:3]:
                    print(f"  - {item.get('f14')}: 净流入 {item.get('f62')}, 涨跌幅 {item.get('f3')}")
                return True
            else:
                print(f"数据格式异常: {data}")
                
        except requests.exceptions.SSLError as e:
            print(f"SSL错误: {e}")
            print("可能是代理不支持HTTPS或SSL版本问题")
        except requests.exceptions.ConnectionError as e:
            print(f"连接错误: {e}")
            print("可能是代理不可用或网络问题")
        except json.JSONDecodeError as e:
            print(f"JSON解析错误: {e}")
            print("响应内容不是有效的JSON格式")
        except Exception as e:
            print(f"其他错误: {e}")
            
        if retry < max_retries - 1:
            print("重新获取代理...")
            proxy_pool = load_proxy_pool()
            if not proxy_pool:
                print("无法获取新代理")
                break
    
    return False

if __name__ == '__main__':
    print("=" * 50)
    print("测试代理获取和数据请求")
    print("=" * 50)
    
    print("\n先测试不使用代理:")
    success_direct = test_without_proxy()
    
    if success_direct:
        print("\n不使用代理可以直接访问!")
    else:
        print("\n不使用代理无法访问")
        print("\n尝试使用代理...")
        proxy_pool = load_proxy_pool()
        
        if proxy_pool:
            print("\n开始测试数据请求...")
            success = test_fetch_data(proxy_pool)
            if success:
                print("\n[OK] 测试成功!")
            else:
                print("\n[FAIL] 测试失败")
        else:
            print("\n[FAIL] 无法获取代理")
