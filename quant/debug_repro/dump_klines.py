import json
import sys
import pandas as pd

path = sys.argv[1] if len(sys.argv) > 1 else "data/kline/000001/30min.parquet"
df = pd.read_parquet(path)
df = df.sort_values("datetime").reset_index(drop=True)

med = df["close"].median()
df = df[(df["close"] > med / 3) & (df["close"] < med * 3)].reset_index(drop=True)

rows = []
for _, r in df.iterrows():
    ts = int(pd.Timestamp(r["datetime"]).timestamp())
    rows.append({
        "time": pd.Timestamp(r["datetime"]).strftime("%Y-%m-%d %H:%M"),
        "timestamp": ts,
        "open": float(r["open"]),
        "high": float(r["high"]),
        "low": float(r["low"]),
        "close": float(r["close"]),
        "volume": float(r["volume"]),
    })

out = sys.argv[2] if len(sys.argv) > 2 else "debug_repro/klines.json"
with open(out, "w", encoding="utf-8") as f:
    json.dump(rows, f)
print(f"wrote {len(rows)} bars to {out}")
print("first:", rows[0])
print("last:", rows[-1])
