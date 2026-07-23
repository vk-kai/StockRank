"""AI 返回 JSON 的鲁棒提取与解析（ai_analyzer / industry_cycle 共用）。

LLM 偶尔产出"几乎是 JSON"的文本，常见毛病：字符串内未转义的英文双引号（中文里很自然，如
…炒作"封装技术瓶颈"…）、尾随逗号、以及把 JSON 包在解释文字/代码围栏里。标准 json.loads 直接失败，
业务层回退显示原始文本。本模块做三层兜底：
  ① 代码围栏 / 括号匹配定位真正的 JSON 区间（忽略散文里的括号）；
  ② 标准 json.loads；
  ③ 失败则轻量修复（CJK 相邻的内层双引号转义、尾随逗号去除）再解析。

配合 call_ai_api 的 response_format=json_object 使用：那是源头主防线，本模块是兜底。
"""
import json
import re

_FENCE_RE = re.compile(r'```(?:json)?\s*([\s\S]*?)\s*```')
# CJK 表意文字 + CJK 标点 + 全角符号
_CJK = r'一-鿿　-〿＀-￯'
# 内层双引号：前后都是 CJK/中文标点的 " 几乎必为内容引号（结构性 " 必紧邻 JSON 语法字符）
_INNER_QUOTE_RE = re.compile(rf'(?<=[{_CJK}])"(?=[{_CJK}])')
_TRAILING_COMMA_RE = re.compile(r',(\s*[}\]])')


def _balanced_span(text, start, opener, closer):
    """从 text[start]（必须等于 opener）起做字符串感知的括号匹配，返回闭合区间串或 None。"""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if esc:
            esc = False
            continue
        if c == '\\':
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _repair(text):
    """修复 AI 常见 JSON 毛病：CJK 相邻的内层双引号转义、尾随逗号去除。"""
    # 用 lambda 返回 '\\"'，规避 re.sub 替换串的反斜杠转义歧义
    text = _INNER_QUOTE_RE.sub(lambda m: '\\"', text)
    text = _TRAILING_COMMA_RE.sub(r'\1', text)
    return text


def _strip_comments(text):
    """移除 JS 风格注释（// 行注释、/* 块注释）。作为最后兜底候选——
    注意会误伤字符串内的 //（如 URL），故只在前面的候选都失败时才尝试。"""
    text = re.sub(r'//.*?(?=\n|$)', '', text)
    text = re.sub(r'/\*[\s\S]*?\*/', '', text)
    return text


def extract_ai_json(content, prefer='any'):
    """从 AI 原始返回中提取并解析 JSON。

    prefer: 'array' 只接受 list | 'object' 只接受 dict | 'any' 皆可。
    返回解析后的 Python 对象（list/dict），失败返回 None。
    """
    if not content:
        return None
    fence = _FENCE_RE.search(content)
    # 候选依次：代码围栏内容 → 原文 → 去注释原文（去注释有误伤 URL 风险，放最后）
    raws = []
    if fence:
        raws.append(fence.group(1))
    raws.append(content)
    raws.append(_strip_comments(content))

    for raw in raws:
        text = _repair(raw)
        for i, c in enumerate(text):
            if c == '[':
                span = _balanced_span(text, i, '[', ']')
            elif c == '{':
                span = _balanced_span(text, i, '{', '}')
            else:
                continue
            if span is None:
                continue
            try:
                obj = json.loads(span)
            except (json.JSONDecodeError, ValueError):
                continue
            if prefer == 'array' and not isinstance(obj, list):
                continue
            if prefer == 'object' and not isinstance(obj, dict):
                continue
            return obj
    return None


# ---- Tier2：AI 自修复（本地容错搞不定的结构性破损，回喂 AI 修正）----
_REPAIR_SYSTEM = "你是 JSON 修正器：只输出合法 JSON，不要任何解释、不要 markdown 代码围栏。"
_REPAIR_USER_PREFIX = (
    "下面不是合法 JSON。请仅修正 JSON 语法——转义字符串值内的英文双引号为 \\\"、"
    "去掉 } 或 ] 前的尾随逗号、补全未闭合的括号——保持原内容与结构不变，"
    "直接输出修正后的合法 JSON：\n\n"
)


def parse_with_ai_repair(content, call_ai_fn, prefer='any', logger=None):
    """本地容错解析（Tier3）→ 失败则回喂 AI 修正一次（Tier2）→ 再解析。

    先本地（免费、治大多数：未转义引号/尾逗号/围栏/散文括号）；本地也搞不定才花一次 AI 调用
    修正结构性破损。call_ai_fn(messages) -> content_str | None（由调用方适配 call_ai_api）。
    返回解析后的 Python 对象，或 None。
    """
    if content:
        obj = extract_ai_json(content, prefer=prefer)
        if obj is not None:
            return obj
    if content and call_ai_fn:
        try:
            fixed = call_ai_fn([
                {'role': 'system', 'content': _REPAIR_SYSTEM},
                {'role': 'user', 'content': _REPAIR_USER_PREFIX + content},
            ])
        except Exception as e:
            if logger:
                logger.warning(f"AI JSON 修正调用异常: {e}")
            fixed = None
        if fixed:
            obj = extract_ai_json(fixed, prefer=prefer)
            if obj is not None:
                if logger:
                    logger.info("AI JSON 自修复成功")
                return obj
            if logger:
                logger.warning("AI JSON 自修复后仍解析失败，回退原始内容")
    return None
