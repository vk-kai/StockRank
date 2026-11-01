# -*- coding: utf-8 -*-
"""AI 结果缓存: 版本化元数据 + 原子写入 + 读取兼容旧版裸结果
缓存结构: {"schema_version":2, "generated_at":"", "source_version":"数据指纹", "model":"", "result":{}}
数据/模型/Prompt 变化时指纹随之变化, 可据此判断缓存是否需要重新生成"""
import os, hashlib, datetime
from agent_core import config
def fingerprint(*parts):
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode('utf-8'))
        h.update(b'\x00')
    return h.hexdigest()[:12]


def file_fp(path):
    """文件指纹: 路径 + 大小 + 修改时间"""
    try:
        st = os.stat(path)
    except OSError:
        return 'missing'
    return fingerprint(path, st.st_size, int(st.st_mtime))


def load(path):
    """返回 (result or None, meta or None); 兼容旧版裸结果格式"""
    d = config.jload(path, None)
    if d is None:
        return None, None
    if isinstance(d, dict) and 'schema_version' in d and 'result' in d:
        return d.get('result'), {k: v for k, v in d.items() if k != 'result'}
    return d, None


def save(path, result, source_fp):
    wrap = {'schema_version': config.CACHE_SCHEMA_VERSION,
            'generated_at': datetime.datetime.now().isoformat(timespec='seconds'),
            'source_version': source_fp,
            'model': config.load_config().get('model', ''),
            'result': result}
    config.atomic_write_json(path, wrap)


def is_stale(path, current_fp):
    """缓存的数据指纹与当前不一致 → 过期(可重新生成)"""
    _, meta = load(path)
    if not meta:
        return True
    return meta.get('source_version') != current_fp
