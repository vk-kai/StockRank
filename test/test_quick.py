import sys
sys.path.append('c:/Users/Administrator/Desktop/python项目/股票资金走势/StockRank/backend')

import data_processor
from data_processor import get_sector_flow_data

print("测试 get_sector_flow_data()...")
data = get_sector_flow_data()
print(f"获取到 {len(data)} 个板块")

if data:
    print("\n前10个板块:")
    for d in data[:10]:
        print(f"  {d['name']} (代码: {d['code']})")
    
    print("\n检查是否有'电池'板块:")
    for d in data:
        if '电池' in d['name']:
            print(f"  找到: {d['name']} (代码: {d['code']})")
else:
    print("未能获取数据!")

print(f"\ndata_processor.latest_data 变量: {len(data_processor.latest_data)} 个板块")

print("\n模拟 flow_routes.py 的逻辑:")
print(f"  data_processor.latest_data 是否为空: {not data_processor.latest_data}")
if data_processor.latest_data:
    print(f"  第一个板块: {data_processor.latest_data[0]['name']} ({data_processor.latest_data[0]['code']})")
