import sys
import os

# 获取项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, 'backend'))

from feishu_pusher import send_feishu_message, push_daily_summary_feishu
from data_processor import get_top5_comparison_data
from datetime import datetime

print("=" * 50)
print("飞书推送测试脚本")
print("=" * 50)
print("\n请选择测试类型:")
print("1. 测试普通消息推送")
print("2. 测试每日汇总推送")
print("3. 退出")

choice = input("\n请输入选项 (1/2/3): ").strip()

if choice == '1':
    title = '突发：A股大盘暴跌超10% 两市超5000只个股跌停'
    news_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    content = news_time + '\n\n<font color="red">今日A股市场遭遇历史性暴跌，上证指数收盘大跌10.2%，深证成指暴跌11.5%，创业板指暴跌12.8%。两市超过5000只个股跌停，市场恐慌情绪蔓延。</font>\n\nA股遭遇历史性暴跌，超5000只个股跌停，受多重利空因素叠加影响'
    
    print(f"\n正在推送测试消息...")
    result = send_feishu_message(title, content, url='https://example.com/news/test')
    print('推送结果:', '成功' if result else '失败')
    
elif choice == '2':
    date_input = input("\n请输入日期 (格式: YYYY-MM-DD，默认今天): ").strip()
    if not date_input:
        date_input = datetime.now().strftime('%Y-%m-%d')
    
    period_input = input("请输入时段 (上午/下午，默认下午): ").strip()
    if not period_input:
        period_input = '下午'
    
    print(f"\n正在获取 {date_input} 的TOP5对比数据...")
    comparison_data = get_top5_comparison_data(date_input)
    
    if comparison_data:
        print(f"获取成功，共 {len(comparison_data['top5'])} 个板块")
        print("\nTOP5板块:")
        for item in comparison_data['top5']:
            print(f"  {item['rank']}. {item['name']} - 流入: {item['today_flow']:.2f}万")
        
        print(f"\n正在推送 {period_input} 汇总...")
        result = push_daily_summary_feishu(comparison_data, period=period_input)
        print('推送结果:', '成功' if result else '失败')
    else:
        print(f"获取 {date_input} 的数据失败，请检查是否有该日期的数据")
    
elif choice == '3':
    print("\n退出测试脚本")
else:
    print("\n无效选项")

print("\n" + "=" * 50)
