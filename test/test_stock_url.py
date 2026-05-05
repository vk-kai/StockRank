import sys
import os
import warnings
import requests
from bs4 import BeautifulSoup

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

from config import THS_SECTOR_URL
from data_processor import generate_random_headers

print("="*60)
print("测试提取板块详情URL并检测个股数据")
print(f"URL: {THS_SECTOR_URL}")
print("="*60)

headers = generate_random_headers()

try:
    session = requests.Session()
    session.trust_env = False
    response = session.get(THS_SECTOR_URL, headers=headers, timeout=15, verify=False)
    
    if response.status_code == 200:
        if response.encoding == 'ISO-8859-1':
            response.encoding = 'GBK'
        
        soup = BeautifulSoup(response.text, 'html.parser')
        table = soup.find('table', class_='m-table J-ajax-table')
        
        if table:
            tbody = table.find('tbody')
            if tbody:
                rows = tbody.find_all('tr')
                first_row = rows[0]
                cols = first_row.find_all('td')
                
                print(f"\n第一行有 {len(cols)} 列:")
                for i, col in enumerate(cols):
                    text = col.get_text(strip=True)
                    print(f"  cols[{i}]: '{text}'")
                    link = col.find('a')
                    if link:
                        href = link.get('href', '')
                        print(f"    -> link: {href}")
                
                sector_link = cols[1].find('a')
                if sector_link:
                    sector_url = sector_link.get('href', '')
                    if sector_url.startswith('http://'):
                        sector_url = sector_url.replace('http://', 'https://')
                    print(f"\n提取的板块详情URL: {sector_url}")
                    
                    print("\n测试访问板块详情URL获取个股数据...")
                    test_headers = generate_random_headers()
                    test_resp = session.get(sector_url, headers=test_headers, timeout=10, verify=False)
                    print(f"状态码: {test_resp.status_code}")
                    if test_resp.status_code == 200:
                        if test_resp.encoding == 'ISO-8859-1':
                            test_resp.encoding = 'GBK'
                        if 'm-table' in test_resp.text or '个股' in test_resp.text:
                            print("内容正常: 包含个股数据")
                        else:
                            print("内容异常: 不包含个股数据")
                            print(f"内容长度: {len(test_resp.text)}")
                else:
                    print("未找到板块链接")
        else:
            print("未找到表格")
    else:
        print(f"请求失败: HTTP {response.status_code}")
        
except Exception as e:
    print(f"错误: {e}")

print("\n" + "="*60)
