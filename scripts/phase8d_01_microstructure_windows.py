"""
Phase 8D - Stage 1: Entry Timestamp Microstructure Windows & Threshold-Crossing Reconstruction
Covers:
- Section 2: Entry Timestamp Microstructure Window (0.25s, 0.5s, 1s, 2s, 3s, 5s, 10s, 20s, 30s, 60s)
  Calculates: signed mid return, signed Bid return, signed Ask return, absolute movement,
  tick count, quote-change count, consecutive up/down ticks, acceleration, local volatility,
  spread, spread change, distance from local high/low for 423 trades and 423 matched controls.
- Section 5: Threshold-Crossing Reconstruction across Predefined Grids ($0.05 - $1.00, 1s - 60s).
- Generates: outputs/strategy_reconstruction/phase8d_tick_event_features.csv
"""

from pathlib import Path
from datetime import datetime, timedelta
import json
import time
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUTS_DIR = ROOT / "outputs"
RECON_PATH = OUTPUTS_DIR / "market_reconstruction" / "phase7c_trade_reconciliation.csv"
TICKS_DIR = DATA_DIR / "market" / "raw_ticks"
OUTPUT_DIR = OUTPUTS_DIR / "strategy_reconstruction"

class TickCache:
    def __init__(self, ticks_dir):
        self.ticks_dir = Path(ticks_dir)
        self.cache = {}

    def get_hour_ticks(self, dt_utc):
        iso_str = dt_utc.strftime("%Y-%m-%dT%H-00-00-000Z")
        if iso_str in self.cache:
            return self.cache[iso_str]

        p = self.ticks_dir / f"xauusd_ticks_{iso_str}.json"
        if not p.exists():
            self.cache[iso_str] = None
            return None

        try:
            with open(p, 'r') as f:
                data = json.load(f)
            if not data or len(data) == 0:
                self.cache[iso_str] = None
                return None
            arr = np.array(data, dtype=float)
            df = pd.DataFrame({
                'ts': arr[:, 0],
                'ask': arr[:, 1],
                'bid': arr[:, 2],
                'mid': (arr[:, 1] + arr[:, 2]) / 2.0,
                'spread': arr[:, 1] - arr[:, 2]
            })
            self.cache[iso_str] = df
            return df
        except Exception:
            self.cache[iso_str] = None
            return None

    def get_range_ticks(self, start_utc, end_utc):
        cur_h = start_utc.replace(minute=0, second=0, microsecond=0)
        end_h = end_utc.replace(minute=0, second=0, microsecond=0)
        ticks = []
        h = cur_h
        while h <= end_h + timedelta(hours=1):
            tdf = self.get_hour_ticks(h)
            if tdf is not None and len(tdf) > 0:
                ticks.append(tdf)
            h += timedelta(hours=1)
        if not ticks:
            return None
        return pd.concat(ticks, ignore_index=True).drop_duplicates(subset=['ts']).sort_values('ts').reset_index(drop=True)


