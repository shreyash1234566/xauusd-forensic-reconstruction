import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(".")
RECON_PATH = ROOT / "outputs" / "market_reconstruction" / "phase7c_trade_reconciliation.csv"
TICKS_DIR = ROOT / "data" / "market" / "raw_ticks"

df = pd.read_csv(RECON_PATH)

def load_hour_ticks(dt_utc):
    iso_str = dt_utc.strftime("%Y-%m-%dT%H-00-00-000Z")
    p = TICKS_DIR / f"xauusd_ticks_{iso_str}.json"
    if not p.exists():
        return None
    with open(p, 'r') as f:
        data = json.load(f)
    if not data or len(data) == 0:
        return None
    arr = np.array(data, dtype=float)
    # [ts_ms, ask, bid, ask_v, bid_v]
    ts = arr[:, 0]
    ask = arr[:, 1]
    bid = arr[:, 2]
    mid = (ask + bid) / 2.0
    return pd.DataFrame({'ts': ts, 'ask': ask, 'bid': bid, 'mid': mid})

mfe_list = []
mae_list = []
df['pnl_num'] = df['recorded_pnl'].astype(float)
df['implied_pnl_move'] = df['pnl_num'] / (df['volume'] * 100.0)

for idx, r in df.iterrows():
    side = r['side']
    entry_p = float(r['entry_tick_mid'])

    # parse open and close utc
    t_open = pd.to_datetime(r['open_time_utc'])
    t_close = pd.to_datetime(r['close_time_utc'])

    cur_h = t_open.replace(minute=0, second=0, microsecond=0)
    end_h = t_close.replace(minute=0, second=0, microsecond=0)

    ticks = []
    h = cur_h
    while h <= end_h + timedelta(hours=1):
        tdf = load_hour_ticks(h)
        if tdf is not None:
            ticks.append(tdf)
        h += timedelta(hours=1)

    if len(ticks) == 0:
        mfe_list.append(np.nan)
        mae_list.append(np.nan)
        continue

    all_ticks = pd.concat(ticks, ignore_index=True)
    open_ms = int(t_open.timestamp() * 1000)
    close_ms = int(t_close.timestamp() * 1000)

    trade_ticks = all_ticks[(all_ticks['ts'] >= open_ms) & (all_ticks['ts'] <= close_ms)]
    if len(trade_ticks) == 0:
        trade_ticks = all_ticks[(all_ticks['ts'] >= open_ms - 2000) & (all_ticks['ts'] <= close_ms + 2000)]

    if len(trade_ticks) == 0:
        mfe_list.append(np.nan)
        mae_list.append(np.nan)
        continue

    if side == 'Buy':
        excursions = trade_ticks['mid'] - entry_p
        mfe = float(excursions.max())
        mae = float(-excursions.min() if excursions.min() < 0 else 0.0)
    else:
        excursions = entry_p - trade_ticks['mid']
        mfe = float(excursions.max())
        mae = float(-excursions.min() if excursions.min() < 0 else 0.0)

    mfe_list.append(mfe)
    mae_list.append(mae)

df['mfe'] = mfe_list
df['mae'] = mae_list

valid_mfe = df.dropna(subset=['mfe', 'mae'])
print(f"Computed MFE/MAE for {len(valid_mfe)}/{len(df)} trades")
print("\n=== MFE (Maximum Favorable Excursion) ===")
print(f"Median MFE: ${valid_mfe['mfe'].median():.2f}/oz")
print(f"Mean MFE: ${valid_mfe['mfe'].mean():.2f}/oz")
print(f"P25 MFE: ${valid_mfe['mfe'].quantile(0.25):.2f}/oz")
print(f"P75 MFE: ${valid_mfe['mfe'].quantile(0.75):.2f}/oz")
print(f"P95 MFE: ${valid_mfe['mfe'].quantile(0.95):.2f}/oz")
print(f"Max MFE: ${valid_mfe['mfe'].max():.2f}/oz")

print("\n=== MAE (Maximum Adverse Excursion) ===")
print(f"Median MAE: ${valid_mfe['mae'].median():.2f}/oz")
print(f"Mean MAE: ${valid_mfe['mae'].mean():.2f}/oz")
print(f"P25 MAE: ${valid_mfe['mae'].quantile(0.25):.2f}/oz")
print(f"P75 MAE: ${valid_mfe['mae'].quantile(0.75):.2f}/oz")
print(f"P95 MAE: ${valid_mfe['mae'].quantile(0.95):.2f}/oz")
print(f"Max MAE: ${valid_mfe['mae'].max():.2f}/oz")

# Losses MAE and Wins MAE
win_mfe = valid_mfe[valid_mfe['pnl_num'] > 0]
loss_mfe = valid_mfe[valid_mfe['pnl_num'] <= 0]
print(f"\nWins Median MFE: ${win_mfe['mfe'].median():.2f}/oz, Median MAE: ${win_mfe['mae'].median():.2f}/oz")
print(f"Losses Median MFE: ${loss_mfe['mfe'].median():.2f}/oz, Median MAE: ${loss_mfe['mae'].median():.2f}/oz")
print(f"Losses Max MAE: ${loss_mfe['mae'].max():.2f}/oz")

# Check realized move vs MFE (Take profit capture ratio)
win_capture = (win_mfe['implied_pnl_move'] / win_mfe['mfe']).replace([np.inf, -np.inf], np.nan).dropna()
print(f"Take Profit Capture Ratio for Wins (Realized Move / MFE) Median: {win_capture.median():.4f}")
print(f"Take Profit Capture Ratio Mean: {win_capture.mean():.4f}")
