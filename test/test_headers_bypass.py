import sys
import os
import time
import random
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import get_random_user_agent

SECTOR_API_URL = "https://push2.eastmoney.com/api/qt/clist/get"

BROWSER_USER_AGENTS = {
    'chrome_windows': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'chrome_mac': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'edge_windows': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0',
    'firefox_windows': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
    'safari_mac': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
}

SEC_CH_UA_TEMPLATES = {
    'chrome': '"Chromium";v="125", "Google Chrome";v="125", "Not.A/Brand";v="24"',
    'edge': '"Microsoft Edge";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
    'firefox': '',
    'safari': '',
}

COOKIES = [
    '',
    'qgqp_b_id=9849bf5ba6a612557a93f8f340e0b20a',
    'st_pvi=00084442657277; st_sp=2025-08-17%2023%3A35%3A44',
    'qgqp_b_id=9849bf5ba6a612557a93f8f340e0b20a; st_nvi=X0SuRmE-CSfugODoeQ9Ha5c08; st_pvi=00084442657277',
]

REFERERS = [
    'https://data.eastmoney.com/',
    'https://data.eastmoney.com/bkzj/hy.html',
    'https://quote.eastmoney.com/',
    'https://www.eastmoney.com/',
    '',
]

ACCEPT_TYPES = [
    'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'application/json, text/javascript, */*; q=0.01',
    '*/*',
    'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
]

ACCEPT_LANGUAGES = [
    'zh-CN,zh;q=0.9,en-GB;q=0.8,en;q=0.7,en-US;q=0.6',
    'zh-CN,zh;q=0.9',
    'en-US,en;q=0.9',
    'zh-CN',
]

def get_params():
    return {
        'pn': 1,
        'pz': 10,
        'po': 1,
        'np': 1,
        'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
        'fltt': 2,
        'invt': 2,
        'fid': 'f62',
        'fs': 'm:90+s:4',
        'fields': 'f12,f14,f62,f3'
    }

def build_headers(strategy, config):
    headers = {}
    
    if strategy == 'minimal':
        headers['User-Agent'] = config['ua']
        
    elif strategy == 'standard':
        headers['User-Agent'] = config['ua']
        headers['Accept'] = config['accept']
        headers['Accept-Language'] = config['lang']
        headers['Referer'] = config['referer']
        
    elif strategy == 'full':
        headers['User-Agent'] = config['ua']
        headers['Accept'] = config['accept']
        headers['Accept-Encoding'] = 'gzip, deflate, br'
        headers['Accept-Language'] = config['lang']
        headers['Cache-Control'] = 'max-age=0'
        headers['Connection'] = 'keep-alive'
        headers['Referer'] = config['referer']
        if config['cookie']:
            headers['Cookie'] = config['cookie']
        if config['sec_ch_ua']:
            headers['sec-ch-ua'] = config['sec_ch_ua']
            headers['sec-ch-ua-mobile'] = '?0'
            headers['sec-ch-ua-platform'] = '"Windows"'
        headers['Sec-Fetch-Dest'] = 'document'
        headers['Sec-Fetch-Mode'] = 'navigate'
        headers['Sec-Fetch-Site'] = 'none'
        headers['Sec-Fetch-User'] = '?1'
        headers['Upgrade-Insecure-Requests'] = '1'
        
    elif strategy == 'api_style':
        headers['User-Agent'] = config['ua']
        headers['Accept'] = 'application/json, text/plain, */*'
        headers['Accept-Encoding'] = 'gzip, deflate, br'
        headers['Accept-Language'] = config['lang']
        headers['Referer'] = config['referer']
        if config['cookie']:
            headers['Cookie'] = config['cookie']
            
    elif strategy == 'random_generated':
        headers['User-Agent'] = get_random_user_agent()
        headers['Accept'] = '*/*'
        headers['Accept-Language'] = 'zh-CN,zh;q=0.9'
        headers['Referer'] = 'https://data.eastmoney.com/'
        
    return headers

def test_request(headers, params, test_num, strategy):
    try:
        start_time = time.time()
        response = requests.get(SECTOR_API_URL, params=params, headers=headers, timeout=15)
        elapsed = time.time() - start_time
        
        status = response.status_code
        
        if status == 200:
            try:
                data = response.json()
                has_data = 'data' in data and 'diff' in data.get('data', {})
                sector_count = len(data.get('data', {}).get('diff', [])) if has_data else 0
                return {
                    'success': True,
                    'status': status,
                    'elapsed': elapsed,
                    'sector_count': sector_count,
                    'has_data': has_data
                }
            except:
                return {
                    'success': False,
                    'status': status,
                    'elapsed': elapsed,
                    'error': 'JSON解析失败'
                }
        else:
            return {
                'success': False,
                'status': status,
                'elapsed': elapsed,
                'error': f'HTTP {status}'
            }
    except Exception as e:
        return {
            'success': False,
            'status': None,
            'elapsed': 0,
            'error': str(e)
        }

