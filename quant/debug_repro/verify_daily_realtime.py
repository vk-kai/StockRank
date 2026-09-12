"""日K盘中实时补充 —— 回归验证脚本。

修复内容（backend/kline_service.py）：
1. 顶部补 logging + logger 定义（修复原 except 块内 logger 未定义的 NameError）
2. 新增 _fetch_today_realtime_bar_df：用实时行情报价合成当天日K
   （pytdx 主、akshare 兜底），替换原来用 pytdx 日线历史接口
   （盘中拿不到当天未收盘K线）的错误数据源。
3. 合理性校验：补充价 / 昨收 比值超出 [0.2, 5.0] 时丢弃补充、降级纯历史，
   防止 000001 这类歧义代码（项目定义为上证指数，但历史是个股）污染K线。

运行：PYTHONUTF8=1 .venv/Scripts/python.exe debug_repro/verify_daily_realtime.py
（盘中 9:30-15:00 运行可不 mock，直接看真实补充；盘外用 mock 触发盘中分支。）
"""
import sys
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, ".")

from backend import kline_service
from backend.kline_service import _fetch_today_realtime_bar_df, get_security_kline

today = datetime.now().strftime("%Y-%m-%d")
print(f"今天: {today}\n")

# [1] 正常代码：盘中补充生效
print("[1] 600519（无歧义）mock 盘中 —— 期望 source 含 +realtime，末根=今天：")
with patch.object(kline_service, "_is_intraday_for_daily_kline", return_value=True):
    p = get_security_kline("600519", "daily", 8, "security")
df = p.get("data")
tc = "date"
print(f"    source={p.get('source')}  末根={df.iloc[-1][tc]}  close={round(float(df.iloc[-1]['close']), 2)}")

# [2] 歧义代码：校验规避，降级纯历史
print("\n[2] 000001（歧义：项目 _SH_INDEX_CODES 定义为上证指数，历史是个股 ~10）mock 盘中 —— 期望 source=local，降级：")
with patch.object(kline_service, "_is_intraday_for_daily_kline", return_value=True):
    p0 = get_security_kline("000001", "daily", 8, "security")
df0 = p0.get("data")
print(f"    source={p0.get('source')}  末根={df0.iloc[-1][tc]}  close={round(float(df0.iloc[-1]['close']), 2)}")

# [3] 异常路径：不抛 NameError
print("\n[3] 异常路径（无效 code）—— 期望不抛 NameError：")
try:
    _fetch_today_realtime_bar_df("999999", "security", today, prev_close=10.0)
    print("    OK（旧代码此处会 NameError）")
except NameError as e:
    print(f"    FAIL NameError: {e}")

# [4] 盘外对照：原逻辑不受影响
print("\n[4] 600519 真实时段（不 mock）—— 期望走原有路径：")
pc = get_security_kline("600519", "daily", 8, "security")
dc = pc.get("data")
print(f"    source={pc.get('source')}  末根={dc.iloc[-1][tc]}")
