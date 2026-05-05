import sys
import os
import warnings
import json

warnings.filterwarnings('ignore')

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'backend'))

from health_checker import run_health_check, get_health_status

print("="*60)
print("测试健康检测流程")
print("="*60)

result = run_health_check()

print("\n检测结果:")
print(f"  同花顺新闻: {'成功' if result['news'] else '失败'}")
print(f"  同花顺板块资金: {'成功' if result['sector'] else '失败'}")
print(f"  同花顺个股详情: {'成功' if result['stocks'] else '失败'}")

print("\n健康状态详情:")
status = get_health_status()
print(json.dumps(status, ensure_ascii=False, indent=2))

print("\n" + "="*60)
print("测试完成")
print("="*60)
