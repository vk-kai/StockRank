import sys
import os
import warnings
import requests

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

from data_processor import generate_random_headers

SECTOR_URL = "https://q.10jqka.com.cn/thshy/detail/code/881267/"

print("="*60)
print("测试板块详情URL")
print(f"URL: {SECTOR_URL}")
print("="*60)

headers = generate_random_headers(host='q.10jqka.com.cn')

print(f"\n请求头:")
for k, v in headers.items():
    print(f"  {k}: {v}")

try:
    session = requests.Session()
    session.trust_env = False
    response = session.get(SECTOR_URL, headers=headers, timeout=15, verify=False)
    
    print(f"\n状态码: {response.status_code}")
    if response.status_code == 200:
        if response.encoding == 'ISO-8859-1':
            response.encoding = 'GBK'
        text = response.text
        if 'm-table' in text or '个股' in text:
            print("内容正常: 包含个股数据")
        else:
            print("内容异常: 不包含个股数据")
            print(f"内容长度: {len(text)}")
    else:
        print(f"请求失败: HTTP {response.status_code}")
        
except Exception as e:
    print(f"错误: {e}")

print("\n" + "="*60)
