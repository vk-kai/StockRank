# -*- coding: utf-8 -*-
"""路径与全局配置 —— StockRank 云端版

与本地版(桌面 WeChatExport/个人Agent/config.py)的差异只在路径定位:
本地版基于 WeChatExport/ 根目录, 本版数据统一放 backend/agent_data/ 下(git 忽略,
由人工拷贝或 scripts/agent_local_sync.py 同步器维护), 其余行为参数与本地保持一致。
本地长期运行是主战场, 每次在本地改完代码用「同步到云端.bat」一键同步即可,
同步脚本会跳过本文件(云端路径结构是手写的, 不能被本地版覆盖)。
"""
import os, json, tempfile, threading

APP = os.path.dirname(os.path.abspath(__file__))            # backend/agent_core/
ROOT = os.path.dirname(APP)                                 # backend/
DATA_ROOT = os.path.join(ROOT, 'agent_data')                # backend/agent_data/ (git 忽略)
KB = os.path.join(DATA_ROOT, 'Agent知识库')                  # 知识库: 风格档案/联系人档案/范例库/事实
DATA = os.path.join(DATA_ROOT, '聊天记录数据')               # 聊天记录 jsonl(私聊/群聊)
CACHE = os.path.join(APP, 'cache')                           # AI 画像/推演等运行时缓存
WEB = os.path.join(APP, 'web')                               # 云端前端由 Vue 承载, 此目录仅兜底不用
CONFIG = os.path.join(APP, 'config.json')                    # LLM 网关配置(含 key, git 忽略)

os.makedirs(CACHE, exist_ok=True)

# 行为参数
HISTORY_WINDOW = 8        # 送入模型的对话轮数
LLM_TIMEOUT = 180         # 单次 AI 调用超时(秒)
LLM_RETRIES = 2           # 连接类失败自动重试次数
MAX_BODY = 1 << 20        # HTTP 请求体上限 1MB
RETRIEVE_TOP_K = 12       # 注入分身上下文的相关记忆条数
CACHE_SCHEMA_VERSION = 2

_cfg_lock = threading.Lock()


def jload(p, default):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def load_config():
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'base_url': '', 'api_key': '', 'model': ''}


def save_config(c):
    with _cfg_lock:
        atomic_write_json(CONFIG, c)


def atomic_write(path, data_bytes):
    """先写临时文件再原子替换, 避免读到一个写了一半的文件"""
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data_bytes)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path, obj):
    atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2).encode('utf-8'))