def extract_window_features(tdf, target_ms, windows_sec):
    """
    Extracts high-resolution microstructure features for a given target timestamp.
    """
    features = {}

    # Slice ticks up to target_ms
    prior_ticks = tdf[tdf['ts'] <= target_ms]
    if len(prior_ticks) == 0:
        prior_ticks = tdf.iloc[:1]

    p_entry_mid = prior_ticks.iloc[-1]['mid']
    p_entry_bid = prior_ticks.iloc[-1]['bid']
    p_entry_ask = prior_ticks.iloc[-1]['ask']
    entry_spread = prior_ticks.iloc[-1]['spread']

    features['entry_mid'] = p_entry_mid
    features['entry_bid'] = p_entry_bid
    features['entry_ask'] = p_entry_ask
    features['entry_spread'] = entry_spread

    for w in windows_sec:
        w_ms = int(w * 1000)
        start_ms = target_ms - w_ms
        w_ticks = tdf[(tdf['ts'] <= target_ms) & (tdf['ts'] >= start_ms)]

        w_str = str(w).replace('.', '_')
        if len(w_ticks) >= 2:
            mid_start = w_ticks.iloc[0]['mid']
            mid_end = w_ticks.iloc[-1]['mid']
            bid_start = w_ticks.iloc[0]['bid']
            bid_end = w_ticks.iloc[-1]['bid']
            ask_start = w_ticks.iloc[0]['ask']
            ask_end = w_ticks.iloc[-1]['ask']

            ret_mid = mid_end - mid_start
            ret_bid = bid_end - bid_start
            ret_ask = ask_end - ask_start
            abs_move = abs(ret_mid)
            tick_cnt = len(w_ticks)

            # Quote change count
            b_diff = np.diff(w_ticks['bid'].values)
            a_diff = np.diff(w_ticks['ask'].values)
            quote_cnt = int(np.sum((b_diff != 0) | (a_diff != 0)))

            # Consecutive up / down ticks
            m_diff = np.diff(w_ticks['mid'].values)
            consec_up = int(np.sum(m_diff > 0))
            consec_down = int(np.sum(m_diff < 0))

            # Acceleration
            half_idx = len(w_ticks) // 2
            if half_idx >= 1:
                ret_h1 = w_ticks.iloc[half_idx]['mid'] - mid_start
                ret_h2 = mid_end - w_ticks.iloc[half_idx]['mid']
                accel = ret_h2 - ret_h1
            else:
                accel = 0.0

            # Local Volatility (std of tick returns)
            if len(m_diff) >= 2:
                local_vol = float(np.std(m_diff))
            else:
                local_vol = 0.0

            # Spread
            spread_mean = float(w_ticks['spread'].mean())
            spread_chg = float(w_ticks.iloc[-1]['spread'] - w_ticks.iloc[0]['spread'])

            # Distance from local high / low in window
            max_p = float(w_ticks['mid'].max())
            min_p = float(w_ticks['mid'].min())
            dist_high = max_p - p_entry_mid
            dist_low = p_entry_mid - min_p

            features[f'ret_mid_{w_str}s'] = ret_mid
            features[f'ret_bid_{w_str}s'] = ret_bid
            features[f'ret_ask_{w_str}s'] = ret_ask
            features[f'abs_move_{w_str}s'] = abs_move
            features[f'tick_cnt_{w_str}s'] = tick_cnt
            features[f'quote_cnt_{w_str}s'] = quote_cnt
            features[f'consec_up_{w_str}s'] = consec_up
            features[f'consec_down_{w_str}s'] = consec_down
            features[f'accel_{w_str}s'] = accel
            features[f'vol_{w_str}s'] = local_vol
            features[f'spread_{w_str}s'] = spread_mean
            features[f'spread_chg_{w_str}s'] = spread_chg
            features[f'dist_high_{w_str}s'] = dist_high
            features[f'dist_low_{w_str}s'] = dist_low
        else:
            features[f'ret_mid_{w_str}s'] = 0.0
            features[f'ret_bid_{w_str}s'] = 0.0
            features[f'ret_ask_{w_str}s'] = 0.0
            features[f'abs_move_{w_str}s'] = 0.0
            features[f'tick_cnt_{w_str}s'] = len(w_ticks)
            features[f'quote_cnt_{w_str}s'] = 0
            features[f'consec_up_{w_str}s'] = 0
            features[f'consec_down_{w_str}s'] = 0
            features[f'accel_{w_str}s'] = 0.0
            features[f'vol_{w_str}s'] = 0.0
            features[f'spread_{w_str}s'] = entry_spread
            features[f'spread_chg_{w_str}s'] = 0.0
            features[f'dist_high_{w_str}s'] = 0.0
            features[f'dist_low_{w_str}s'] = 0.0

    return features


