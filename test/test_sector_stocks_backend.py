import sys
import os

# 添加后端路径
sys.path.append(os.path.join(os.path.dirname(__file__), '../backend'))

from routes.flow_routes import get_sector_stocks
from flask import Flask, request

app = Flask(__name__)

def test_backend_sector_stocks():
    print("测试后端接口 /api/flow/sector-stocks")
    print("=" * 100)
    
    # 模拟请求
    with app.test_request_context('/api/flow/sector-stocks?code=BK1033'):
        try:
            response = get_sector_stocks()
            print(f"响应状态码: {response.status_code}")
            print(f"响应内容: {response.get_json()}")
            
            if response.get_json()['success']:
                data = response.get_json()['data']
                print(f"\n板块名称: {data['sector_name']}")
                print(f"板块代码: {data['sector_code']}")
                print(f"个股数量: {data['total']}")
                print("\n前3只个股:")
                for i, stock in enumerate(data['stocks'][:3]):
                    print(f"{i+1}. {stock['name']} ({stock['code']})")
                    print(f"   现价: {stock['price']} 元")
                    print(f"   涨跌幅: {stock['change_percent']*100:.2f}%")
                    print(f"   主力净流入: {stock['main_flow']:,.0f} 元")
                    print()
        except Exception as e:
            print(f"测试失败: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    test_backend_sector_stocks()