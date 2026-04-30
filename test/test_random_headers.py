import requests
import random
import string
from datetime import datetime
import json

# 复制自 data_processor.py 的请求头生成算法
def _generate_random_string(length):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def _generate_random_cookie():
    timestamp = int(datetime.now().timestamp())
    random_hash = ''.join(random.choices('ABCDEF0123456789', k=16))
    jsluid = ''.join(random.choices('ABCDEF0123456789', k=32))
    qgqp_b_id = _generate_random_string(20)
    ct_identifier = _generate_random_string(36)
    hm_lvt_1 = f'{timestamp - random.randint(100, 500)}'
    hm_lvt_2 = f'{timestamp - random.randint(100, 500)}'
    hm_lpvt_1 = f'{timestamp}'
    hm_lpvt_2 = f'{timestamp}'
    v_random = _generate_random_string(40)
    vvvv = random.randint(1, 1000)
    
    return f'__jsluid_s={jsluid}; qgqp_b_id={qgqp_b_id}; ct_identifier={ct_identifier}; vvvv={vvvv}; Hm_lvt_6dc19a3987135225beb977a0b9931a25={hm_lvt_1}; HMACCOUNT={random_hash}; Hm_lvt_9d25c03aef06fec6abea265b79509ba4={hm_lvt_2}; Hm_lpvt_6dc19a3987135225beb977a0b9931a25={hm_lpvt_1}; Hm_lpvt_9d25c03aef06fec6abea265b79509ba4={hm_lpvt_2}; v={v_random}'

def _generate_random_browser_version():
    major = random.randint(120, 130)
    minor = 0
    patch = random.randint(1000, 9999)
    build = random.randint(10, 200)
    return f'{major}.{minor}.{patch}.{build}'

def generate_random_headers(host=None, referer=None):
    browsers = ['Edge', 'Chrome']
    browser = random.choice(browsers)
    
    browser_version = _generate_random_browser_version()
    major_version = browser_version.split('.')[0]
    
    cookie = _generate_random_cookie()
    
    if browser == 'Edge':
        sec_ch_ua = f'"Microsoft Edge";v="{major_version}", "Not.A/Brand";v="8", "Chromium";v="{major_version}"'
        user_agent = f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{browser_version} Safari/537.36 Edg/{browser_version}'
    else:
        sec_ch_ua = f'"Chromium";v="{major_version}", "Google Chrome";v="{major_version}", "Not-A.Brand";v="99"'
        user_agent = f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{browser_version} Safari/537.36'
    
    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Cache-Control': 'max-age=0',
        'Connection': 'keep-alive',
        'Cookie': cookie,
        'Host': host or 'data.10jqka.com.cn',
        'sec-ch-ua': sec_ch_ua,
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'document',
        'sec-fetch-mode': 'navigate',
        'sec-fetch-site': 'none',  # 首次访问时使用 none
        'sec-fetch-user': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': user_agent
    }
    
    if referer:
        headers['Referer'] = referer
        headers['sec-fetch-site'] = 'same-site'  # 有Referer时使用 same-site
    
    return headers

def print_headers(headers):
    print("\n生成的请求头:")
    for key, value in headers.items():
        if key == 'Cookie':
            print(f"  {key}: {value[:60]}...")
        elif key == 'User-Agent':
            print(f"  {key}: {value}")
        else:
            print(f"  {key}: {value}")

def test_request(url, headers):
    print(f"\n测试URL: {url}")
    
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(url, headers=headers, timeout=10, verify=False)
        print(f"返回状态码: {response.status_code}")
        
        # 处理JavaScript重定向
        if response.status_code == 200 and '<script' in response.text and 'window.location.href' in response.text:
            import re
            match = re.search(r'window.location.href="(.*?)";', response.text)
            if match:
                redirect_url = match.group(1)
                print(f"发现重定向: {redirect_url}")
                if not redirect_url.startswith('http'):
                    redirect_url = f'https:{redirect_url}' if redirect_url.startswith('//') else f'https://data.10jqka.com.cn{redirect_url}'
                # 跟随重定向
                response = session.get(redirect_url, headers=headers, timeout=10, verify=False)
                print(f"重定向后状态码: {response.status_code}")
                if response.status_code == 200:
                    print("重定向成功!")
        
        # 打印响应头和部分内容
        if response.status_code != 200:
            print(f"响应头: {dict(response.headers)}")
            print(f"响应内容前500字符: {response.text[:500]}")
        
        return response.status_code
    except Exception as e:
        print(f"请求异常: {e}")
        return None

def main():
    print("="*80)
    print("随机请求头测试脚本")
    print("="*80)
    
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # 测试板块资金接口
    print("\n--- 测试板块资金接口 ---")
    ths_sector_url = "https://data.10jqka.com.cn/funds/hyzjl/field/tradezdf/order/desc/ajax/1/"
    headers = generate_random_headers(host='data.10jqka.com.cn')
    print_headers(headers)
    status_code = test_request(ths_sector_url, headers)
    
    # 测试个股详情接口
    print("\n--- 测试个股详情接口 ---")
    ths_stocks_url = "https://q.10jqka.com.cn/gn/detail/code/301466/"
    headers = generate_random_headers(host='q.10jqka.com.cn', referer=ths_stocks_url)
    print_headers(headers)
    status_code = test_request(ths_stocks_url, headers)
    
    # 测试新闻接口
    print("\n--- 测试新闻接口 ---")
    news_url = "https://news.10jqka.com.cn/tapp/news/push/stock/"
    headers = generate_random_headers(host='news.10jqka.com.cn', referer='https://news.10jqka.com.cn/')
    print_headers(headers)
    status_code = test_request(news_url, headers)
    
    print("\n" + "="*80)
    print("测试完成!")

if __name__ == '__main__':
    main()