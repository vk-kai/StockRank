import json
import os
import threading
from datetime import datetime

from config import DATA_DIR

PUSH_STATE_DIR = os.path.join(DATA_DIR, 'market_map_push')
PUSH_STATE_FILE = os.path.join(PUSH_STATE_DIR, 'latest.json')

_write_lock = threading.Lock()


def _empty_doc():
    return {
        'source': '',
        'run_id': 0,
        'updated_at': None,
        'stocks': [],
    }


def _normalize_code(value):
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    if len(digits) == 6:
        return digits
    return ''


def _normalize_stocks(stocks):
    deduped = {}
    for item in stocks or []:
        if not isinstance(item, dict):
            continue
        code = _normalize_code(item.get('code'))
        if not code or code in deduped:
            continue
        name = str(item.get('name') or code).strip() or code
        deduped[code] = {'code': code, 'name': name}
    return list(deduped.values())


def load_market_map_push():
    if not os.path.exists(PUSH_STATE_FILE):
        return _empty_doc()
    try:
        with open(PUSH_STATE_FILE, 'r', encoding='utf-8') as f:
            doc = json.load(f)
        if not isinstance(doc, dict):
            return _empty_doc()
        stocks = _normalize_stocks(doc.get('stocks'))
        return {
            'source': str(doc.get('source') or '').strip(),
            'run_id': int(doc.get('run_id') or 0),
            'updated_at': doc.get('updated_at') or None,
            'stocks': stocks,
        }
    except Exception:
        return _empty_doc()


def save_market_map_push(payload):
    payload = payload or {}
    doc = {
        'source': str(payload.get('source') or '').strip() or 'quant-scan',
        'run_id': int(payload.get('run_id') or 0),
        'updated_at': str(payload.get('pushed_at') or payload.get('updated_at') or '').strip() or datetime.now().isoformat(),
        'stocks': _normalize_stocks(payload.get('stocks')),
    }
    os.makedirs(PUSH_STATE_DIR, exist_ok=True)
    tmp = PUSH_STATE_FILE + '.tmp'
    with _write_lock:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False)
        os.replace(tmp, PUSH_STATE_FILE)
    return doc


def clear_market_map_push():
    with _write_lock:
        if os.path.exists(PUSH_STATE_FILE):
            os.remove(PUSH_STATE_FILE)
    return _empty_doc()
