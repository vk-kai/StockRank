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
print("测试板块数据解析")
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
                print(f"\n找到 {len(rows)} 行数据")
                
                if rows:
                    first_row = rows[0]
                    cols = first_row.find_all('td')
                    print(f"\n第一行有 {len(cols)} 列:")
                    
                    for i, col in enumerate(cols):
                        text = col.get_text(strip=True)
                        class_name = col.get('class', [])
                        print(f"  cols[{i}]: '{text}' (class: {class_name})")
                        
                        link = col.find('a')
                        if link:
                            print(f"    -> link: {link.get('href', '')}")
        else:
            print("未找到表格")
    else:
        print(f"请求失败: HTTP {response.status_code}")
        
except Exception as e:
    print(f"错误: {e}")

print("\n" + "="*60)
