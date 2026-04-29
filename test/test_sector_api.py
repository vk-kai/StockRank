import sys
sys.path.append('c:/Users/Administrator/Desktop/python项目/股票资金走势/StockRank/backend')

import requests
import data_processor
from data_processor import get_sector_flow_data, get_random_user_agent

print("=" * 60)
print("测试板块个股数据获取")
print("=" * 60)

print("\n1. 获取板块数据...")
get_sector_flow_data()
print(f"   latest_data: {len(data_processor.latest_data)} 个板块")

if data_processor.latest_data:
    sector_name = "电池"
    sector_code = None
    
    for item in data_processor.latest_data:
        if item.get('name') == sector_name:
            sector_code = item.get('code', '')
            break
    
    print(f"\n2. 找到板块 '{sector_name}' 的代码: {sector_code}")
    
    if sector_code:
        print("\n3. 请求个股数据...")
        
        SECTOR_STOCKS_URL = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            'fid': 'f62',
            'po': '1',
            'pz': '50',
            'pn': '1',
            'np': '1',
            'fltt': '2',
            'invt': '2',
            'ut': '8dec03ba335b81bf4ebdf7b29ec27d15',
            'fs': f'b:{sector_code}',
            'fields': 'f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f124,f1,f13'
        }
        
        headers = {
            'User-Agent': get_random_user_agent(),
            'Referer': 'https://data.eastmoney.com/',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        
        try:
            response = requests.get(SECTOR_STOCKS_URL, params=params, headers=headers, timeout=15)
            print(f"   HTTP状态码: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and 'diff' in data['data']:
                    stocks = data['data']['diff']
                    print(f"   [OK] 成功获取 {len(stocks)} 只个股")
                    
                    print("\n   前3只个股:")
                    for i, item in enumerate(stocks[:3]):
                        print(f"   {i+1}. {item.get('f14')} ({item.get('f12')})")
                else:
                    print(f"   [FAIL] 数据格式异常: {data}")
            else:
                print(f"   [FAIL] HTTP错误: {response.status_code}")
                
        except Exception as e:
            print(f"   [FAIL] 请求异常: {e}")
else:
    print("   [FAIL] 无法获取板块数据")
