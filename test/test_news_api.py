import sys
import os
import warnings
import requests
import time

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

from config import NEWS_URL

print("="*60)
print("测试同花顺新闻API")
print(f"URL: {NEWS_URL}")
print("="*60)

params = {
    'page': 1,
    'tag': '',
    'track': 'website',
    'pagesize': 10
}

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Referer': 'https://news.10jqka.com.cn/',
}

print("\n尝试1: 使用简单请求头...")
start_time = time.time()
try:
    session = requests.Session()
    session.trust_env = False
    response = session.get(NEWS_URL, params=params, headers=headers, timeout=30, verify=False)
    response_time = round((time.time() - start_time) * 1000, 2)
    print(f"状态码: {response.status_code}")
    print(f"响应时间: {response_time}ms")
    if response.status_code == 200:
        data = response.json()
        print(f"返回数据: {str(data)[:200]}...")
        print("测试成功!")
    else:
        print(f"响应内容: {response.text[:200]}")
except Exception as e:
    response_time = round((time.time() - start_time) * 1000, 2)
    print(f"错误: {e}")
    print(f"响应时间: {response_time}ms")

print("\n尝试2: 不使用verify...")
start_time = time.time()
try:
    response = requests.get(NEWS_URL, params=params, headers=headers, timeout=30)
    response_time = round((time.time() - start_time) * 1000, 2)
    print(f"状态码: {response.status_code}")
    print(f"响应时间: {response_time}ms")
    if response.status_code == 200:
        print("测试成功!")
except Exception as e:
    response_time = round((time.time() - start_time) * 1000, 2)
    print(f"错误: {e}")
    print(f"响应时间: {response_time}ms")

print("\n" + "="*60)
