import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
from pathlib import Path

ROOT = Path(".")
RECON_PATH = ROOT / "outputs" / "market_reconstruction" / "phase7c_trade_reconciliation.csv"

df = pd.read_csv(RECON_PATH)
df['pnl_num'] = df['recorded_pnl'].astype(float)
df['holding_sec'] = (pd.to_datetime(df['close_time_utc']) - pd.to_datetime(df['open_time_utc'])).dt.total_seconds()
df['holding_min'] = df['holding_sec'] / 60.0
df['open_dt'] = pd.to_datetime(df['recorded_open_time'])
df['hour_broker'] = df['open_dt'].dt.hour
df['minute_broker'] = df['open_dt'].dt.minute
df['dow'] = df['open_dt'].dt.day_name()
df['implied_pnl_move'] = df['pnl_num'] / (df['volume'] * 100.0)

print("=== 1. SUMMARY STATS ===")
print(f"Total trades: {len(df)}")
print(f"Buys: {(df['side']=='Buy').sum()}, Sells: {(df['side']=='Sell').sum()}")
print("Volume counts:\n", df['volume'].value_counts().to_dict())

print("\n=== 2. HOLDING DURATION ===")
print(f"Min: {df['holding_min'].min():.2f}m")
print(f"25th percentile: {df['holding_min'].quantile(0.25):.2f}m")
print(f"Median: {df['holding_min'].median():.2f}m")
print(f"75th percentile: {df['holding_min'].quantile(0.75):.2f}m")
print(f"90th percentile: {df['holding_min'].quantile(0.90):.2f}m")
print(f"95th percentile: {df['holding_min'].quantile(0.95):.2f}m")
print(f"Max: {df['holding_min'].max():.2f}m")
print(f"Trades closed <= 1 min: {(df['holding_min'] <= 1.0).sum()}")
print(f"Trades closed <= 5 min: {(df['holding_min'] <= 5.0).sum()}")
print(f"Trades closed <= 15 min: {(df['holding_min'] <= 15.0).sum()}")
print(f"Trades closed <= 30 min: {(df['holding_min'] <= 30.0).sum()}")
print(f"Trades closed > 60 min: {(df['holding_min'] > 60.0).sum()}")

print("\n=== 3. PNL STATS ===")
wins = df[df['pnl_num'] > 0]
losses = df[df['pnl_num'] <= 0]
print(f"Win count: {len(wins)} ({len(wins)/len(df)*100:.2f}%)")
print(f"Loss count: {len(losses)} ({len(losses)/len(df)*100:.2f}%)")
print(f"Total PnL: ${df['pnl_num'].sum():.2f}")
print(f"Gross Profit: ${wins['pnl_num'].sum():.2f}")
print(f"Gross Loss: ${losses['pnl_num'].sum():.2f}")
print(f"Profit Factor: {wins['pnl_num'].sum() / abs(losses['pnl_num'].sum()):.4f}")
print(f"Mean Win: ${wins['pnl_num'].mean():.2f}, Median Win: ${wins['pnl_num'].median():.2f}")
print(f"Mean Loss: ${losses['pnl_num'].mean():.2f}, Median Loss: ${losses['pnl_num'].median():.2f}")
print(f"Win/Loss Payoff Ratio: {wins['pnl_num'].mean() / abs(losses['pnl_num'].mean()):.4f}")
print(f"Max Win: ${df['pnl_num'].max():.2f}")
print(f"Max Loss: ${df['pnl_num'].min():.2f}")

print("\n=== 4. TIMING & SESSION CLUSTERING ===")
print("Trades by Broker Hour (EET/EEST):")
for h, c in df['hour_broker'].value_counts().sort_index().items():
    print(f"  Hour {h:02d}: {c} trades ({c/len(df)*100:.1f}%)")

print("\nTrades by Day of Week:")
for d, c in df['dow'].value_counts().items():
    print(f"  {d:9s}: {c} trades ({c/len(df)*100:.1f}%)")

print("\nMinute of hour distribution top 10:")
print(df['minute_broker'].value_counts().head(10).to_dict())

print("\n=== 5. POSITION SIZING & SEQUENCE ANALYSIS ===")
df['prev_pnl'] = df['pnl_num'].shift(1)
df['prev_win'] = df['prev_pnl'] > 0
df['is_win'] = df['pnl_num'] > 0

# Check after win vs after loss
after_win = df[df['prev_win'] == True]
after_loss = df[df['prev_win'] == False]
print(f"Win rate after Win: {after_win['is_win'].mean()*100:.2f}% (N={len(after_win)})")
print(f"Win rate after Loss: {after_loss['is_win'].mean()*100:.2f}% (N={len(after_loss)})")

# Check lot size escalation
print("Volume after Loss:")
print(after_loss['volume'].value_counts().to_dict())
print("Volume after Win:")
print(after_win['volume'].value_counts().to_dict())

# Consecutive loss sequences
loss_streaks = []
cur_streak = 0
for pnl in df['pnl_num']:
    if pnl <= 0:
        cur_streak += 1
    else:
        if cur_streak > 0:
            loss_streaks.append(cur_streak)
        cur_streak = 0
if cur_streak > 0:
    loss_streaks.append(cur_streak)
print("Max consecutive losses:", max(loss_streaks) if loss_streaks else 0)
print("Loss streak counts:", pd.Series(loss_streaks).value_counts().to_dict())

# Volume = 0.02 analysis
v02 = df[df['volume'] == 0.02]
print(f"\n0.02 lot trades (N={len(v02)}):")
print("Dates of 0.02 trades:", v02['open_dt'].dt.strftime("%Y-%m-%d").tolist())
print("0.02 trades win rate:", (v02['pnl_num'] > 0).mean()*100)
print("0.02 trades prev_pnl:", v02['prev_pnl'].tolist())
