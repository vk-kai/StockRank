import requests
import json
import re
from datetime import datetime, timedelta
import os
import random
import string
import hashlib
import subprocess
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
from bs4 import BeautifulSoup
from core.config import DAILY_DIR, REALTIME_DIR, MAX_DAYS, DATA_URL, THS_SECTOR_URL, THS_SECTOR_NET_IN_URL, THS_SECTOR_NET_OUT_URL, USE_PROXY, get_random_user_agent, get_eastmoney_headers, em_request
from ._common import (
    error_logger, data_logger, system_logger, data_summary_logger,
    _safe_float, _parse_ths_number, _parse_ths_int,
    _parse_json_or_jsonp, _last_list_value, _last_dict_value, _pick_first_number,
    MARKET_INDEX_URL, GLOBAL_INDICES_CACHE_FILE,
)
from .ths_client import generate_random_headers, attach_fresh_ths_cookie
