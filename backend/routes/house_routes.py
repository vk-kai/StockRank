from flask import Blueprint, jsonify
import pandas as pd
import numpy as np

house_bp = Blueprint('house', __name__, url_prefix='/api/house')

XIANY_ERSHOUFANG_HUANBI = [
    99.9, 99.8, 101.2, 100.9, 100.6, 100.6, 100.1, 100.0, 99.4, 99.3, 99.2, 99.4,
    99.8, 100.0, 99.7, 99.9, 100.2, 100.5, 100.6, 100.9, 100.7, 100.3, 99.7, 100.2,
    101.0, 100.9, 100.6, 100.8, 101.0, 100.9, 100.6, 100.3, 100.2, 99.8, 99.5, 99.7,
    100.0, 99.7, 100.1, 99.9, 99.6, 100.1, 100.3, 99.5, 99.6, 99.8, 99.3, 99.7,
    100.6, 100.8, 100.8, 100.3, 99.6, 99.6, 99.4, 99.7, 99.5, 100.0, 99.4, 99.5,
    99.5, 99.6, 99.7, 99.4, 99.0, 99.2, 99.4, 99.8, 99.2, 99.1, 99.7, 99.8,
    99.7, 99.6, 99.7, 99.6, 99.3, 99.2, 99.1, 98.9, 98.8, 99.0, 99.6, 98.9,
    99.2, 99.9, 100.0,
]

def generate_xian_price_data():
    base_date = pd.to_datetime("2018-12-31")
    date_range = pd.date_range(start="2019-01-31", periods=len(XIANY_ERSHOUFANG_HUANBI), freq="ME")
    
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
    quarterly = monthly_data.resample('QE').agg({
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

@house_bp.route('/kline', methods=['GET'])
def get_kline_data():
    try:
        data = generate_xian_price_data()
        monthly_kline = generate_monthly_kline(data)
        monthly_macd = calculate_macd(monthly_kline)
        quarterly_kline = generate_quarterly_kline(monthly_kline)
        quarterly_macd = calculate_macd(quarterly_kline)
        
        monthly_data = []
        for idx in monthly_kline.index:
            row = monthly_kline.loc[idx]
            macd_row = monthly_macd.loc[idx]
            monthly_data.append({
                'date': idx.strftime('%Y-%m-%d'),
                'year': idx.year,
                'month': idx.month,
                'open': round(row['open'], 2),
                'close': round(row['close'], 2),
                'high': round(row['high'], 2),
                'low': round(row['low'], 2),
                'huanbi': round(row['huanbi'], 2),
                'tongbi': round(row['tongbi'], 2),
                'macd': round(macd_row['macd'], 4),
                'signal': round(macd_row['signal'], 4),
                'histogram': round(macd_row['histogram'], 4)
            })
        
        quarterly_data = []
        for idx in quarterly_kline.index:
            row = quarterly_kline.loc[idx]
            macd_row = quarterly_macd.loc[idx]
            quarterly_data.append({
                'date': idx.strftime('%Y-%m-%d'),
                'quarter': row['quarter'],
                'open': round(row['open'], 2),
                'close': round(row['close'], 2),
                'high': round(row['high'], 2),
                'low': round(row['low'], 2),
                'macd': round(macd_row['macd'], 4),
                'signal': round(macd_row['signal'], 4),
                'histogram': round(macd_row['histogram'], 4)
            })
        
        return jsonify({
            'success': True,
            'data': {
                'monthly': monthly_data,
                'quarterly': quarterly_data,
                'title': '西安二手房真实价格分析 (2019年1月-2025年3月)',
                'source': '国家统计局'
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
