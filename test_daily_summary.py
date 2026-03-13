#!/usr/bin/env python3
# 模拟一天结束后生成每日汇总的测试脚本

import sys
import os

# 添加backend目录到路径
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from data_processor import generate_daily_summary, load_daily_data
from datetime import datetime

def main():
    print("=== 模拟一天结束后生成每日汇总 ===")
    print(f"当前日期: {datetime.now().strftime('%Y-%m-%d')}")
    print()
    
    # 模拟生成每日汇总
    print("1. 生成每日汇总数据...")
    success = generate_daily_summary()
    
    if success:
        print("✅ 每日汇总生成成功！")
        print()
        
        # 加载生成的每日汇总数据
        today = datetime.now().strftime('%Y-%m-%d')
        daily_data = load_daily_data(today)
        
        if daily_data:
            print("2. 每日汇总数据:")
            print(f"   日期: {daily_data['date']}")
            print(f"   生成时间: {daily_data['timestamp']}")
            print(f"   板块数量: {len(daily_data['data'])}")
            print()
            print("   当日资金流入TOP10板块:")
            print("   ┌──────┬──────────────┬────────────┬───────────┐")
            print("   │ 排名 │ 板块名称    │ 净流入(万) │ 涨跌幅(%) │")
            print("   ├──────┼──────────────┼────────────┼───────────┤")
            
            for item in daily_data['data']:
                rank = item['rank']
                name = item['name']
                flow = item['flow']
                change = item['change'] * 100
                
                print(f"   │ {rank:4d} │ {name:12s} │ {flow:10.2f} │ {change:9.2f} │")
            
            print("   └──────┴──────────────┴────────────┴───────────┘")
        else:
            print("❌ 无法加载每日汇总数据")
    else:
        print("❌ 每日汇总生成失败")

if __name__ == "__main__":
    main()