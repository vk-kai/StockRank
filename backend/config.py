import os
import random
import string
import json
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if BASE_DIR == '/':
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, 'data')
DAILY_DIR = os.path.join(DATA_DIR, 'daily')
REALTIME_DIR = os.path.join(DATA_DIR, 'realtime')
NEWS_DIR = os.path.join(DATA_DIR, 'news')
LOG_DIR = os.path.join(BASE_DIR, 'logs')
CONFIG_DIR = os.path.join(BASE_DIR, 'config')

MAX_DAYS = 30
MAX_NEWS_HOURS = 48

DATA_URL = "https://push2.eastmoney.com/api/qt/clist/get"
NEWS_URL = "https://news.10jqka.com.cn/tapp/news/push/stock/"
THS_SECTOR_NET_IN_URL = "https://q.10jqka.com.cn/thshy/index/field/zjjlr/order/desc/page/1/ajax/1/"
THS_SECTOR_NET_OUT_URL = "https://q.10jqka.com.cn/thshy/index/field/zjjlr/order/asc/page/1/ajax/1/"
THS_SECTOR_URL = THS_SECTOR_NET_IN_URL

USE_PROXY = False

def is_dev_mode():
    return os.environ.get('STOCKRANK_ENV', 'prod') == 'dev'

def get_random_user_agent():
    browsers = ['Chrome', 'Firefox', 'Safari', 'Edge']
    browser = random.choice(browsers)
    
    chrome_version = f"{random.randint(100, 125)}.0.{random.randint(1000, 9999)}.{random.randint(10, 999)}"
    firefox_version = random.randint(100, 125)
    safari_version = f"{random.randint(600, 620)}.{random.randint(1, 15)}.{random.randint(1, 15)}"
    edge_version = f"{random.randint(100, 125)}.0.{random.randint(1000, 9999)}.{random.randint(10, 999)}"
    
    webkit_version = f"{random.randint(535, 538)}.{random.randint(1, 99)}"
    gecko_version = f"{random.randint(2010, 2025)}{random.randint(1, 12):02d}{random.randint(1, 28):02d}"
    
    platforms = [
        ('Windows NT 10.0; Win64; x64', 'Windows'),
        ('Windows NT 10.0; Win64; x64', 'Windows'),
        ('Macintosh; Intel Mac OS X 10_15_7', 'Mac'),
        ('Macintosh; Intel Mac OS X 11_0_0', 'Mac'),
        ('X11; Linux x86_64', 'Linux'),
        ('X11; Ubuntu; Linux x86_64', 'Linux'),
    ]
    
    platform, os_type = random.choice(platforms)
    
    if browser == 'Chrome':
        return f"Mozilla/5.0 ({platform}) AppleWebKit/{webkit_version} (KHTML, like Gecko) Chrome/{chrome_version} Safari/{webkit_version}"
    elif browser == 'Firefox':
        return f"Mozilla/5.0 ({platform}; rv:{firefox_version}.0) Gecko/{gecko_version} Firefox/{firefox_version}.0"
    elif browser == 'Safari':
        if os_type == 'Mac':
            return f"Mozilla/5.0 ({platform}) AppleWebKit/{webkit_version} (KHTML, like Gecko) Version/{random.randint(15, 18)}.{random.randint(0, 5)} Safari/{safari_version}"
        else:
            return f"Mozilla/5.0 ({platform}) AppleWebKit/{webkit_version} (KHTML, like Gecko) Chrome/{chrome_version} Safari/{webkit_version}"
    else:
        return f"Mozilla/5.0 ({platform}) AppleWebKit/{webkit_version} (KHTML, like Gecko) Chrome/{chrome_version} Safari/{webkit_version} Edg/{edge_version}"

DEV_NEWS_URL = "http://127.0.0.1:8899/tapp/news/push/stock/"

AI_CONFIG_FILE = os.path.join(CONFIG_DIR, 'ai_config.json')
FEISHU_CONFIG_FILE = os.path.join(CONFIG_DIR, 'feishu_config.json')
STOCK_MONITOR_CONFIG_FILE = os.path.join(CONFIG_DIR, 'stock_monitor.json')
AI_PROMPT_FILE = os.path.join(CONFIG_DIR, 'ai_prompt.txt')
MONITOR_CONFIG_FILE = os.path.join(CONFIG_DIR, 'monitor_config.json')

def load_monitor_config():
    default_config = {
        'api_base_url': 'http://127.0.0.1:5000',
        'check_interval': 30,
        'alert_threshold': 120,
        'restart_cooldown': 300
    }
    
    if os.path.exists(MONITOR_CONFIG_FILE):
        try:
            with open(MONITOR_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
                default_config.update(config)
        except Exception:
            pass
    
    return default_config

if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR)
