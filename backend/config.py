import os
from datetime import timedelta

# 数据目录配置 - 与backend目录同级
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Docker环境下，如果上级目录是根目录，则使用当前目录
if BASE_DIR == '/':
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, 'data')
DAILY_DIR = os.path.join(DATA_DIR, 'daily')  # 最近一个月的每日最高流入数据
REALTIME_DIR = os.path.join(DATA_DIR, 'realtime')  # 当天5分钟一次的实时数据
LOG_DIR = os.path.join(BASE_DIR, 'logs')  # 日志目录（与data平行）

MAX_DAYS = 30
DATA_URL = "https://push2.eastmoney.com/api/qt/clist/get"