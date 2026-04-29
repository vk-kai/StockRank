import requests
import json
from datetime import datetime

# 测试URL
TEST_URL = "https://push2.eastmoney.com/api/qt/clist/get?fid=f62&po=1&pz=50&pn=1&np=1&fltt=2&invt=2&ut=8dec03ba335b81bf4ebdf7b29ec27d15&fs=b%3ABK1033&fields=f12%2Cf14%2Cf2%2Cf3%2Cf62%2Cf184%2Cf66%2Cf69%2Cf72%2Cf75%2Cf78%2Cf81%2Cf84%2Cf87%2Cf124%2Cf1%2Cf13"

# 模拟后端请求头
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://data.eastmoney.com/',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
}

def test_with_session():
    print(f"测试开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"测试URL: {TEST_URL}")
    print("=" * 100)
    print("使用 Session 方式测试...")
    
    session = requests.Session()
    session.trust_env = False  # 忽略环境变量中的代理设置
    
    try:
        response = session.get(TEST_URL, headers=headers, timeout=15, verify=False)
        print(f"响应状态码: {response.status_code}")
        print(f"响应时间: {response.elapsed.total_seconds():.2f} 秒")
        
        data = response.json()
        if 'data' in data and 'diff' in data['data']:
            print(f"成功获取 {len(data['data']['diff'])} 只个股")
            print("\n前3只个股:")
            for i, item in enumerate(data['data']['diff'][:3]):
                print(f"{i+1}. {item.get('f14', 'N/A')} ({item.get('f12', 'N/A')})")
        else:
            print("数据格式异常")
            print(json.dumps(data, ensure_ascii=False, indent=2)[:500])
            
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()
    
    print("=" * 100)

def test_without_session():
    print("\n使用直接 requests.get 方式测试...")
    print("=" * 100)
    
    try:
        response = requests.get(TEST_URL, headers=headers, timeout=15, verify=False)
        print(f"响应状态码: {response.status_code}")
        print(f"响应时间: {response.elapsed.total_seconds():.2f} 秒")
        
        data = response.json()
        if 'data' in data and 'diff' in data['data']:
            print(f"成功获取 {len(data['data']['diff'])} 只个股")
        else:
            print("数据格式异常")
            
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("=" * 100)

if __name__ == "__main__":
    test_with_session()
    test_without_session()
    print(f"\n测试结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")