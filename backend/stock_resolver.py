# -*- coding: utf-8 -*-
"""自选股:名字↔代码互解 + 板块判定 + 涨跌停幅度。

涨跌停规则(自动,不可手填):
  - 北交所(bj) ±30%
  - 创业板(sz 300/301/302) ±20%
  - 科创板(sh 688/689) ±20%
  - 主板(sh 600/601/603/605;sz 000/001/002/003) ±10%
  - ST/*ST ±5% 仅对主板生效(注册制板块与北交所无 5% ST 档)
"""
from logger import get_logger

logger = get_logger('stock_resolver')


def classify_board(code):
    """code 形如 'sh600519' / 'sz301236' / 'bj920002'。

    返回 'main' / 'creative' / 'star' / 'bse' / 'unknown'。
    """
    code = (code or '').lower()
    if len(code) < 3:
        return 'unknown'
    ex, num = code[:2], code[2:]
    if ex == 'bj':
        return 'bse'
    if ex == 'sh':
        if num.startswith(('688', '689')):
            return 'star'
        if num.startswith(('600', '601', '603', '605')):
            return 'main'
        return 'unknown'
    if ex == 'sz':
        if num.startswith(('300', '301', '302')):
            return 'creative'
        if num.startswith(('000', '001', '002', '003')):
            return 'main'
        return 'unknown'
    return 'unknown'


def get_limit_pct(code, name):
    """返回该股涨跌停幅度(正数,百分点),如 10.0 / 20.0 / 30.0 / 5.0。"""
    board = classify_board(code)
    if board == 'bse':
        base = 30.0
    elif board in ('creative', 'star'):
        base = 20.0
    elif board == 'main':
        base = 10.0
    else:
        base = 10.0  # 未知降级主板
    # ST ±5% 仅主板
    if board == 'main' and name and ('ST' in name.upper()):
        base = 5.0
    return base
