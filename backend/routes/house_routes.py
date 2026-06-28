from flask import Blueprint, jsonify, request
import pandas as pd
import numpy as np
import traceback
import os
import json
import uuid
from datetime import datetime
from logger import get_logger

try:
    from config import DAILY_DIR
except Exception:
    DAILY_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'daily'))

house_bp = Blueprint('house', __name__, url_prefix='/api/house')
error_logger = get_logger('error')
system_logger = get_logger('system')

DATA_DIR = os.path.dirname(DAILY_DIR)
CUSTOM_KLINES_FILE = os.path.join(DATA_DIR, 'custom_klines.json')

XIANY_ERSHOUFANG_HUANBI = [
    99.9, 99.8, 101.2, 100.9, 100.6, 100.6, 100.1, 100.0, 99.4, 99.3, 99.2, 99.4,
    99.8, 100.0, 99.7, 99.9, 100.2, 100.5, 100.6, 100.9, 100.7, 100.3, 99.7, 100.2,
    101.0, 100.9, 100.6, 100.8, 101.0, 100.9, 100.6, 100.3, 100.2, 99.8, 99.5, 99.7,
    100.0, 99.7, 100.1, 99.9, 99.6, 100.1, 100.3, 99.5, 99.6, 99.8, 99.3, 99.7,
    100.6, 100.8, 100.8, 100.3, 99.6, 99.6, 99.4, 99.7, 99.5, 100.0, 99.4, 99.5,
    99.5, 99.6, 99.7, 99.4, 99.0, 99.2, 99.4, 99.8, 99.2, 99.1, 99.7, 99.8,
    99.7, 99.6, 99.7, 99.6, 99.3, 99.2, 99.1, 98.9, 98.8, 99.0, 99.6, 98.9,
    99.2, 99.9, 100.0,100.4,99.8
]

# 基础周期 → 可聚合出的更高周期
HIGHER_PERIODS = {
    '30min': ['daily', 'monthly', 'quarterly'],
    'daily': ['monthly', 'quarterly'],
    'monthly': ['quarterly'],
}

def get_pandas_freq(freq_type):
    pd_version = tuple(map(int, pd.__version__.split('.')[:2]))
    if freq_type == 'month':
        return 'ME' if pd_version >= (2, 2) else 'M'
    elif freq_type == 'quarter':
        return 'QE' if pd_version >= (2, 2) else 'Q'
    return freq_type

def _resample_freq(period):
    return {'daily': 'D', 'monthly': get_pandas_freq('month'), 'quarterly': get_pandas_freq('quarter')}.get(period, 'D')

def _fmt_label(ts, period):
    if period == '30min':
        return ts.strftime('%m-%d %H:%M')
    if period == 'daily':
        return ts.strftime('%Y-%m-%d')
    if period == 'monthly':
        return ts.strftime('%Y-%m')
    if period == 'quarterly':
        return f"{ts.year}Q{ts.quarter}"
    return ts.strftime('%Y-%m-%d')

def generate_xian_price_data():
    base_date = pd.to_datetime("2018-12-31")
    month_freq = get_pandas_freq('month')
    date_range = pd.date_range(start="2019-01-31", periods=len(XIANY_ERSHOUFANG_HUANBI), freq=month_freq)

    df = pd.DataFrame(index=[base_date] + list(date_range))

    prices = [100.0]
    for ratio in XIANY_ERSHOUFANG_HUANBI:
        new_price = prices[-1] * (ratio / 100)
        prices.append(new_price)

    df['price'] = prices[:len(df)]

    df['huanbi'] = df['price'] / df['price'].shift(1) * 100
    df.loc[df.index[0], 'huanbi'] = 100.0

    df['tongbi'] = 100.0
    for idx in range(13, len(df)):
        prev_year_price = df.iloc[idx - 12]['price']
        current_price = df.iloc[idx]['price']
        df.iloc[idx, df.columns.get_loc('tongbi')] = (current_price / prev_year_price) * 100

    return df

