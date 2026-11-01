# -*- coding: utf-8 -*-
"""统一 AI 调用: OpenAI 兼容接口 + 连接失败重试 + JSON 提取"""
import json, re, time, urllib.request, urllib.error
from agent_core import config
class LLMError(Exception):
    pass


def llm_chat(messages, temperature=0.8, timeout=None):
    timeout = timeout or config.LLM_TIMEOUT
    cfg = config.load_config()
    if not cfg.get('base_url') or not cfg.get('api_key'):
        raise LLMError('未配置 AI 接口, 请到「设置」填写 base_url / api_key / model')
    base = cfg['base_url'].rstrip('/')
    if not base.endswith('/v1'):
        base += '/v1'
    url = base + '/chat/completions'
    body = json.dumps({'model': cfg['model'], 'messages': messages,
                       'temperature': temperature}).encode('utf-8')
    data = None
    last_err = None
    for attempt in range(config.LLM_RETRIES + 1):
        req = urllib.request.Request(url, data=body, method='POST', headers={
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + cfg['api_key']})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode('utf-8'))
            break
        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = e.read().decode('utf-8')[:300]
            except Exception:
                pass
            # 4xx 是请求本身的问题, 重试无意义
            raise LLMError(f'AI 接口返回 {e.code}: {detail}')
        except Exception as e:
            last_err = e
            if attempt < config.LLM_RETRIES:
                time.sleep(1.5 * (attempt + 1))
    if data is None:
        raise LLMError(f'AI 接口连接失败(已重试{config.LLM_RETRIES}次): {last_err}')
    try:
        return data['choices'][0]['message']['content']
    except Exception:
        raise LLMError('AI 返回格式异常: ' + json.dumps(data, ensure_ascii=False)[:300])


def embed_texts(texts, _allow_dim=True):
    """批量向量化(OpenAI 兼容 /embeddings), 返回与输入等长的向量列表。
    需在设置里配置 embedding_model(可选 embedding_dimensions 压缩维度);
    网关不认 dimensions 参数报 400 时自动去掉重试一次。"""
    cfg = config.load_config()
    if not cfg.get('base_url') or not cfg.get('api_key') or not cfg.get('embedding_model'):
        raise LLMError('未配置向量化接口: 请到「设置」填写 embedding_model')
    base = cfg['base_url'].rstrip('/')
    if not base.endswith('/v1'):
        base += '/v1'
    body = {'model': cfg['embedding_model'], 'input': list(texts)}
    dim = int(cfg.get('embedding_dimensions') or 0)
    if dim > 0 and _allow_dim:
        body['dimensions'] = dim
    req = urllib.request.Request(base + '/embeddings', data=json.dumps(body).encode('utf-8'),
                                 method='POST', headers={
                                     'Content-Type': 'application/json',
                                     'Authorization': 'Bearer ' + cfg['api_key']})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = e.read().decode('utf-8')[:200]
        except Exception:
            pass
        if dim > 0 and _allow_dim and e.code == 400:
            return embed_texts(texts, _allow_dim=False)
        raise LLMError(f'向量化接口返回 {e.code}: {detail}')
    except Exception as e:
        raise LLMError(f'向量化接口连接失败: {e}')
    try:
        rows = sorted(data['data'], key=lambda x: x.get('index', 0))
        return [row['embedding'] for row in rows]
    except Exception:
        raise LLMError('向量化接口返回格式异常: ' + json.dumps(data, ensure_ascii=False)[:200])


def extract_json(text):
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        raise LLMError('AI 未返回 JSON')
    raw = m.group(0)
    # AI 生成 JSON 时可能把真实换行/Tab 写进字符串值(strict 模式会报 Invalid control character)
    try:
        return json.loads(raw, strict=False)
    except json.JSONDecodeError:
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', raw)
        try:
            return json.loads(cleaned, strict=False)
        except json.JSONDecodeError:
            raise LLMError('AI 返回的内容格式异常(JSON 解析失败), 请重试一次')
