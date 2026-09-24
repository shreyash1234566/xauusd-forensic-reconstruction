"""
Phase 8B - Stage 3: Tick Microstructure & Pre-Entry Event Sequences (1s - 60s)
Extracts fine-grained tick dynamics leading up to entry execution on 7.1M+ raw ticks.
Deterministic Medium stage (~5-10 seconds).
"""

from pathlib import Path
from datetime import timedelta
import json
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

def main():
    print("=================================================================")
    print("PHASE 8B - STAGE 03: TICK MICROSTRUCTURE EXTRACTION")
    print("=================================================================")

    trades = pd.read_csv(RECON_PATH)
    trades['open_dt_utc'] = pd.to_datetime(trades['open_time_utc'])
    print(f"Analyzing pre-entry tick trajectories for {len(trades)} trades...")

    tick_cache = TickCache(TICKS_DIR)
    micro_records = []
    windows_sec = [1, 3, 5, 10, 30, 60]

    for idx, r in trades.iterrows():
        t_open = r['open_dt_utc']
        open_ms = int(t_open.timestamp() * 1000)

        # Query 90 seconds prior to entry
        tdf = tick_cache.get_range_ticks(t_open - timedelta(seconds=90), t_open + timedelta(seconds=5))

        rec = {
            'ticket': r['ticket'],
            'side': r['side'],
            'open_time_utc': r['open_time_utc'],
            'recorded_price': r['recorded_price'],
        }

        if tdf is None or len(tdf) == 0:
            for w in windows_sec:
                rec[f'ret_{w}s'] = np.nan
                rec[f'tick_count_{w}s'] = np.nan
                rec[f'spread_{w}s'] = np.nan
                rec[f'consec_upticks_{w}s'] = np.nan
                rec[f'accel_{w}s'] = np.nan
            micro_records.append(rec)
            continue

        entry_ticks = tdf[tdf['ts'] <= open_ms]
        if len(entry_ticks) == 0:
            entry_ticks = tdf.iloc[:1]

        p_entry_mid = entry_ticks.iloc[-1]['mid']
        rec['entry_mid_tick'] = p_entry_mid
        rec['entry_spread'] = entry_ticks.iloc[-1]['spread']

        for w in windows_sec:
            w_ticks = tdf[(tdf['ts'] <= open_ms) & (tdf['ts'] >= open_ms - w * 1000)]
            if len(w_ticks) >= 2:
                p_start = w_ticks.iloc[0]['mid']
                p_end = w_ticks.iloc[-1]['mid']
                ret = p_end - p_start
                cnt = len(w_ticks)
                spread_mean = w_ticks['spread'].mean()

                diffs = np.diff(w_ticks['mid'].values)
                consec_up = int(np.sum(diffs > 0) - np.sum(diffs < 0))

                half = len(w_ticks) // 2
                if half >= 1:
                    ret_h1 = w_ticks.iloc[half]['mid'] - w_ticks.iloc[0]['mid']
                    ret_h2 = w_ticks.iloc[-1]['mid'] - w_ticks.iloc[half]['mid']
                    accel = ret_h2 - ret_h1
                else:
                    accel = 0.0

                rec[f'ret_{w}s'] = ret
                rec[f'tick_count_{w}s'] = cnt
                rec[f'spread_{w}s'] = spread_mean
                rec[f'consec_upticks_{w}s'] = consec_up
                rec[f'accel_{w}s'] = accel
            else:
                rec[f'ret_{w}s'] = 0.0
                rec[f'tick_count_{w}s'] = len(w_ticks)
                rec[f'spread_{w}s'] = entry_ticks.iloc[-1]['spread']
                rec[f'consec_upticks_{w}s'] = 0
                rec[f'accel_{w}s'] = 0.0

        micro_records.append(rec)

    micro_df = pd.DataFrame(micro_records)
    out_micro_path = OUTPUT_DIR / "phase8b_tick_microstructure.csv"
    micro_df.to_csv(out_micro_path, index=False)
    print(f"[PASS] Saved microstructure dataset: {out_micro_path} ({len(micro_df)} rows)")

    # Compute Event Sequences Capture Rates
    valid_micro = micro_df.dropna(subset=['ret_5s', 'ret_1s']).copy()
    valid_micro['target_dir'] = (valid_micro['side'] == 'Buy').astype(int)

    seq_results = []
    for w in [5, 10, 30]:
        for thresh in [0.25, 0.50, 0.75, 1.00]:
            # Momentum Continuation
            cap_c = ((valid_micro['target_dir'] == 1) & (valid_micro[f'ret_{w}s'] >= thresh)).sum() + \
                    ((valid_micro['target_dir'] == 0) & (valid_micro[f'ret_{w}s'] <= -thresh)).sum()

            # Momentum Reversal
            cap_r = ((valid_micro['target_dir'] == 1) & (valid_micro[f'ret_{w}s'] <= -thresh)).sum() + \
                    ((valid_micro['target_dir'] == 0) & (valid_micro[f'ret_{w}s'] >= thresh)).sum()

            seq_results.append({
                'window_sec': w,
                'threshold_dollar': thresh,
                'continuation_trades': cap_c,
                'continuation_pct': cap_c / len(valid_micro) * 100.0,
                'reversal_trades': cap_r,
                'reversal_pct': cap_r / len(valid_micro) * 100.0
            })

    seq_df = pd.DataFrame(seq_results)
    out_seq_path = OUTPUT_DIR / "phase8b_entry_event_sequences.csv"
    seq_df.to_csv(out_seq_path, index=False)
    print(f"[PASS] Saved event sequence comparison: {out_seq_path}")

    print("\nPre-Entry Momentum vs Reversal Capture Rates:")
    print(seq_df.to_string(index=False))

    print("\nSTAGE 03 COMPLETE.\n")

if __name__ == "__main__":
    main()
