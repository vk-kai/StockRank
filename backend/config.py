import os
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
MAX_NEWS_HOURS = 24

DATA_URL = "https://push2.eastmoney.com/api/qt/clist/get"
NEWS_URL = "https://news.10jqka.com.cn/tapp/news/push/stock/"

DEV_MODE = os.environ.get('STOCKRANK_ENV', 'prod') == 'dev'
DEV_NEWS_URL = "http://127.0.0.1:8899/tapp/news/push/stock/"

AI_CONFIG_FILE = os.path.join(CONFIG_DIR, 'ai_config.json')
FEISHU_CONFIG_FILE = os.path.join(CONFIG_DIR, 'feishu_config.json')
STOCK_MONITOR_CONFIG_FILE = os.path.join(CONFIG_DIR, 'stock_monitor.json')
AI_PROMPT_FILE = os.path.join(CONFIG_DIR, 'ai_prompt.txt')

if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR)