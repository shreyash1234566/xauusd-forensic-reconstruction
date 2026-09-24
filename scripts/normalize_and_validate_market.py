"""
Normalize Dukascopy raw UTC data → broker-time (UTC+3) normalized CSV.
Run from project root: .venv\Scripts\python scripts/normalize_and_validate_market.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "data" / "market" / "raw" / "xauusd_m1_utc_raw.csv"
NORM_PATH = ROOT / "data" / "market" / "normalized" / "xauusd_m1.csv"
META_PATH = ROOT / "data" / "market" / "metadata.json"

# Broker timezone offset relative to the Dukascopy UTC feed
BROKER_UTC_OFFSET_HOURS = 3


def main() -> None:
    print(f"Loading raw Dukascopy M1 feed: {RAW_PATH}")
    df = pd.read_csv(RAW_PATH)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    print(f"  Raw rows: {len(df):,}")
    print(f"  UTC range: {df['timestamp'].min()} → {df['timestamp'].max()}")

    # ---- Shift to broker time ----------------------------------------
    df["timestamp"] = df["timestamp"] + pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    print(f"\nAfter UTC+{BROKER_UTC_OFFSET_HOURS} shift (broker time):")
    print(f"  Range: {df['timestamp'].min()} → {df['timestamp'].max()}")

    # ---- OHLC integrity checks ---------------------------------------
    bad_hl = (df["high"] < df["low"]).sum()
    bad_oh = (df["open"] > df["high"]).sum()
    bad_ol = (df["open"] < df["low"]).sum()
    bad_ch = (df["close"] > df["high"]).sum()
    bad_cl = (df["close"] < df["low"]).sum()
    print(f"\nOHLC integrity checks:")
    print(f"  high < low:   {bad_hl}")
    print(f"  open > high:  {bad_oh}")
    print(f"  open < low:   {bad_ol}")
    print(f"  close > high: {bad_ch}")
    print(f"  close < low:  {bad_cl}")

    # ---- Gap analysis ------------------------------------------------
    df_sorted = df.sort_values("timestamp").reset_index(drop=True)
    diffs = df_sorted["timestamp"].diff().dt.total_seconds().dropna()
    large_gaps = diffs[diffs > 300]  # > 5 minutes
    print(f"\nGap analysis (gaps > 5 min):")
    print(f"  Count: {len(large_gaps)}")
    print(f"  Largest gap: {large_gaps.max() / 60:.1f} min")
    if len(large_gaps) > 0:
        gap_times = df_sorted.loc[large_gaps.index, "timestamp"]
        print(f"  First 10 gap timestamps (end of gap):")
        for ts in gap_times.head(10):
            print(f"    {ts}")

    # ---- Save normalized -----------------------------------------
    df_sorted.to_csv(NORM_PATH, index=False)
    print(f"\nNormalized file saved: {NORM_PATH}")
    print(f"  Rows: {len(df_sorted):,}")

    # ---- Verify anchor trade alignment ----------------------------
    print("\n--- Trade Alignment Verification ---")
    # First trade in dataset: 2025-09-25 19:32:56, Buy, price 3736.13
    first_trade_time = pd.Timestamp("2025-09-25 19:32:56")
    first_trade_price = 3736.13

    bar_idx = df_sorted["timestamp"].searchsorted(first_trade_time, side="right") - 1
    if bar_idx >= 0:
        bar = df_sorted.iloc[bar_idx]
        contained = bar["low"] <= first_trade_price <= bar["high"]
        print(f"  Trade entry:  {first_trade_time} @ {first_trade_price}")
        print(f"  Matched bar:  {bar['timestamp']} OHLCV= {bar['open']:.3f}/{bar['high']:.3f}/{bar['low']:.3f}/{bar['close']:.3f}")
        print(f"  Price in bar range: {contained}")
        spread_proxy = first_trade_price - bar["close"]
        print(f"  Price vs bar close: {spread_proxy:+.3f} (proxy for spread estimate)")

    # ---- Write metadata ------------------------------------------
    meta = {
        "source": "Dukascopy historical bid prices",
        "instrument": "XAUUSD",
        "price_type": "bid",
        "timeframe": "M1",
        "raw_timezone": "UTC",
        "normalized_timezone": f"UTC+{BROKER_UTC_OFFSET_HOURS} (broker time / EET)",
        "utc_offset_hours": BROKER_UTC_OFFSET_HOURS,
        "raw_file": str(RAW_PATH),
        "normalized_file": str(NORM_PATH),
        "raw_row_count": len(df),
        "normalized_row_count": len(df_sorted),
        "date_from": str(df_sorted["timestamp"].min()),
        "date_to": str(df_sorted["timestamp"].max()),
        "ohlc_integrity": {
            "bad_high_lt_low": int(bad_hl),
            "bad_open_gt_high": int(bad_oh),
            "bad_open_lt_low": int(bad_ol),
            "bad_close_gt_high": int(bad_ch),
            "bad_close_lt_low": int(bad_cl),
        },
        "gap_count_gt5min": int(len(large_gaps)),
        "anchor_verification": {
            "trade_timestamp": str(first_trade_time),
            "trade_price": first_trade_price,
            "bar_timestamp": str(bar["timestamp"]),
            "bar_open": float(bar["open"]),
            "bar_high": float(bar["high"]),
            "bar_low": float(bar["low"]),
            "bar_close": float(bar["close"]),
            "price_in_bar_range": bool(contained),
            "price_minus_bar_close": float(spread_proxy),
        },
    }
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print(f"\nMetadata saved: {META_PATH}")
    print("\n✓ Normalization and validation complete.")


if __name__ == "__main__":
    main()
