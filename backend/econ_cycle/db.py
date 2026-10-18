# -*- coding: utf-8 -*-
"""经济周期模块的存储层:统一库 data/stockrank.db 中的 econ_* 三张表。

econ_indicator  指标目录(代码/层级/区域/权重)
econ_series     指标序列(主键 code+period+value_type;含采集时间与来源)
econ_phase      阶段判定结果(全国/西安/行业 × 月份;含依据)
"""
import os
import sqlite3
from datetime import datetime

from core.config import UNIFIED_DB_FILE

DB_FILE = UNIFIED_DB_FILE  # 与 mp_* 同库,部署零迁移成本

_tables_ready = False


def _db():
    """连接并确保建表(进程内一次)。返回 Row 工厂连接。"""
    global _tables_ready
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    if not _tables_ready:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS econ_indicator (
          code   TEXT PRIMARY KEY,
          name   TEXT NOT NULL,
          layer  TEXT NOT NULL,            -- leading 领先 / coincident 同步 / lagging 滞后
          region TEXT NOT NULL,            -- national 全国 / xian 西安 / industry:xxx 行业
          unit   TEXT DEFAULT '',
          source TEXT DEFAULT '',
          freq   TEXT DEFAULT 'monthly',
          weight REAL NOT NULL DEFAULT 1.0,
          value_type TEXT NOT NULL DEFAULT 'level'  -- 序列存储类型: level / yoy / cum_yoy
        );
        CREATE TABLE IF NOT EXISTS econ_series (
          indicator_code TEXT NOT NULL,
          period   TEXT NOT NULL,          -- YYYY-MM(数据所属期间)
          value    REAL,
          value_type TEXT NOT NULL DEFAULT 'level',  -- level / yoy / cum_yoy(西安累计同比)
          pub_date   TEXT DEFAULT '',      -- 实际发布日期(用于回测点时截断)
          capture_time TEXT NOT NULL,
          source     TEXT DEFAULT '',
          source_url TEXT DEFAULT '',
          note       TEXT DEFAULT '',
          PRIMARY KEY (indicator_code, period, value_type)
        );
        CREATE TABLE IF NOT EXISTS econ_phase (
          scope  TEXT NOT NULL,            -- national / xian / industry:xxx
          month  TEXT NOT NULL,            -- YYYY-MM(判定所依据数据的最新期间)
          phase  TEXT NOT NULL,            -- downturn 持续恶化 / bottoming 低位企稳 / early_recovery 复苏初期 / expansion 上行 / overheating 过热
          score  REAL,
          reasons TEXT DEFAULT '',
          created_at TEXT NOT NULL,
          PRIMARY KEY (scope, month)
        );
        ''')
        # 旧库兼容:econ_indicator 补 value_type/invert 列
        cols = {r[1] for r in conn.execute('PRAGMA table_info(econ_indicator)')}
        if 'value_type' not in cols:
            conn.execute("ALTER TABLE econ_indicator ADD COLUMN value_type TEXT NOT NULL DEFAULT 'level'")
        if 'invert' not in cols:
            conn.execute('ALTER TABLE econ_indicator ADD COLUMN invert INTEGER NOT NULL DEFAULT 0')
        _tables_ready = True
    return conn


def upsert_indicators(rows):
    """批量登记指标目录 rows: dict(code,name,layer,region,...,value_type,invert)。缺省字段兜底。"""
    defaults = dict(unit='', source='', freq='monthly', weight=1.0, value_type='level', invert=0)
    norm = [dict(defaults, **{k: v for k, v in r.items() if v is not None}) for r in rows]
    with _db() as conn:
        conn.executemany('''INSERT INTO econ_indicator(code,name,layer,region,unit,source,freq,weight,value_type,invert)
            VALUES(:code,:name,:layer,:region,:unit,:source,:freq,:weight,:value_type,:invert)
            ON CONFLICT(code) DO UPDATE SET name=excluded.name, layer=excluded.layer,
              region=excluded.region, unit=excluded.unit, source=excluded.source,
              freq=excluded.freq, weight=excluded.weight,
              value_type=excluded.value_type, invert=excluded.invert''', norm)


def upsert_series(code, points, value_type='level', source='', source_url=''):
    """批量写序列 points: [(period 'YYYY-MM', value, pub_date), ...]。返回写入条数。"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    rows = [(code, p, v, value_type, pub or '', now, source, source_url)
            for p, v, pub in points if v is not None]
    with _db() as conn:
        conn.executemany('''INSERT INTO econ_series
            (indicator_code,period,value,value_type,pub_date,capture_time,source,source_url)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(indicator_code,period,value_type) DO UPDATE SET
              value=excluded.value, pub_date=excluded.pub_date,
              capture_time=excluded.capture_time''', rows)
    return len(rows)


def get_series(code, value_type='level', limit=None, as_of=None):
    """取序列(as_of='YYYY-MM' 用于回测点时截断),按期间升序。"""
    q = '''SELECT period, value, pub_date FROM econ_series
           WHERE indicator_code=? AND value_type=?'''
    args = [code, value_type]
    if as_of:
        q += ' AND period<=?'
        args.append(as_of)
    q += ' ORDER BY period'
    if limit:
        q += ' LIMIT ?'
        args.append(limit)
    with _db() as conn:
        return [(r['period'], r['value'], r['pub_date'])
                for r in conn.execute(q, args)]


def get_indicators(region=None):
    q = 'SELECT * FROM econ_indicator'
    args = []
    if region:
        q += ' WHERE region=?'
        args.append(region)
    q += ' ORDER BY layer, code'
    with _db() as conn:
        return [dict(r) for r in conn.execute(q, args)]


def save_phase(scope, month, phase, score, reasons):
    with _db() as conn:
        conn.execute('''INSERT INTO econ_phase(scope,month,phase,score,reasons,created_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(scope,month) DO UPDATE SET phase=excluded.phase,
              score=excluded.score, reasons=excluded.reasons,
              created_at=excluded.created_at''',
                     (scope, month, phase, score, reasons,
                      datetime.now().strftime('%Y-%m-%d %H:%M:%S')))


def get_phases(scope):
    with _db() as conn:
        return [dict(r) for r in conn.execute(
            'SELECT * FROM econ_phase WHERE scope=? ORDER BY month', (scope,))]
