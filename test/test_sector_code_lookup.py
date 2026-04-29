import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '../backend'))

from data_processor import get_sector_flow_data, latest_data
import requests
import json

SECTOR_STOCKS_URL = "https://push2.eastmoney.com/api/qt/clist/get"

def test_step1_get_sector_code():
    print("=" * 80)
    print("第一步：验证根据板块名称获取板块代码")
    print("=" * 80)
    
    print("\n1.1 先获取板块资金数据...")
    data = get_sector_flow_data()
    
    if not data:
        print("[FAIL] 获取板块资金数据失败！")
        return None, None
    
    print(f"[OK] 成功获取 {len(data)} 个板块数据")
    
    print("\n1.2 查找板块名称对应的代码...")
    test_sector_name = "电池"
    
    sector_code = None
    for item in data:
        if item.get('name') == test_sector_name:
            sector_code = item.get('code', '')
            print(f"[OK] 找到板块 '{test_sector_name}' 的代码: {sector_code}")
            break
    
    if not sector_code:
        print(f"[FAIL] 未找到板块 '{test_sector_name}' 对应的代码")
        print("\n可用的板块名称列表（前10个）:")
        for item in data[:10]:
            print(f"  - {item.get('name')} (代码: {item.get('code')})")
        return None, None
    
    return test_sector_name, sector_code


def test_step2_get_sector_stocks(sector_name, sector_code):
    print("\n" + "=" * 80)
    print("第二步：验证拼接URL获取个股信息")
    print("=" * 80)
    
    if not sector_code:
        print("[FAIL] 板块代码为空，无法继续测试")
        return
    
    print(f"\n2.1 构建请求URL...")
    print(f"   板块名称: {sector_name}")
    print(f"   板块代码: {sector_code}")
    
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
    
    from urllib.parse import urlencode
    full_url = f"{SECTOR_STOCKS_URL}?{urlencode(params)}"
    print(f"\n   完整URL:\n   {full_url}")
    
    print(f"\n2.2 发送请求获取个股数据...")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://data.eastmoney.com/',
    }
    
    try:
        response = requests.get(SECTOR_STOCKS_URL, params=params, headers=headers, timeout=15)
        print(f"   HTTP状态码: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            if 'data' in data and 'diff' in data['data']:
                stocks = data['data']['diff']
                print(f"[OK] 成功获取 {len(stocks)} 只个股")
                
                print("\n   前5只个股信息:")
                for i, item in enumerate(stocks[:5]):
                    code = item.get('f12', '')
                    name = item.get('f14', '')
                    price = item.get('f2', 0)
                    change = item.get('f3', 0)
                    main_flow = item.get('f62', 0)
                    
                    print(f"   {i+1}. {name} ({code})")
                    print(f"      现价: {price} 元")
                    print(f"      涨跌幅: {change/100 if change else 0:.2f}%")
                    print(f"      主力净流入: {main_flow:,.0f} 元")
                
                return True
            else:
                print(f"[FAIL] 返回数据格式异常: {data}")
                return False
        else:
            print(f"[FAIL] HTTP请求失败，状态码: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"[FAIL] 请求异常: {e}")
        return False


def test_step3_api_endpoint():
    print("\n" + "=" * 80)
    print("第三步：验证后端API接口（传入sector参数）")
    print("=" * 80)
    
    test_sector = "电池"
    
    print(f"\n3.1 直接请求 API /api/flow/sector-stocks?sector={test_sector}")
    
    try:
        response = requests.get(
            "http://127.0.0.1:5001/api/flow/sector-stocks",
            params={"sector": test_sector},
            timeout=30
        )
        
        print(f"   HTTP状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   success: {result.get('success')}")
            
            if result.get('success'):
                data = result.get('data', {})
                print(f"   板块名称: {data.get('sector_name')}")
                print(f"   板块代码: {data.get('sector_code')}")
                print(f"   个股数量: {data.get('total')}")
                
                print("\n   [OK] API接口测试成功！")
                return True
            else:
                print(f"   [FAIL] API返回失败: {result.get('message')}")
                return False
        else:
            print(f"   [FAIL] HTTP请求失败")
            print(f"   响应内容: {response.text[:500]}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("   [SKIP] 后端服务未启动，跳过此测试")
        print("   请先启动后端服务: python backend/app.py")
        return None
    except Exception as e:
        print(f"   [FAIL] 测试异常: {e}")
        return False


def main():
    print("\n" + "#" * 80)
    print("# 板块个股数据获取测试")
    print("#" * 80)
    
    sector_name, sector_code = test_step1_get_sector_code()
    
    if sector_code:
        test_step2_get_sector_stocks(sector_name, sector_code)
    
    test_step3_api_endpoint()
    
    print("\n" + "#" * 80)
    print("# 测试完成")
    print("#" * 80)


if __name__ == "__main__":
    main()