def generate_monthly_kline(data):
    monthly_ohlc = pd.DataFrame(index=data.index[1:])

    monthly_ohlc["open"] = data["price"].shift(1).loc[monthly_ohlc.index]
    monthly_ohlc["close"] = data["price"].loc[monthly_ohlc.index]
    monthly_ohlc["high"] = monthly_ohlc[["open", "close"]].max(axis=1)
    monthly_ohlc["low"] = monthly_ohlc[["open", "close"]].min(axis=1)
    monthly_ohlc["huanbi"] = data["huanbi"].loc[monthly_ohlc.index]
    monthly_ohlc["tongbi"] = data["tongbi"].loc[monthly_ohlc.index]

    return monthly_ohlc

def generate_quarterly_kline(monthly_data):
    quarter_freq = get_pandas_freq('quarter')
    quarterly = monthly_data.resample(quarter_freq).agg({
        'open': 'first',
        'close': 'last',
        'high': 'max',
        'low': 'min'
    })
    quarterly["quarter"] = [f"{d.year}Q{d.quarter}" for d in quarterly.index]
    return quarterly

def calculate_macd(data):
    df = data.copy()
    close_prices = df["close"]

    df["ema12"] = close_prices.ewm(span=12, adjust=False).mean()
    df["ema26"] = close_prices.ewm(span=26, adjust=False).mean()
    df["macd"] = df["ema12"] - df["ema26"]
    df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["histogram"] = df["macd"] - df["signal"]

    return df

# ---------------- 自定义K线：存储 ----------------
def _load_custom():
    try:
        if os.path.exists(CUSTOM_KLINES_FILE):
            with open(CUSTOM_KLINES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f) or []
    except Exception as e:
        error_logger.warning(f"读取 custom_klines 失败: {e}")
    return []

def _save_custom(datasets):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = CUSTOM_KLINES_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(datasets, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CUSTOM_KLINES_FILE)

def _find_custom(ds_id):
    for ds in _load_custom():
        if ds.get('id') == ds_id:
            return ds
    return None

# ---------------- 自定义K线：聚合 ----------------
def _points_from_ohlc(ohlc, macd_df, period):
    points = []
    for idx in ohlc.index:
        row = ohlc.loc[idx]
        macd_row = macd_df.loc[idx]
        date_str = idx.strftime('%Y-%m-%d %H:%M') if period == '30min' else idx.strftime('%Y-%m-%d')
        points.append({
            'date': date_str,
            'label': _fmt_label(idx, period),
            'open': round(float(row['open']), 4),
            'close': round(float(row['close']), 4),
            'high': round(float(row['high']), 4),
            'low': round(float(row['low']), 4),
            'macd': round(float(macd_row['macd']), 4),
            'signal': round(float(macd_row['signal']), 4),
            'histogram': round(float(macd_row['histogram']), 4),
        })
    return points

def _aggregate_custom(ds, period):
    """把自定义数据集的 close 点聚合成指定周期的 OHLC+MACD。"""
    base = ds.get('basePeriod', 'daily')
    if period != base and period not in HIGHER_PERIODS.get(base, []):
        return []

    pts = sorted(ds.get('points', []), key=lambda p: p['date'])
    pts = [p for p in pts if p.get('date') and p.get('value') not in (None, '')]
    if not pts:
        return []

    dates = pd.to_datetime([p['date'] for p in pts])
    values = [float(p['value']) for p in pts]
    df = pd.DataFrame({'close': values}, index=dates).sort_index()

    # 基础周期 OHLC：open=上一收盘，high/low 取两者
    df['open'] = df['close'].shift(1)
    df.loc[df.index[0], 'open'] = df['close'].iloc[0]
    df['high'] = df[['open', 'close']].max(axis=1)
    df['low'] = df[['open', 'close']].min(axis=1)
    ohlc = df[['open', 'close', 'high', 'low']]

    # 聚合到更高周期
    if period != base:
        ohlc = ohlc.resample(_resample_freq(period)).agg({
            'open': 'first', 'close': 'last', 'high': 'max', 'low': 'min'
        }).dropna()

    macd_df = calculate_macd(ohlc.copy())
    return _points_from_ohlc(ohlc, macd_df, period)

