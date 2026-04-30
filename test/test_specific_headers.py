import requests
import json
import time

# 测试的URL和请求头
TEST_URL = "https://data.10jqka.com.cn/funds/hyzjl/field/tradezdf/order/desc/ajax/1/"

TEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive",
    "Cookie": "Hm_lvt_6dc19a3987135225beb977a0b9931a25=1777540198; HMACCOUNT=77735FA95F21A988; Hm_lvt_9d25c03aef06fec6abea265b79509ba4=1777540445; Hm_lpvt_6dc19a3987135225beb977a0b9931a25=1777540678; Hm_lpvt_9d25c03aef06fec6abea265b79509ba4=1777540678; v=7cJ8AGBOP8chFpA3HwVx4CpUZXNLqUT4HCDnnL7y",
    "Host": "data.10jqka.com.cn",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-site",
    "sec-fetch-user": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.2407.76 Safari/537.36"
}

def print_request_details(url, headers):
    print("="*80)
    print("测试请求详情:")
    print(f"URL: {url}")
    print("\n请求头:")
    for key, value in headers.items():
        if key == 'Cookie':
            print(f"  {key}: {value[:80]}...")
        else:
            print(f"  {key}: {value}")
    print("="*80)

def test_request():
    print("\n开始测试请求...")
    
    try:
        session = requests.Session()
        session.trust_env = False
        
        start_time = time.time()
        response = session.get(TEST_URL, headers=TEST_HEADERS, timeout=15, verify=False, allow_redirects=True)
        response_time = round((time.time() - start_time) * 1000, 2)
        
        print(f"\n✅ 请求完成!")
        print(f"HTTP状态码: {response.status_code}")
        print(f"响应时间: {response_time}ms")
        print(f"响应大小: {len(response.content)} bytes")
        
        # 检查内容
        if response.status_code == 200:
            if response.encoding == 'ISO-8859-1':
                response.encoding = 'GBK'
            else:
                response.encoding = response.apparent_encoding
            
            content = response.text
            
            # 检查是否包含板块数据
            if '板块' in content and '资金' in content:
                print("\n✅ 页面包含板块资金数据!")
                
                # 提取表格部分
                table_start = content.find('<table')
                table_end = content.find('</table>')
                if table_start != -1 and table_end != -1:
                    table_content = content[table_start:table_end + 8]
                    print(f"\n表格内容预览:")
                    print(table_content[:500] + "...")
                    
                    # 统计板块数量
                    row_count = table_content.count('<tr')
                    print(f"\n表格行数: {row_count}")
            else:
                print("\n⚠️ 页面内容可能不包含板块资金数据")
                print(f"内容前500字符:")
                print(content[:500] + "...")
        
        return True
        
    except requests.exceptions.Timeout:
        print("\n❌ 请求超时!")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"\n❌ 连接错误: {e}")
        return False
    except requests.exceptions.HTTPError as e:
        print(f"\n❌ HTTP错误: {e}")
        return False
    except Exception as e:
        print(f"\n❌ 未知错误: {e}")
        return False

def main():
    print("\n" + "#"*80)
    print("# 特定请求头测试脚本")
    print("#"*80)
    
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    print_request_details(TEST_URL, TEST_HEADERS)
    
    success = test_request()
    
    if success:
        print("\n🎉 测试成功!")
    else:
        print("\n⚠️ 测试失败!")

if __name__ == '__main__':
    main()