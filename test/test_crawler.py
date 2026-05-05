import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import json
import time
from backend.data_processor import generate_random_headers
from backend.config import NEWS_URL

THS_SECTOR_URL = "https://data.10jqka.com.cn/funds/hyzjl/field/tradezdf/order/desc/ajax/1/"
THS_STOCKS_URL = "https://q.10jqka.com.cn/gn/detail/code/301466/"

def print_headers(headers):
    print("请求头详情:")
    for key, value in headers.items():
        if key == 'Cookie':
            print(f"  {key}: {value[:60]}...")
        elif key == 'User-Agent':
            print(f"  {key}: {value[:70]}...")
        else:
            print(f"  {key}: {value}")

def test_ths_sector():
    print("\n" + "="*60)
    print("测试同花顺板块资金接口")
    print("="*60)
    
    for i in range(3):
        print(f"\n--- 第 {i+1} 次尝试 ---")
        headers = generate_random_headers()
        print_headers(headers)
        
        try:
            session = requests.Session()
            session.trust_env = False
            start_time = time.time()
            response = session.get(THS_SECTOR_URL, headers=headers, timeout=15, verify=False)
            response_time = round((time.time() - start_time) * 1000, 2)
            
            print(f"\nHTTP状态码: {response.status_code}")
            print(f"响应时间: {response_time}ms")
            
            if response.status_code == 200:
                if response.encoding == 'ISO-8859-1':
                    response.encoding = 'GBK'
                else:
                    response.encoding = response.apparent_encoding
                
                content = response.text[:500]
                if '板块' in content or '资金' in content:
                    print("✅ 成功获取板块数据")
                    print(f"内容预览: {content[:200]}...")
                    return True
                else:
                    print("❌ 页面内容异常，未找到板块数据")
                    print(f"内容预览: {content[:200]}...")
            else:
                print(f"❌ HTTP错误: {response.status_code}")
        except Exception as e:
            print(f"❌ 请求异常: {e}")
        
        time.sleep(1)
    
    return False

def test_ths_stocks():
    print("\n" + "="*60)
    print("测试同花顺个股详情接口")
    print("="*60)
    
    for i in range(3):
        print(f"\n--- 第 {i+1} 次尝试 ---")
        headers = generate_random_headers(host='q.10jqka.com.cn', referer=THS_STOCKS_URL)
        print_headers(headers)
        
        try:
            session = requests.Session()
            session.trust_env = False
            start_time = time.time()
            response = session.get(THS_STOCKS_URL, headers=headers, timeout=15, verify=False)
            response_time = round((time.time() - start_time) * 1000, 2)
            
            print(f"\nHTTP状态码: {response.status_code}")
            print(f"响应时间: {response_time}ms")
            
            if response.status_code == 200:
                if response.encoding == 'ISO-8859-1':
                    response.encoding = 'GBK'
                else:
                    response.encoding = response.apparent_encoding
                
                content = response.text[:500]
                if '股票' in content or '涨跌' in content:
                    print("✅ 成功获取个股数据")
                    print(f"内容预览: {content[:200]}...")
                    return True
                else:
                    print("❌ 页面内容异常，未找到个股数据")
                    print(f"内容预览: {content[:200]}...")
            else:
                print(f"❌ HTTP错误: {response.status_code}")
        except Exception as e:
            print(f"❌ 请求异常: {e}")
        
        time.sleep(1)
    
    return False

def test_news():
    print("\n" + "="*60)
    print("测试同花顺新闻接口")
    print("="*60)
    
    for i in range(3):
        print(f"\n--- 第 {i+1} 次尝试 ---")
        
        headers = {
            'User-Agent': f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': 'https://news.10jqka.com.cn/',
        }
        print(f"User-Agent: {headers['User-Agent']}")
        
        params = {
            'page': 1,
            'tag': '',
            'track': 'website',
            'pagesize': 10
        }
        
        try:
            session = requests.Session()
            session.trust_env = False
            start_time = time.time()
            response = session.get(NEWS_URL, params=params, headers=headers, timeout=15, verify=False)
            response_time = round((time.time() - start_time) * 1000, 2)
            
            print(f"HTTP状态码: {response.status_code}")
            print(f"响应时间: {response_time}ms")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    if isinstance(data, dict) and 'data' in data:
                        news_list = data['data'].get('list', [])
                        print(f"✅ 成功获取新闻数据，共 {len(news_list)} 条")
                        if news_list:
                            print(f"第一条新闻: {news_list[0].get('title', 'N/A')}")
                        return True
                    elif isinstance(data, list):
                        print(f"✅ 成功获取新闻数据，共 {len(data)} 条")
                        if data:
                            print(f"第一条新闻: {data[0].get('title', 'N/A')}")
                        return True
                    else:
                        print(f"❌ 新闻数据格式异常")
                        print(f"返回数据类型: {type(data)}")
                        print(f"返回数据: {str(data)[:200]}...")
                except json.JSONDecodeError as e:
                    print(f"❌ JSON解析失败: {e}")
                    print(f"返回内容: {response.text[:200]}...")
            else:
                print(f"❌ HTTP错误: {response.status_code}")
        except Exception as e:
            print(f"❌ 请求异常: {e}")
        
        time.sleep(1)
    
    return False

def main():
    print("\n" + "#"*60)
    print("# StockRank 爬虫测试脚本")
    print("#"*60)
    
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    results = {
        '板块资金': test_ths_sector(),
        '个股详情': test_ths_stocks(),
        '新闻': test_news()
    }
    
    print("\n" + "="*60)
    print("测试结果汇总")
    print("="*60)
    for name, success in results.items():
        status = "✅ 成功" if success else "❌ 失败"
        print(f"{name}: {status}")
    
    all_success = all(results.values())
    if all_success:
        print("\n🎉 所有测试通过！")
    else:
        print("\n⚠️ 部分测试失败，请检查网络或请求头")
    
    return all_success

if __name__ == '__main__':
    main()