# ---------------- 接口 ----------------
@house_bp.route('/datasets', methods=['GET'])
def list_datasets():
    datasets = [{
        'id': 'house',
        'title': '🏠 西安二手房价格',
        'unit': '万',
        'basePeriod': 'monthly',
        'builtin': True,
        'count': len(XIANY_ERSHOUFANG_HUANBI)
    }]
    for ds in _load_custom():
        datasets.append({
            'id': ds.get('id'),
            'title': ds.get('title', '未命名'),
            'unit': ds.get('unit', ''),
            'basePeriod': ds.get('basePeriod', 'daily'),
            'builtin': False,
            'count': len(ds.get('points', []))
        })
    return jsonify({'success': True, 'data': datasets})


@house_bp.route('/datasets', methods=['POST'])
def save_dataset():
    try:
        body = request.get_json(force=True) or {}
        title = (body.get('title') or '').strip()
        base = body.get('basePeriod')
        unit = (body.get('unit') or '').strip()
        if not title:
            return jsonify({'success': False, 'error': '标题不能为空'}), 400
        if base not in ('30min', 'daily', 'monthly'):
            return jsonify({'success': False, 'error': '基础周期无效'}), 400

        points = []
        for p in body.get('points', []):
            d = (p.get('date') or '').strip()
            v = p.get('value')
            if not d or v in (None, ''):
                continue
            try:
                points.append({'date': d, 'value': float(v)})
            except Exception:
                continue
        if not points:
            return jsonify({'success': False, 'error': '至少填入一个有效数据点'}), 400

        datasets = _load_custom()
        new_ds = {
            'id': str(uuid.uuid4()),
            'title': title,
            'unit': unit,
            'basePeriod': base,
            'points': points,
            'createdAt': datetime.now().astimezone().isoformat()
        }
        datasets.append(new_ds)
        _save_custom(datasets)
        return jsonify({'success': True, 'id': new_ds['id']})
    except Exception as e:
        error_logger.error(f"保存自定义K线失败: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500


@house_bp.route('/datasets/<ds_id>', methods=['DELETE'])
def delete_dataset(ds_id):
    try:
        datasets = _load_custom()
        new_list = [d for d in datasets if d.get('id') != ds_id]
        if len(new_list) == len(datasets):
            return jsonify({'success': False, 'error': '未找到该数据集'}), 404
        _save_custom(new_list)
        return jsonify({'success': True})
    except Exception as e:
        error_logger.error(f"删除自定义K线失败: {e}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': str(e)}), 500


@house_bp.route('/kline', methods=['GET'])
def get_kline_data():
    dataset_id = (request.args.get('id') or 'house').strip()
    period = (request.args.get('period') or 'monthly').strip()
    try:
        if dataset_id == 'house':
            data = generate_xian_price_data()
            monthly_kline = generate_monthly_kline(data)
            if period == 'quarterly':
                kline = generate_quarterly_kline(monthly_kline)
                macd_df = calculate_macd(kline.copy())
                points = _points_from_ohlc(kline, macd_df, 'quarterly')
            else:
                macd_df = calculate_macd(monthly_kline.copy())
                points = _points_from_ohlc(monthly_kline, macd_df, 'monthly')
            return jsonify({
                'success': True,
                'data': {
                    'title': '🏠 西安二手房价格',
                    'unit': '万',
                    'source': '国家统计局',
                    'period': period,
                    'points': points
                }
            })

        ds = _find_custom(dataset_id)
        if not ds:
            return jsonify({'success': False, 'error': '数据集不存在'}), 404
        points = _aggregate_custom(ds, period)
        return jsonify({
            'success': True,
            'data': {
                'title': ds.get('title', '自定义K线'),
                'unit': ds.get('unit', ''),
                'source': '用户自定义',
                'period': period,
                'points': points
            }
        })
    except Exception as e:
        error_msg = f"K线接口错误: {str(e)}"
        error_logger.error(error_msg)
        error_logger.error(f"详细堆栈信息:\n{traceback.format_exc()}")
        system_logger.error(f"API错误 [/api/house/kline]: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