def run_strategy_test(strategy, rounds=5):
    print(f"\n{'='*60}")
    print(f"策略: {strategy}")
    print(f"{'='*60}")
    
    results = []
    
    for i in range(rounds):
        ua_key = random.choice(list(BROWSER_USER_AGENTS.keys()))
        browser_type = 'chrome' if 'chrome' in ua_key else ('edge' if 'edge' in ua_key else ('firefox' if 'firefox' in ua_key else 'safari'))
        
        config = {
            'ua': BROWSER_USER_AGENTS[ua_key],
            'accept': random.choice(ACCEPT_TYPES),
            'lang': random.choice(ACCEPT_LANGUAGES),
            'referer': random.choice(REFERERS),
            'cookie': random.choice(COOKIES),
            'sec_ch_ua': SEC_CH_UA_TEMPLATES.get(browser_type, ''),
        }
        
        headers = build_headers(strategy, config)
        params = get_params()
        
        print(f"\n第 {i+1}/{rounds} 次测试")
        print(f"  UA类型: {ua_key}")
        print(f"  User-Agent: {config['ua'][:50]}...")
        
        result = test_request(headers, params, i+1, strategy)
        results.append(result)
        
        if result['success']:
            print(f"  ✓ 成功! 状态码: {result['status']}, 耗时: {result['elapsed']:.2f}s, 板块数: {result['sector_count']}")
        else:
            print(f"  ✗ 失败! 状态码: {result.get('status', 'N/A')}, 错误: {result.get('error', 'Unknown')}")
        
        time.sleep(random.uniform(0.5, 1.5))
    
    success_count = sum(1 for r in results if r['success'])
    success_rate = success_count / rounds * 100
    avg_time = sum(r['elapsed'] for r in results) / rounds
    
    print(f"\n策略 [{strategy}] 汇总:")
    print(f"  成功率: {success_rate:.1f}% ({success_count}/{rounds})")
    print(f"  平均耗时: {avg_time:.2f}s")
    
    return {
        'strategy': strategy,
        'success_rate': success_rate,
        'success_count': success_count,
        'total': rounds,
        'avg_time': avg_time,
        'results': results
    }

def run_all_tests():
    print("="*60)
    print("东方财富板块资金API请求头测试")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"API地址: {SECTOR_API_URL}")
    print("="*60)
    
    strategies = [
        'minimal',
        'standard', 
        'full',
        'api_style',
        'random_generated'
    ]
    
    all_results = []
    
    for strategy in strategies:
        result = run_strategy_test(strategy, rounds=5)
        all_results.append(result)
        time.sleep(2)
    
    print("\n" + "="*60)
    print("测试汇总报告")
    print("="*60)
    print(f"{'策略':<20} {'成功率':<10} {'成功/总数':<12} {'平均耗时':<10}")
    print("-"*60)
    
    for r in all_results:
        print(f"{r['strategy']:<20} {r['success_rate']:.1f}%{'':<5} {r['success_count']}/{r['total']:<8} {r['avg_time']:.2f}s")
    
    best = max(all_results, key=lambda x: x['success_rate'])
    print(f"\n最佳策略: {best['strategy']} (成功率: {best['success_rate']:.1f}%)")
    
    return all_results

def test_continuous_requests(strategy='full', count=20, interval=1):
    print("="*60)
    print(f"连续请求测试 - 策略: {strategy}")
    print(f"请求次数: {count}, 间隔: {interval}s")
    print("="*60)
    
    success_count = 0
    fail_count = 0
    status_codes = {}
    
    for i in range(count):
        ua_key = random.choice(list(BROWSER_USER_AGENTS.keys()))
        browser_type = 'chrome' if 'chrome' in ua_key else ('edge' if 'edge' in ua_key else ('firefox' if 'firefox' in ua_key else 'safari'))
        
        config = {
            'ua': BROWSER_USER_AGENTS[ua_key],
            'accept': random.choice(ACCEPT_TYPES),
            'lang': random.choice(ACCEPT_LANGUAGES),
            'referer': random.choice(REFERERS),
            'cookie': random.choice(COOKIES),
            'sec_ch_ua': SEC_CH_UA_TEMPLATES.get(browser_type, ''),
        }
        
        headers = build_headers(strategy, config)
        params = get_params()
        
        result = test_request(headers, params, i+1, strategy)
        
        status = result.get('status', 'N/A')
        status_codes[status] = status_codes.get(status, 0) + 1
        
        if result['success']:
            success_count += 1
            symbol = "✓"
        else:
            fail_count += 1
            symbol = "✗"
        
        print(f"[{i+1:3d}/{count}] {symbol} 状态: {status}, 成功: {success_count}, 失败: {fail_count}")
        
        time.sleep(interval)
    
    print("\n" + "-"*60)
    print(f"连续测试完成!")
    print(f"  成功: {success_count}/{count} ({success_count/count*100:.1f}%)")
    print(f"  失败: {fail_count}/{count} ({fail_count/count*100:.1f}%)")
    print(f"  状态码分布: {status_codes}")
    
    return {
        'success_count': success_count,
        'fail_count': fail_count,
        'status_codes': status_codes
    }

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='测试东方财富API请求头策略')
    parser.add_argument('--mode', choices=['all', 'continuous'], default='all', help='测试模式')
    parser.add_argument('--strategy', default='full', help='连续测试使用的策略')
    parser.add_argument('--count', type=int, default=20, help='连续测试次数')
    parser.add_argument('--interval', type=float, default=1, help='连续测试间隔(秒)')
    
    args = parser.parse_args()
    
    if args.mode == 'all':
        run_all_tests()
    else:
        test_continuous_requests(args.strategy, args.count, args.interval)
