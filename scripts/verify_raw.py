import pandas as pd
from pathlib import Path

raw_path = Path("data/raw/trades_raw.tsv")
lines = [l for l in raw_path.read_text(encoding="utf-8").splitlines() if l.strip()]

print(f"Total non-empty lines: {len(lines)}")

df = pd.read_csv(
    raw_path,
    sep="\t",
    header=None,
    dtype=str,
    names=["ticket", "side", "open_time", "close_time", "symbol", "lot_size", "observed_price", "pnl"]
)

print(f"1. Row count: {len(df)}")
print(f"2. Column count: {df.shape[1]}")
print(f"3. Unique symbols: {df['symbol'].unique().tolist()}")

df["open_dt"] = pd.to_datetime(df["open_time"])
df["close_dt"] = pd.to_datetime(df["close_time"])
df["lot_size_num"] = pd.to_numeric(df["lot_size"])
df["pnl_num"] = pd.to_numeric(df["pnl"])

print(f"4. Minimum open timestamp: {df['open_dt'].min()}")
print(f"5. Maximum open timestamp: {df['open_dt'].max()}")
print(f"6. Minimum close timestamp: {df['close_dt'].min()}")
print(f"7. Maximum close timestamp: {df['close_dt'].max()}")

print(f"8. Buy count: {(df['side'] == 'Buy').sum()}")
print(f"9. Sell count: {(df['side'] == 'Sell').sum()}")

print(f"10. Lot-size frequency: {df['lot_size_num'].value_counts().sort_index().to_dict()}")
print(f"11. P&L total: {df['pnl_num'].sum():.2f}")
print(f"12. P&L minimum: {df['pnl_num'].min():.2f}")
print(f"13. P&L maximum: {df['pnl_num'].max():.2f}")

print("\n14. First 3 rows:")
for i in range(min(3, len(df))):
    r = df.iloc[i]
    print(f"  Row {i+1}: {r['ticket']}\t{r['side']}\t{r['open_time']}\t{r['close_time']}\t{r['symbol']}\t{r['lot_size']}\t{r['observed_price']}\t{r['pnl']}")

print("\n15. Last 3 rows:")
for i in range(max(0, len(df)-3), len(df)):
    r = df.iloc[i]
    print(f"  Row {i+1}: {r['ticket']}\t{r['side']}\t{r['open_time']}\t{r['close_time']}\t{r['symbol']}\t{r['lot_size']}\t{r['observed_price']}\t{r['pnl']}")