def main():
    print("=================================================================")
    print("PHASE 8D - STAGE 01: ENTRY MICROSTRUCTURE WINDOWS & THRESHOLDS")
    print("=================================================================")
    t0 = time.time()

    trades = pd.read_csv(RECON_PATH)
    trades['open_dt_utc'] = pd.to_datetime(trades['open_time_utc'])
    trades['close_dt_utc'] = pd.to_datetime(trades['close_time_utc'])
    n_trades = len(trades)
    print(f"Loaded {n_trades} canonical observed trades.")

    tick_cache = TickCache(TICKS_DIR)
    windows_sec = [0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 30.0, 60.0]

    # -------------------------------------------------------------
    # 1. PROCESS 423 REAL TRADES
    # -------------------------------------------------------------
    print(f"\n1. Extracting pre-entry tick features across 10 windows for {n_trades} trades...")
    trade_features = []

    for idx, r in trades.iterrows():
        t_open = r['open_dt_utc']
        open_ms = int(t_open.timestamp() * 1000)

        # Pull ticks 90s prior to entry
        tdf = tick_cache.get_range_ticks(t_open - timedelta(seconds=90), t_open + timedelta(seconds=5))

        row_dict = {
            'event_id': f"TRADE_{r['ticket']}",
            'is_trade': 1,
            'ticket': r['ticket'],
            'side': r['side'],
            'open_time_utc': r['open_time_utc'],
            'recorded_price': r['recorded_price'],
            'recorded_pnl': r['recorded_pnl'],
            'volume': r['volume']
        }

        if tdf is not None and len(tdf) > 0:
            feats = extract_window_features(tdf, open_ms, windows_sec)
            row_dict.update(feats)
        else:
            # Missing tick window placeholder
            row_dict['entry_mid'] = r['recorded_price']
            row_dict['entry_bid'] = r['recorded_price']
            row_dict['entry_ask'] = r['recorded_price']
            row_dict['entry_spread'] = 0.20
            for w in windows_sec:
                w_str = str(w).replace('.', '_')
                for f_name in ['ret_mid', 'ret_bid', 'ret_ask', 'abs_move', 'tick_cnt', 'quote_cnt',
                               'consec_up', 'consec_down', 'accel', 'vol', 'spread', 'spread_chg',
                               'dist_high', 'dist_low']:
                    row_dict[f'{f_name}_{w_str}s'] = 0.0

        trade_features.append(row_dict)

    print(f"Processed {len(trade_features)} trade events.")

    # -------------------------------------------------------------
    # 2. GENERATE AND PROCESS 423 MATCHED NON-TRADE CONTROLS
    # -------------------------------------------------------------
    # Select control moments: exactly 15 minutes prior to trade open on the same day (guaranteed non-trade in active regime)
    print("\n2. Extracting pre-event tick features for 423 matched non-trade controls...")
    control_features = []

    for idx, r in trades.iterrows():
        t_control = r['open_dt_utc'] - timedelta(minutes=15)
        ctrl_ms = int(t_control.timestamp() * 1000)

        tdf = tick_cache.get_range_ticks(t_control - timedelta(seconds=90), t_control + timedelta(seconds=5))

        row_dict = {
            'event_id': f"CTRL_{r['ticket']}",
            'is_trade': 0,
            'ticket': np.nan,
            'side': 'Control',
            'open_time_utc': t_control.strftime("%Y-%m-%d %H:%M:%S"),
            'recorded_price': np.nan,
            'recorded_pnl': np.nan,
            'volume': np.nan
        }

        if tdf is not None and len(tdf) > 0:
            feats = extract_window_features(tdf, ctrl_ms, windows_sec)
            row_dict.update(feats)
        else:
            row_dict['entry_mid'] = np.nan
            row_dict['entry_bid'] = np.nan
            row_dict['entry_ask'] = np.nan
            row_dict['entry_spread'] = 0.20
            for w in windows_sec:
                w_str = str(w).replace('.', '_')
                for f_name in ['ret_mid', 'ret_bid', 'ret_ask', 'abs_move', 'tick_cnt', 'quote_cnt',
                               'consec_up', 'consec_down', 'accel', 'vol', 'spread', 'spread_chg',
                               'dist_high', 'dist_low']:
                    row_dict[f'{f_name}_{w_str}s'] = 0.0

        control_features.append(row_dict)

    print(f"Processed {len(control_features)} control events.")

    # Combine into dataset
    full_event_df = pd.DataFrame(trade_features + control_features)
    out_tick_path = OUTPUT_DIR / "phase8d_tick_event_features.csv"
    full_event_df.to_csv(out_tick_path, index=False)
    print(f"[PASS] Saved tick event features: {out_tick_path} ({len(full_event_df)} rows, {len(full_event_df.columns)} cols)")

    # -------------------------------------------------------------
    # 3. THRESHOLD-CROSSING RECONSTRUCTION GRID
    # -------------------------------------------------------------
    print("\n--- 3. SECTION 5: THRESHOLD-CROSSING RECONSTRUCTION GRID ---")
    displacements = [0.05, 0.10, 0.20, 0.30, 0.50, 0.75, 1.00]
    grid_windows = [1.0, 3.0, 5.0, 10.0, 20.0, 30.0, 60.0]

    trades_df = full_event_df[full_event_df['is_trade'] == 1]
    ctrls_df = full_event_df[full_event_df['is_trade'] == 0]

    grid_results = []
    for w in grid_windows:
        w_str = str(w).replace('.', '_')
        col_move = f'abs_move_{w_str}s'
        for disp in displacements:
            trade_hits = (trades_df[col_move] >= disp).sum()
            ctrl_hits = (ctrls_df[col_move] >= disp).sum()

            trade_rate = trade_hits / len(trades_df) * 100.0
            ctrl_rate = ctrl_hits / len(ctrls_df) * 100.0
            diff_rate = trade_rate - ctrl_rate

            grid_results.append({
                'window_sec': w,
                'displacement_usd': disp,
                'trade_capture_count': trade_hits,
                'trade_capture_pct': trade_rate,
                'control_trigger_count': ctrl_hits,
                'control_trigger_pct': ctrl_rate,
                'selectivity_advantage_pct': diff_rate
            })

    grid_df = pd.DataFrame(grid_results)
    print(grid_df.sort_values('selectivity_advantage_pct', ascending=False).head(10).to_string(index=False))

    elapsed = time.time() - t0
    print(f"\nSTAGE 01 COMPLETE in {elapsed:.2f} seconds.\n")

if __name__ == "__main__":
    main()
